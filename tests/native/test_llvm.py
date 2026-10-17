import os
import subprocess
import sys
from pathlib import Path

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from pyjs.web.domx import CustomElement
from tests.backend_semantics import (
    BACKEND_CONTRACTS,
    PORTABLE_FAILURE_SOURCES,
)
from tests.native.runtime_support import MEMORY_SANITIZERS

CONTROL_FLOW_SOURCE = """
def choose(flag: bool, left: int, right: int) -> int:
    selected = left if flag else right
    return selected + 1


def main() -> int:
    value = 0
    while value < 4:
        value = value + 1
    return choose(value == 4, value, 0)
"""
EXPECTED_LLVM = Path(__file__).with_name("control_flow.ll")
SETTINGS_SOURCE = Path(__file__).with_name("settings_source.py")

OBJECT_SOURCE = """
class Marker:
    pass


class Point:
    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y

    def total(self) -> int:
        return self.x + self.y


def move(point: Point, amount: int) -> int:
    point.x = point.x + amount
    return point.total()


def main() -> int:
    count = 0
    while count < 10000:
        Marker()
        count = count + 1
    point = Point(2, 3)
    return move(point, 4)
"""

INHERITANCE_SOURCE = """
class Animal:
    def __init__(self, value: int):
        self.value = value

    def sound(self) -> int:
        return self.value


class Cat(Animal):
    pass


class Dog(Animal):
    def __init__(self, value: int, bonus: int):
        super().__init__(value)
        self.bonus = bonus

    def sound(self) -> int:
        return self.value + self.bonus

    def reward(self) -> int:
        return self.bonus

    def parent_sound(self) -> int:
        return super().sound()


class Puppy(Dog):
    def reward(self) -> int:
        return self.bonus + 1


def speak(animal: Animal) -> int:
    return animal.sound()


def reward(dog: Dog) -> int:
    return dog.reward()


def main() -> int:
    dog = Dog(3, 4)
    cat = Cat(6)
    puppy = Puppy(2, 5)
    return speak(dog) + speak(cat) + reward(puppy) + dog.parent_sound()
"""

COLLECTION_SOURCE = """
def main() -> int:
    values = [1, 2]
    total = 0
    for value in values:
        total = total + value
        if value == 2:
            values.append(3)
    pairs = [(1, 2), (3, 4)]
    for left, right in pairs:
        total = total + left + right
    for index in range(3, -1, -1):
        total = total + index
    return total + values[-1] + len(values)
"""

STRING_SOURCE = """
def build(prefix: str, index: int) -> str:
    return f"{prefix}-{index}" + " ✓"


def main() -> int:
    value = build("row", 42)
    if value != "row-42 ✓":
        return 1
    if not value:
        return 2
    if str(True) != "True":
        return 4
    utf8 = "café 😀 \\x00" + "finished"
    if utf8 != "café 😀 \\x00finished":
        return 8
    if str(-7) == "-7":
        return 17
    return 3
"""

INTEGER_SEMANTICS_SOURCE = """
def main() -> int:
    if -7 // 3 != -3:
        return 1
    if -7 % 3 != 2:
        return 2
    if 7 // -3 != -3:
        return 3
    if 7 % -3 != -2:
        return 4
    if -7 // -3 != 2:
        return 5
    if -7 % -3 != -1:
        return 6
    if 7 // 3 != 2:
        return 7
    if 7 % 3 != 1:
        return 8
    return 29
"""

NATIVE_SOURCE = """
from pyjs.native import Document, attr, div, span


def main() -> str:
    document = Document()
    children = [span(document, "<one>"), span(document, "two & three")]
    root = div(document, attr("data-name", 'demo & "test"'), *children)
    return document.render(root)
"""


def test_llvm_transpiler_matches_complete_control_flow_golden():
    expected = EXPECTED_LLVM.read_text()
    if sys.platform == "win32":
        expected = expected.replace("declare ptr @signal(i32, ptr)\n", "")
        expected = expected.replace(
            "  %sigpipe.previous = call ptr @signal(i32 13, ptr inttoptr (i64 1 to ptr))\n", "",
        )
    assert transpile_llvm(CONTROL_FLOW_SOURCE) == expected


def test_llvm_transpiler_compiles_and_executes_control_flow(tmp_path):
    executable = LLVM().compile(
        transpile_llvm(CONTROL_FLOW_SOURCE),
        tmp_path,
        name="control_flow",
    )

    result = subprocess.run([executable], check=False)

    assert result.returncode == 5


def test_llvm_transpiler_compiles_and_executes_integer_abs(tmp_path):
    executable = LLVM().compile(
        transpile_llvm("def main() -> int:\n    return abs(-41) + abs(True)\n"),
        tmp_path,
        name="integer-abs",
    )

    result = subprocess.run([executable], check=False)

    assert result.returncode == 42


def test_llvm_emits_reached_imported_application_definitions(tmp_path):
    generated = transpile_llvm(
        """
        from tests.native.imported_program import Counter as ImportedCounter
        from tests.native.imported_program import calculate as imported_calculate
        from tests.native.imported_program import main as imported_main

        class Counter:
            def __init__(self, value: int):
                self.value = value

            def increment(self) -> int:
                return self.value + 2

        def calculate(value: int) -> int:
            return Counter(value).increment()

        def main() -> int:
            imported = ImportedCounter(10)
            return (
                calculate(10)
                + imported_calculate(10)
                + imported_main(10)
                + imported.increment()
            )
        """
    )

    assert "%class.Counter = type {" in generated
    assert "%class.tests.native.imported_program.Counter = type {" in generated
    assert "define i64 @fn.calculate" in generated
    assert "define i64 @fn.tests.native.imported_program.calculate" in generated
    assert "define i64 @fn.tests.native.imported_program.main" in generated

    executable = LLVM().compile(generated, tmp_path, name="imported-program")
    result = subprocess.run([executable], check=False)

    assert result.returncode == 48


def test_llvm_emits_cross_module_inheritance_and_virtual_calls(tmp_path):
    generated = transpile_llvm(
        """
        from tests.native.imported_program import Counter

        class ExtendedCounter(Counter):
            def increment(self) -> int:
                return self.value + 3

        def invoke(counter: Counter) -> int:
            return counter.increment()

        def main() -> int:
            return invoke(Counter(10)) + invoke(ExtendedCounter(10))
        """
    )

    assert "%vtable.type.tests.native.imported_program.Counter" in generated
    assert "@vtable.tests.native.imported_program.Counter" in generated
    assert "@fn.tests.native.imported_program.Counter.increment" in generated

    executable = LLVM().compile(generated, tmp_path, name="imported-inheritance")
    result = subprocess.run([executable], check=False)

    assert result.returncode == 24


def test_llvm_comparison_resolves_imports_from_caller_source_roots():
    comparison = LLVM().assert_matches_python(
        """
        from tests.native.imported_program import calculate

        def main() -> int:
            return calculate(10)
        """
    )

    assert comparison.native.returncode == 11


def test_llvm_uses_shared_numeric_formats_at_storage_boundaries(tmp_path):
    generated = transpile_llvm(
        """
        from pyjs import float32, float64, int8, int16, int32, int64
        from pyjs import uint8, uint16, uint32

        class Reading:
            signed: int16
            unsigned: uint16

            def __init__(self, signed: int16, unsigned: uint16) -> None:
                self.signed = signed
                self.unsigned = unsigned

        def signed(value: int8) -> int32:
            return int32(value)

        def unsigned(value: uint8) -> uint32:
            return uint32(value)

        def half(value: float32) -> float64:
            return float64(value / float32(2.0))

        def wide(value: int64) -> int64:
            return value + 1

        def narrow(value: int64) -> int64:
            return value - 1

        def identity(value: int64) -> int64:
            return value

        def wrap(value: int8) -> int8:
            return (value + 30) * 3

        def main() -> int:
            reading = Reading(-2, -1)
            if signed(-1) != -1:
                return 1
            if unsigned(-1) != 255:
                return 2
            if reading.signed != -2:
                return 3
            if reading.unsigned != 65535:
                return 4
            if half(float32(5.0)) != 2.5:
                return 5
            if wide(9007199254740992) != 9007199254740993:
                return 6
            if wide(9223372036854775807) >= 0:
                return 7
            if narrow(wide(9223372036854775807)) != 9223372036854775807:
                return 8
            if identity(-9223372036854775808) >= 0:
                return 9
            if wrap(100) != -122:
                return 10
            if int8(130.9) != -126:
                return 11
            return 37
        """
    )

    assert "%class.Reading = type { i16, i16 }" in generated
    assert "define i32 @fn.signed(ptr %arg.__arena, ptr %arg.__exception, i8 %arg.value)" in generated
    assert "define i32 @fn.unsigned(ptr %arg.__arena, ptr %arg.__exception, i8 %arg.value)" in generated
    assert "define double @fn.half(ptr %arg.__arena, ptr %arg.__exception, float %arg.value)" in generated
    assert "define i64 @fn.wide(ptr %arg.__arena, ptr %arg.__exception, i64 %arg.value)" in generated
    assert "sext i8" in generated
    assert "zext i8" in generated
    assert "fpext float" in generated

    executable = LLVM().compile(generated, tmp_path, name="numeric-formats")
    result = subprocess.run([executable], check=False)

    assert result.returncode == 37


def test_llvm_float_storage_keeps_python_zero_division_failure(tmp_path):
    generated = transpile_llvm(
        """
        from pyjs import float32

        def divide(left: float32, right: float32) -> float32:
            return left / right

        def main() -> int:
            divide(1.0, 0.0)
            return 0
        """
    )
    executable = LLVM().compile(generated, tmp_path, name="float-division")

    result = subprocess.run([executable], check=False)

    assert result.returncode != 0


def test_llvm_transpiler_compiles_objects_in_a_request_arena(tmp_path):
    generated = transpile_llvm(OBJECT_SOURCE)

    assert "%class.Point = type { i64, i64 }" in generated
    assert "define ptr @pyjs.arena.try.alloc(" in generated
    assert "call ptr @pyjs.arena.try.alloc" in generated
    assert "call void @pyjs.arena.destroy" in generated

    executable = LLVM().compile(generated, tmp_path, name="objects")
    result = subprocess.run([executable], check=False)

    assert result.returncode == 9


def test_llvm_transpiler_compiles_inheritance_and_virtual_dispatch(tmp_path):
    generated = transpile_llvm(INHERITANCE_SOURCE)

    assert "%class.Animal = type { ptr, i64 }" in generated
    assert "%class.Cat = type { ptr, i64 }" in generated
    assert "%class.Dog = type { ptr, i64, i64 }" in generated
    assert "%class.Puppy = type { ptr, i64, i64 }" in generated
    assert "@vtable.Cat" in generated
    assert "@vtable.Dog" in generated
    # The subtype-only reward method has a null slot on the base class.
    assert (
        "@vtable.Animal = private constant %vtable.type.Animal "
        "{ ptr null, ptr null, ptr @fn.Animal.sound, i64 16 }" in generated
    )
    assert "getelementptr %vtable.type.Animal" in generated

    executable = LLVM().compile(generated, tmp_path, name="inheritance")
    result = subprocess.run([executable], check=False)

    assert result.returncode == 22


def test_llvm_transpiler_compiles_collections_and_live_iteration(tmp_path):
    generated = transpile_llvm(COLLECTION_SOURCE)

    assert "%pyjs.list = type { i64, i64, ptr, ptr, ptr, i64 }" in generated
    assert "call ptr @pyjs.list.append.slot" in generated
    assert "%pyjs.tuple.i64.i64 = type { i64, i64 }" in generated
    assert "%pyjs.range.iterator = type { i64, i64, i64 }" in generated

    executable = LLVM().compile(generated, tmp_path, name="collections")
    result = subprocess.run([executable], check=False)

    assert result.returncode == 28


@pytest.mark.parametrize(
    "contract",
    BACKEND_CONTRACTS.values(),
    ids=BACKEND_CONTRACTS,
)
def test_llvm_runs_shared_numeric_contracts(tmp_path, contract):
    generated = transpile_llvm(contract.source)
    executable = LLVM().compile(generated, tmp_path, name="numeric-contract")

    result = subprocess.run([executable], check=False)

    assert result.returncode == 0, contract.failure(result.returncode)


@pytest.mark.parametrize(
    "source",
    PORTABLE_FAILURE_SOURCES.values(),
    ids=PORTABLE_FAILURE_SOURCES,
)
def test_llvm_rejects_shared_portable_numeric_failures(tmp_path, source):
    executable = LLVM().compile(
        transpile_llvm(source),
        tmp_path,
        name="portable-failure",
    )

    result = subprocess.run(executable, check=False)

    assert result.returncode != 0


def test_llvm_transpiler_compiles_utf8_strings_and_formatting(tmp_path):
    generated = transpile_llvm(STRING_SOURCE)

    assert "%pyjs.string = type { i64, ptr }" in generated
    assert "\\E2\\9C\\93" in generated
    assert "call ptr @pyjs.string.concat" in generated
    assert "call ptr @pyjs.string.from.i64" in generated
    assert "call i1 @pyjs.string.equal" in generated

    executable = LLVM().compile(generated, tmp_path, name="strings")
    result = subprocess.run([executable], check=False)

    assert result.returncode == 17


def test_llvm_transpiler_preserves_python_signed_divmod(tmp_path):
    generated = transpile_llvm(INTEGER_SEMANTICS_SOURCE)

    assert "call { i64, i64 } @pyjs.int.divmod" in generated

    executable = LLVM().compile(generated, tmp_path, name="integer-semantics")
    result = subprocess.run(executable, check=False)

    assert result.returncode == 29


@pytest.mark.parametrize(
    "source",
    [
        """
        def main() -> int:
            values = [1]
            return values[-2]
        """,
        """
        def main() -> int:
            total = 0
            for value in range(0, 3, 0):
                total = total + value
            return total
        """,
        """
        def main() -> int:
            return 1 // 0
        """,
    ],
)
def test_llvm_transpiler_traps_invalid_runtime_operations(tmp_path, source):
    executable = LLVM().compile(
        transpile_llvm(source),
        tmp_path,
        name="invalid-operation",
    )

    result = subprocess.run(executable, check=False)

    assert result.returncode != 0


def test_llvm_transpiler_renders_native_dom_and_starred_calls(tmp_path):
    generated = transpile_llvm(NATIVE_SOURCE)

    assert "define ptr @pyjs.native.document.new(ptr %arg.arena)" in generated
    assert "call ptr @pyjs.native.argument.new" in generated
    assert "call i1 @pyjs.native.arguments.extend.elements" in generated
    assert "call ptr @pyjs.native.element.new" in generated
    assert "call ptr @pyjs.native.document.render" in generated
    assert "%pyjs.native.element = type { ptr, ptr, i8, ptr }" in generated
    assert "call void @pyjs.native.element.write" in generated
    assert "call ptr @pyjs.string.concat(ptr %" not in generated
    assert "call i32 @pyjs.write.all" in generated

    executable = LLVM().compile(generated, tmp_path, name="native")
    result = subprocess.run(executable, check=True, capture_output=True, text=True)

    assert result.stdout == (
        '<div data-name="demo &amp; &quot;test&quot;">'
        "<span>&lt;one&gt;</span><span>two &amp; three</span></div>"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="pass_fds is a POSIX subprocess contract; Windows shares CRT descriptors in loaded libraries")
def test_llvm_native_dom_writes_to_an_inherited_descriptor(tmp_path):
    reader, writer = os.pipe()
    try:
        execution = LLVM().run_source(
            f"""
            from pyjs.native import Document, div

            def main() -> int:
                document = Document()
                return document.write(
                    div(document, "descriptor output"),
                    {writer},
                )
            """,
            directory=tmp_path,
            pass_fds=(writer,),
        )
    finally:
        os.close(writer)
    try:
        output = os.read(reader, 4096)
    finally:
        os.close(reader)

    assert execution.returncode == 0
    assert output == b"<div>descriptor output</div>"


def test_llvm_native_dom_matches_void_element_serialization(tmp_path):
    comparison = LLVM().assert_matches_python(
        """
        from pyjs.native import Document, attr, div, tag

        def main() -> str:
            document = Document()
            return document.render(
                div(
                    document,
                    tag(document, "input", attr("name", "query")),
                    tag(document, "br", "explicit child"),
                )
            )
        """,
        directory=tmp_path,
    )

    assert comparison.native.stdout == (
        '<div><input name="query"/><br>explicit child</br></div>'
    )


@pytest.mark.parametrize("optimize", [0, 2])
def test_native_document_composes_with_gc_and_preserves_arena_text(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import Document, attr, div, gc_collect, gc_set_threshold

        def document() -> Document:
            return Document()

        def main() -> str:
            gc_set_threshold(1, byte_limit=128)
            local = Document()
            escaped = document()
            roots = [div(local, attr("data-label", "v" + str(index)), "text" + str(index)) for index in range(3)]
            gc_collect()
            nested = div(escaped, *roots)
            gc_collect()
            output = escaped.render(nested)
            try:
                local.write(roots[0], 4294967296)
            except OverflowError:
                gc_collect()
            else:
                assert False
            assert local.write(roots[0], -1) == 9
            assert escaped.render(nested) == output
            return output
    ''', optimize=optimize, sanitizers=MEMORY_SANITIZERS)
    assert not result.native.stderr


def test_llvm_native_dom_keeps_only_the_last_duplicate_attribute(tmp_path):
    comparison = LLVM().assert_matches_python(
        """
        from pyjs.native import Document, attr, div

        def main() -> str:
            document = Document()
            return document.render(
                div(
                    document,
                    attr("data-value", "first"),
                    "content",
                    attr("data-value", "last"),
                )
            )
        """,
        directory=tmp_path,
    )

    assert comparison.native.stdout == '<div data-value="last">content</div>'


def test_llvm_renders_the_public_web_dom_surface(tmp_path):
    comparison = LLVM().assert_matches_python(
        """
        from pyjs.web.domx import div, input, span, svg_tag, tag, tw
        from pyjs.web.ssr import render_document

        def main() -> str:
            children = [span("<one>"), span("two & three")]
            return render_document(
                div(
                    tw("box rounded"),
                    {"data-name": 'demo & "test"'},
                    *children,
                    input({"name": "query"}),
                    tag("br", "explicit child"),
                    svg_tag(
                        "svg",
                        svg_tag("path", {"d": "M0 0"}),
                    ),
                )
            )
        """,
        directory=tmp_path,
    )

    assert comparison.native.stdout == (
        "<!doctype html>\n"
        '<div class="box rounded" data-name="demo &amp; &quot;test&quot;">'
        "<span>&lt;one&gt;</span><span>two &amp; three</span>"
        '<input name="query"/><br>explicit child</br>'
        '<svg><path d="M0 0"></path></svg></div>'
    )


def test_llvm_public_web_dom_keeps_only_the_last_duplicate_attribute(tmp_path):
    comparison = LLVM().assert_matches_python(
        """
        from pyjs.web.domx import div
        from pyjs.web.ssr import render_html

        def main() -> str:
            return render_html(
                div(
                    {"data-value": "first"},
                    "content",
                    {"data-value": "last"},
                )
            )
        """,
        directory=tmp_path,
    )

    assert comparison.native.stdout == '<div data-value="last">content</div>'


def test_llvm_duplicate_attributes_keep_their_first_insertion_position(tmp_path):
    comparison = LLVM().assert_matches_python(
        """
        from pyjs.web.domx import div
        from pyjs.web.ssr import render_html

        def main() -> str:
            return render_html(
                div(
                    {"data-first": "old"},
                    {"data-middle": "kept"},
                    {"data-first": "new"},
                )
            )
        """,
        directory=tmp_path,
    )

    assert comparison.native.stdout == ('<div data-first="new" data-middle="kept"></div>')


def test_llvm_constructs_public_custom_elements_with_hydration_ids(tmp_path):
    counter = CustomElement.CUSTOM_ELEMENT_COUNTER
    CustomElement.CUSTOM_ELEMENT_COUNTER = 0
    try:
        comparison = LLVM().assert_matches_python(
            """
        from pyjs.web.domx import CustomElement, div, tag, tw
        from pyjs.web.ssr import render_html

        class Greeting(CustomElement):
            def __init__(self, name: str):
                super().__init__()
                tag(self, tw("greeting"), div(name))

        def main() -> str:
            return render_html(div(Greeting("Ada"), Greeting("Grace")))
            """,
            directory=tmp_path,
        )
    finally:
        CustomElement.CUSTOM_ELEMENT_COUNTER = counter

    assert comparison.native.stdout == (
        '<div><pyjs-greeting data-self-id="ce1" class="greeting">'
        "<div>Ada</div></pyjs-greeting>"
        '<pyjs-greeting data-self-id="ce2" class="greeting">'
        "<div>Grace</div></pyjs-greeting></div>"
    )


def test_llvm_transpiler_matches_representative_pyjs_ssr(
    tmp_path,
    settings_html,
):
    source = SETTINGS_SOURCE.read_text(encoding="utf-8")
    comparison = LLVM().assert_matches_python(
        source,
        filename=str(SETTINGS_SOURCE),
        module_name="native_settings_llvm",
        directory=tmp_path,
    )

    assert comparison.native.stdout == settings_html


def test_llvm_compiles_typed_dictionaries_with_python_semantics():
    comparison = LLVM().assert_matches_python(
        """
        def main() -> int:
            values: dict[str, int] = {"one": 1, "two": 2}
            values["three"] = 3
            values["four"] = 4
            values["five"] = 5
            values["one"] = 5
            result = values["one"] + values.get("missing", 4)
            for key in values:
                if key == "two":
                    result += values[key]
            if "three" in values:
                result += 1
            return result + len(values)
        """
    )

    assert comparison.native.returncode == 17


@pytest.mark.parametrize(
    ("annotation", "literal", "lookup", "expected"),
    [
        ("int", "{10: 2, 20: 3}", "20", 5),
        ("bool", "{False: 4, True: 5}", "True", 7),
    ],
)
def test_llvm_dictionary_scalar_key_representations(
    annotation,
    literal,
    lookup,
    expected,
):
    comparison = LLVM().assert_matches_python(
        f"""
        def main() -> int:
            values: dict[{annotation}, int] = {literal}
            return values[{lookup}] + len(values)
        """
    )

    assert comparison.native.returncode == expected


def test_llvm_compiles_typed_sets_with_python_semantics():
    comparison = LLVM().assert_matches_python(
        """
        def main() -> int:
            values: set[str] = {"one", "two", "three", "four"}
            values.add("five")
            values.add("two")
            result = 0
            for value in values:
                if value == "three":
                    result += 5
            if "five" in values:
                result += 4
            return result + len(values)
        """
    )

    assert comparison.native.returncode == 14


def test_llvm_rejects_an_incompatible_virtual_override():
    with pytest.raises(LLVMUnsupported, match="must preserve the base"):
        transpile_llvm(
            """
class Base:
    def choose(self, value: int) -> int:
        return 1


class Child(Base):
    def choose(self, value: bool) -> int:
        return 2 if value else 3


def call(value: Base) -> int:
    return value.choose(256)


def main() -> int:
    return call(Child())
"""
        )


def test_llvm_ranges_stop_when_fixed_width_advancement_overflows(tmp_path):
    generated = transpile_llvm(
        """
def main() -> int:
    count = 0
    for value in range(9223372036854775806, 9223372036854775807, 2):
        count = count + 1
    lowest = -9223372036854775807 - 1
    for value in range(lowest + 1, lowest, -2):
        count = count + 1
    return count
"""
    )
    executable = LLVM().compile(generated, tmp_path, name="range-overflow")

    result = subprocess.run(executable, check=False, timeout=5)

    assert result.returncode == 2


def test_llvm_binds_defaults_keywords_and_static_methods():
    comparison = LLVM().assert_matches_python(
        """
        class Point:
            def __init__(self, x: int, y: int = 4, *, offset: int = 1):
                self.x = x + offset
                self.y = y

            def total(self, extra: int = 2, *, scale: int = 1) -> int:
                return (self.x + self.y + extra) * scale

            @staticmethod
            def add(left: int, right: int = 3, *, scale: int = 2) -> int:
                return (left + right) * scale

        def main() -> int:
            point = Point(2, offset=3)
            return Point.add(scale=3, left=2) + point.total(scale=2)
        """
    )

    assert comparison.native.returncode == 37


def test_llvm_rejects_inherited_class_methods_explicitly():
    with pytest.raises(
        LLVMUnsupported,
        match="class methods require dynamic class identity",
    ):
        transpile_llvm(
            """
class Example:
    @classmethod
    def value(cls) -> int:
        return 1


class Child(Example):
    pass


def main() -> int:
    return Child.value()
"""
        )


def test_llvm_emits_string_constants_used_only_as_defaults():
    comparison = LLVM().assert_matches_python(
        """
        def size(value: str = "default") -> int:
            return len(value)

        def main() -> int:
            return size()
        """
    )

    assert comparison.native.returncode == 7


def test_llvm_rejects_effectful_mutable_default_initializers():
    with pytest.raises(LLVMUnsupported, match="must contain only literal values"):
        transpile_llvm(
            """
            def calculate() -> int:
                return 1

            def append(values: list[int] = [calculate()]) -> int:
                values.append(1)
                return len(values)

            def main() -> int:
                return append()
            """
        )


def test_llvm_collects_managed_objects_and_traces_cycles():
    comparison = LLVM().assert_matches_python(
        """
        from pyjs.native import gc_collect, gc_count, gc_pin, gc_unpin

        class Child:
            def __init__(self, value: int):
                self.value = value

        class Parent:
            def __init__(self, child: Child):
                self.child = child

        class Cycle:
            def __init__(self, value: int):
                self.value = value
                self.other = self

        def main() -> int:
            parent = Parent(Child(7))
            cycle = Cycle(5)
            gc_pin(parent)
            gc_pin(parent)
            gc_pin(cycle)
            gc_collect()
            result = parent.child.value + cycle.other.value + gc_count()
            gc_unpin(parent)
            gc_unpin(cycle)
            gc_collect()
            return result + gc_count()
        """
    )

    assert comparison.native.returncode == 14


def test_llvm_gc_roots_live_locals_before_they_are_pinned():
    comparison = LLVM().assert_matches_python(
        """
        from pyjs.native import gc_collect, gc_count, gc_pin, gc_unpin

        class Box:
            def __init__(self, value: int):
                self.value = value

        def main() -> int:
            value = Box(7)
            gc_collect()
            gc_pin(value)
            gc_collect()
            result = value.value + gc_count()
            gc_unpin(value)
            return result
        """
    )

    assert comparison.native.returncode == 8


def test_llvm_gc_roots_managed_values_returned_by_factories():
    comparison = LLVM().assert_matches_python(
        """
        from pyjs.native import gc_collect, gc_count, gc_pin, gc_unpin

        class Box:
            def __init__(self, value: int):
                self.value = value

        def make_box(value: int) -> Box:
            return Box(value)

        def main() -> int:
            value = make_box(7)
            gc_collect()
            gc_pin(value)
            result = value.value + gc_count()
            gc_unpin(value)
            return result
        """
    )

    assert comparison.native.returncode == 8


def test_llvm_gc_owns_mutable_container_storage_and_contained_objects():
    comparison = LLVM().assert_matches_python(
        """
        from pyjs.native import gc_collect, gc_count, gc_pin, gc_unpin

        class Box:
            def __init__(self, value: int):
                self.value = value

        def main() -> int:
            values = [Box(2)]
            mapping = {1: Box(3)}
            seen = {1, 2}
            gc_pin(values)
            gc_pin(mapping)
            gc_pin(seen)
            values.append(Box(5))
            mapping[2] = Box(7)
            seen.add(3)
            gc_collect()
            result = (
                values[0].value
                + values[1].value
                + mapping[1].value
                + mapping[2].value
                + len(seen)
                + gc_count()
            )
            gc_unpin(values)
            gc_unpin(mapping)
            gc_unpin(seen)
            return result
        """
    )

    assert comparison.native.returncode == 23


def test_llvm_gc_owns_escaping_tuples_and_their_objects():
    comparison = LLVM().assert_matches_python(
        """
        from pyjs.native import gc_collect, gc_pin, gc_unpin

        class Box:
            def __init__(self, value: int):
                self.value = value

        def main() -> int:
            pair = (Box(4), Box(5))
            gc_pin(pair)
            gc_collect()
            result = pair[0].value + pair[1].value
            gc_unpin(pair)
            return result
        """
    )

    assert comparison.native.returncode == 9


def test_llvm_gc_owns_dynamic_strings_in_objects_and_containers():
    comparison = LLVM().assert_matches_python(
        """
        from pyjs.native import gc_collect, gc_count, gc_pin, gc_unpin

        class Label:
            def __init__(self, value: str):
                self.value = value

        def main() -> int:
            value = "item-" + str(7)
            label = Label(value)
            values = [value]
            mapping = {value: label}
            gc_pin(value)
            gc_pin(label)
            gc_pin(values)
            gc_pin(mapping)
            gc_collect()
            result = (
                len(value)
                + len(label.value)
                + len(values[0])
                + len(mapping[value].value)
                + gc_count()
            )
            gc_unpin(value)
            gc_unpin(label)
            gc_unpin(values)
            gc_unpin(mapping)
            return result
        """
    )

    assert comparison.native.returncode == 28


def test_llvm_gc_collects_automatically_only_at_safe_points():
    comparison = LLVM().assert_matches_python(
        """
        from pyjs.native import (
            gc_disable,
            gc_enable,
            gc_is_enabled,
            gc_set_threshold,
        )

        class Child:
            def __init__(self, value: int):
                self.value = value

        class Parent:
            def __init__(self, child: Child):
                self.child = child

        def main() -> int:
            gc_set_threshold(1)
            parent = Parent(Child(7))
            other = Child(5)
            gc_disable()
            disabled = gc_is_enabled()
            ignored = Child(3)
            gc_enable()
            return (
                parent.child.value
                + other.value
                + ignored.value
                + int(disabled)
                + int(gc_is_enabled())
            )
        """
    )

    assert comparison.native.returncode == 16


def test_llvm_gc_roots_partial_call_arguments_across_nested_collection():
    comparison = LLVM().assert_matches_python(
        """
        from pyjs.native import gc_collect, gc_pin, gc_unpin

        class Box:
            def __init__(self, value: int):
                self.value = value

        def collect_and_return() -> int:
            gc_collect()
            return 2

        def consume(value: Box, extra: int) -> int:
            gc_pin(value)
            result = value.value + extra
            gc_unpin(value)
            return result

        def main() -> int:
            return consume(Box(7), collect_and_return())
        """
    )

    assert comparison.native.returncode == 9


def test_llvm_gc_marks_deep_graphs_without_native_recursion():
    comparison = LLVM().assert_matches_python(
        """
        from pyjs.native import gc_collect, gc_pin, gc_unpin

        class Link:
            def __init__(self, value: int):
                self.value = value
                self.previous = self

        def main() -> int:
            root = Link(0)
            for value in range(1, 1500):
                next_link = Link(value)
                next_link.previous = root
                root = next_link
            gc_pin(root)
            gc_collect()
            result = root.value % 256
            gc_unpin(root)
            return result
        """
    )

    assert comparison.matches
    assert comparison.native.returncode == 1499 % 256


def test_llvm_library_owns_a_persistent_managed_heap(tmp_path):
    comparison = LLVM().assert_library_matches_python(
        """
        from pyjs.native import gc_collect, gc_count, gc_pin, gc_unpin

        class Box:
            def __init__(self, value: int):
                self.value = value

        def main() -> str:
            value = Box(7)
            gc_pin(value)
            gc_collect()
            result = f"{value.value}:{gc_count()}"
            gc_unpin(value)
            gc_collect()
            return result
        """,
        directory=tmp_path,
    )

    assert comparison.native == "7:1"
    assert comparison.library.managed
    comparison.library.close()
    with pytest.raises(RuntimeError, match="library is closed"):
        comparison.library.render()
