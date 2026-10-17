"""Optional native values across storage, control flow and ownership boundaries."""

import textwrap

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError
from tests.backend_semantics import (
    OPTIONAL_BRANCH_CONTRACT,
    OPTIONAL_INTEGER_CONTRACT,
    OPTIONAL_OBJECT_CONTRACT,
    OPTIONAL_STRING_CONTRACT,
)


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_dependency_preparation_ignores_class_receivers(optimize):
    LLVM().assert_matches_python('''
        class Helpers:
            @staticmethod
            def __eq__(left: int, right: int) -> bool:
                return left == right

            @staticmethod
            def size(values: list[int]) -> int:
                return len(values)

        def main() -> int:
            assert Helpers.__eq__(3, 3)
            assert Helpers.size([1, 2]) == 2
            return 0
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_optional_string_contract(optimize):
    LLVM().assert_matches_python(OPTIONAL_STRING_CONTRACT.source, optimize=optimize,
                                 sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_optional_branch_contract(optimize):
    LLVM().assert_matches_python(OPTIONAL_BRANCH_CONTRACT.source, optimize=optimize,
                                 sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_optional_integer_contract(optimize):
    result = LLVM().assert_matches_python(OPTIONAL_INTEGER_CONTRACT.source, optimize=optimize,
                                          sanitizers=("address", "undefined"))
    assert result.native.returncode == 0, OPTIONAL_INTEGER_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_optional_object_contract(optimize):
    LLVM().assert_matches_python(OPTIONAL_OBJECT_CONTRACT.source, optimize=optimize,
                                 sanitizers=("address", "undefined"))


@pytest.mark.parametrize("body", [
    "pair = (None, 2)\nreturn pair[1]",
    "value: str | None = 'present'\nvalue, other = (None, 2)\nreturn other",
    "value: str | None = 'present'\nfor index in range(1):\n    value, other = (None, 2)\nreturn other",
])
def test_none_only_tuple_members_have_concrete_storage(body):
    source = "def main() -> int:\n" + textwrap.indent(body, "    ")
    LLVM().assert_matches_python(source)


@pytest.mark.parametrize("source", [
    "def consume(value: tuple[int, None]) -> int:\n    return value[0]\ndef main() -> int:\n    return consume((1, None))\n",
    "def produce() -> tuple[None, int]:\n    return (None, 2)\ndef main() -> int:\n    return produce()[1]\n",
])
def test_none_only_tuple_parameters_and_results(source):
    LLVM().assert_matches_python(source)


@pytest.mark.parametrize("annotation", ["tuple[None, int]", "list[tuple[None, int]]"])
def test_unused_none_only_tuple_parameter_has_a_concrete_abi(tmp_path, annotation):
    library = LLVM().compile_library(f'''\
            def render(value: {annotation}) -> str:
                return "unused"
        ''', tmp_path, entry_point="render")
    try:
        value = (None, 2) if annotation.startswith("tuple") else [(None, 2)]
        assert library.render(value) == "unused"
    finally:
        library.close()


@pytest.mark.parametrize("annotation", ["object", "object | None"])
def test_erased_range_isinstance_distinguishes_other_references(annotation):
    LLVM().assert_matches_python(f'''\
            class Box:
                pass
            def check(value: {annotation}) -> bool:
                return isinstance(value, range)
            def main() -> str:
                return str((check(Box()), check("text"), check(None), check(range(2))))
    ''')


@pytest.mark.parametrize("annotation", ["object", "object | None"])
def test_erased_application_isinstance_has_runtime_identity(annotation):
    result = LLVM().assert_matches_python(f'''
        class Box:
            pass
        def check(value: {annotation}) -> bool:
            return isinstance(value, Box)
        def main() -> str:
            return str((check(Box()), check("text"), check(None)))
    ''', sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("source", [
    '''
    def choose(v: int | None = None) -> int:
        return 3 if v is None else v + 1
    def selected(flag: bool) -> int | None:
        return 9 if flag else None
    def main() -> str:
        a: int | None = None
        b: int | None = 4
        c: str | None = str(9)
        result = str(a) + str(b) + str(a == b) + str(b == 4)
        result += str(bool(a)) + str(bool(b)) + str(c)
        result += str(choose()) + str(choose(8)) + str(selected(False)) + str(selected(True))
        return result
    ''',
    '''
    def main() -> str:
        values: list[int | None] = [1, None, 3]
        values.append(None)
        values[0] = None
        values[1] = 2
        values.insert(0, 4)
        result = ""
        for item in values:
            result += str(item) + ":"
        return result + str(values.count(None)) + str(None in values) + str(values == [4, None, 2, 3, None])
    ''',
    '''
    from pyjs.native import gc_collect, gc_set_threshold
    class Box:
        value: int | None
        text: str | None
        def __init__(self, value: int | None, text: str | None = None) -> None:
            self.value = value
            self.text = text
        def read(self, default: int | None = None) -> int | None:
            return self.value if self.value is not None else default
    def main() -> str:
        gc_set_threshold(1)
        box = Box(None, str(12))
        gc_collect()
        result = str(box.read(3)) + str(box.text)
        box.value = 8
        box.text = None
        gc_collect()
        return result + str(box.read()) + str(box.text)
    ''',
    '''
    import json
    def main() -> str:
        values: dict[str, list[int | None] | None] = {"a": [1, None], "b": None}
        return json.dumps(values, sort_keys=True) + json.dumps(values, indent=2)
    ''',
], ids=["scalars", "lists", "fields", "json"])
def test_optional_boundaries(source, optimize):
    LLVM().assert_matches_python(source, optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_library_optional_inputs(tmp_path, optimize):
    library = LLVM().compile_library('''
        import json
        class Record:
            number: int | None
            text: str | None
            def __init__(self, number: int | None, text: str | None) -> None:
                self.number = number
                self.text = text
        def render(flag: bool | None, number: int | None, floating: float | None,
                   text: str | None, values: list[int | None], record: Record) -> str:
            return (json.dumps(flag) + "|" + json.dumps(number) + "|" + json.dumps(floating)
                    + "|" + json.dumps(text) + "|" + json.dumps(values)
                    + "|" + json.dumps((record.number, record.text)))
    ''', tmp_path, entry_point="render", optimize=optimize)
    import json
    try:
        for values in [(None, None, None, None), (False, 0, -0.0, ""), (True, 42, 1.5, "é")]:
            flag, number, floating, text = values
            seq, record = [number, None, 8], {"number": number, "text": text}
            expected = "|".join(json.dumps(item) for item in (*values, seq, (number, text)))
            assert library.render(*values, seq, record) == expected
        with pytest.raises(TypeError, match="number"):
            library.render(None, "wrong", None, None, [], {"number": None, "text": None})
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_truth_narrowing_and_float_equality(optimize):
    LLVM().assert_matches_python('''
        def inspect(value: float | None) -> str:
            return str(bool(value)) + str(value is None) + str(value == 0.0)
        def main() -> str:
            result = inspect(None) + inspect(0.0) + inspect(float("nan"))
            a: int | None = 7
            b: int | None = None
            result += str(a or 8) + str(b or 8) + str(a and 9) + str(b and 9)
            if isinstance(a, int):
                result += str(a + 1)
            if not isinstance(b, int):
                result += "missing"
            text: str | None = ""
            result += str(bool(text))
            text = "found"
            if text is not None:
                result += text.upper()
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_virtual_calls_and_closure_roots(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def read(self, value: int | None) -> int | None:
                return value
        class Child(Base):
            def read(self, value: int | None) -> int | None:
                return None if value is None else value + 1
        def call(obj: Base, value: int | None) -> str:
            return str(obj.read(value))
        def capture(text: str | None) -> Callable[[], str | None]:
            return lambda: text
        def main() -> str:
            gc_set_threshold(1)
            callback = capture(str(12345))
            empty = capture(None)
            gc_collect()
            result = call(Child(), None) + call(Child(), 7)
            return result + str(callback()) + str(empty())
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_lookup_defaults_iterators_and_inferred_locals(optimize):
    LLVM().assert_matches_python('''
        import json
        def choose(flag: bool) -> int | None:
            value: int | None = None
            if flag:
                value = 4
            inferred = 9 if flag else None
            return value if flag else inferred
        def main() -> str:
            values: dict[str, int | None] = {"a": None, "b": 2}
            values["b"] = None
            values["c"] = 3
            result = str(values.get("a")) + str(values.get("missing"))
            result += str(values.setdefault("d", 4)) + str(values.setdefault("e", None))
            regular: dict[str, int] = {"x": 8}
            result += str(regular.get("x")) + str(regular.get("y"))
            stream = iter([1, 2])
            result += str(next(stream, None)) + str(next(stream, None)) + str(next(stream, None))
            result += str(choose(False)) + str(choose(True))
            return result + json.dumps(values)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_payloads_remain_rooted_during_later_arguments(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def text(value: int) -> str | None:
            return str(value) * 100
        def collect() -> int:
            gc_collect()
            return 1
        def take(value: str | None, ignored: int) -> str:
            return "missing" if value is None else value
        def main() -> str:
            gc_set_threshold(1)
            result = take(text(123), collect())
            for index in range(30):
                item = text(index)
                gc_collect()
                result += take(item, collect())
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_mixed_numeric_equality_keeps_integer_precision(optimize):
    LLVM().assert_matches_python('''
        def same(left: int | None, right: float | None) -> bool:
            return left == right
        def main() -> str:
            result = ""
            integers: list[int | None] = [None, 0, 1, 9007199254740993, -9223372036854775808, 9223372036854775807]
            floats: list[float | None] = [None, -0.0, 1.0, 1.5, 9007199254740992.0, -9223372036854775808.0, 9223372036854775808.0, float("nan"), float("inf")]
            for left in integers:
                for right in floats:
                    result += str(same(left, right))
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_presence_is_not_payload_truth(optimize):
    LLVM().assert_matches_python('''
        def inspect(value: bool | None) -> str:
            result = str(value is True) + str(value is False) + str(value is None)
            if value:
                result += "truthy"
            if value is None:
                result += str(value)
            return result
        def main() -> str:
            return inspect(None) + inspect(False) + inspect(True)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_portable_optional_values_and_host_inputs(tmp_path, optimize):
    import json

    from pyjs import float32, int8

    source = '''
        from pyjs import int8, float32
        import json
        def render(number: int8 | None, floating: float32 | None,
                   values: list[int8 | None]) -> str:
            return json.dumps((number, floating, values))
        def main() -> str:
            values: list[int8 | None] = [int8(128), None, int8(-129)]
            return render(int8(255), float32(1.1), values)
    '''
    LLVM().assert_matches_python(source, optimize=optimize, sanitizers=("address", "undefined"))
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        assert library.render(255, 1.1, [128, None, -129]) == json.dumps((int8(255), float32(1.1), [int8(128), None, int8(-129)]))
        assert library.render(None, None, [None]) == "[null, null, [null]]"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_nullable_generators_variadics_and_tuple_storage(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        import json
        def stream() -> Iterator[str | None]:
            yield None
            yield str(123)
            gc_collect()
            yield ""
        def pack(*values: int | None) -> str:
            return json.dumps(values)
        def named(**values: int | None) -> str:
            return json.dumps(values)
        def numbers() -> Iterator[int | None]:
            yield None
            yield 0
            yield 7
        def fail() -> int | None:
            raise ValueError("failed")
        def main() -> str:
            gc_set_threshold(1)
            values: tuple[int | None, int | None] = (None, 2)
            varied: tuple[int | None, ...] = (None, 4, None)
            result = str(values == values) + pack(None, 1, None) + named(a=None, b=2)
            result += json.dumps(varied)
            for item in stream():
                gc_collect()
                result += str(item)
            for number in numbers():
                result += str(number)
            try:
                result += str(fail())
            except ValueError as error:
                result += str(error)
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("body", [
    'values: set[int | None] = {None, 1}\nreturn str((len(values), None in values, 1 in values))',
    'values: dict[int | None, str] = {None: "x", 1: "y"}\nreturn str(values)',
])
def test_optional_key_literals_preserve_none_and_present_values(body):
    source = "def main() -> str:\n" + "\n".join("    " + line for line in body.splitlines())
    LLVM().assert_matches_python(source)


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_custom_equality_does_not_silently_skip_callbacks(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        class Box:
            def __eq__(self, other: Box | None) -> bool:
                return True
        def compare(value: Box | None) -> bool:
            return value == None
        def main() -> str:
            return str(compare(Box())) + str(compare(None))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_optional_collection_views_require_matching_item_storage():
    with pytest.raises(LLVMUnsupported, match="collection views require matching concrete item storage.*at line"):
        transpile_llvm('''
            def accept(values: list[int | None]) -> str:
                return str(values[0])
            def main() -> str:
                values: list[int] = [1]
                return accept(values)
        ''')


@pytest.mark.parametrize("method,result,annotation", [("__bool__", "self.size != 0", "bool"),
                                                     ("__len__", "self.size", "int")])
def test_optional_user_truth_protocols(method, result, annotation):
    comparison = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect
        class Box:
            def __init__(self, size: int):
                self.size = size
            def {method}(self) -> {annotation}:
                gc_collect()
                return {result}
        def inspect(value: Box | None) -> str:
            return str(bool(value))
        def main() -> str:
            return inspect(None) + inspect(Box(0)) + inspect(Box(1))
    ''', sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


STALE_FIELD = '''
    class Box:
        text: str | None
        number: int | None
        def __init__(self, text: str | None) -> None:
            self.text = text
            self.number = 3
        def clear(self) -> None:
            self.text = None
            self.number = None
    def render(text: str | None) -> str:
        box = Box(text)
        alias = box
        if box.text is not None:
            alias.clear()
            return box.text.upper()
        return "missing"
    def main() -> str:
        result = ""
        try:
            result += render("value")
        except Exception:
            result += "safe"
        box = Box(None)
        if box.number is not None:
            box.clear()
            try:
                result += str(box.number + 1)
            except TypeError:
                result += "safe"
        return result
'''


@pytest.mark.parametrize("optimize", [0, 2])
def test_stale_optional_field_narrowing_is_checked(tmp_path, optimize):
    LLVM().assert_matches_python(STALE_FIELD, optimize=optimize, sanitizers=("address", "undefined"))
    library = LLVM().compile_library(STALE_FIELD, tmp_path, entry_point="render", optimize=optimize)
    try:
        assert library.render(None) == "missing"
        with pytest.raises(LLVMRuntimeError, match="optional field text changed after narrowing") as caught:
            library.render("value")
        load_line = textwrap.dedent(STALE_FIELD).splitlines().index("        return box.text.upper()") + 1
        assert f"line {load_line}, in render" in caught.value.native_traceback
        assert library.render(None) == "missing"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_absent_float_local_links_formatting_runtime(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            value: float | None = None
            return str(value) + f"{value}"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_nullable_writes_invalidate_all_guard_forms(optimize):
    LLVM().assert_matches_python('''
        def truth(value: int | None) -> str:
            if value:
                value = None
            else:
                return "absent"
            return str(value)
        def compound(value: str | None, enabled: bool) -> str:
            if value is not None and enabled:
                value = None
            else:
                return "absent"
            return str(value)
        def instance(value: int | None) -> str:
            if isinstance(value, int):
                value = None
            else:
                return "absent"
            return str(value)
        def unpack(value: int | None) -> int:
            if value is None:
                value = 1
            else:
                value, unused = 2, 3
            return value + 1
        def loop(value: int | None, count: int) -> str:
            value = 2
            result = ""
            while count > 0:
                result += str(value)
                value = None
                count -= 1
            return result + str(value)
        def main() -> str:
            return truth(1) + truth(None) + compound("a", True) + loop(None, 2) + instance(1) + instance(None) + str(unpack(None)) + str(unpack(5))
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_concrete_writes_preserve_narrowed_locals_and_fields(optimize):
    LLVM().assert_matches_python('''
        class Counter:
            count: int | None
            def __init__(self, count: int | None) -> None:
                self.count = count
            def read(self) -> int:
                if self.count is None:
                    return 0
                for i in range(3):
                    self.count += i
                return self.count + 1
        def calculate(value: int | None, doubled: bool) -> int:
            if value is None:
                value = 10
            if doubled:
                value *= 2
            else:
                value += 1
            if value > 5:
                value = 5
            for i in range(3):
                value += i
            while value > 3:
                value -= 1
            return value + 1
        def shadow(value: str | None, items: list[str]) -> str:
            if value is None:
                return "-"
            ignored = [value for value in items]
            return value.upper()
        def main() -> str:
            return str(calculate(None, False)) + str(calculate(1, True)) + str(Counter(4).read()) + str(Counter(None).read()) + shadow("old", ["new"])
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize(("kind", "initial", "read"), [
    ("str", '"old"', "value.upper()"),
    ("int", "3", "str(value + 1)"),
    ("float", "3.0", "str(value + 1.0)"),
])
@pytest.mark.parametrize("region", ["direct", "finally", "handler"])
def test_captured_optional_local_presence_is_checked(optimize, kind, initial, read, region):
    mutation = "if clear:\n    value = None\ngc_collect()\n"
    checked_read = 'try:\n    result = read()\nexcept Exception:\n    result = "safe"\n'
    if region == "finally":
        body = "try:\n" + textwrap.indent(mutation, "    ") + "finally:\n" + textwrap.indent(checked_read, "    ")
    elif region == "handler":
        body = ("try:\n" + textwrap.indent(mutation + 'raise ValueError("read")\n', "    ")
                + "except ValueError:\n" + textwrap.indent(checked_read, "    "))
    else:
        body = mutation + checked_read
    LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        def exercise(clear: bool) -> str:
            value: {kind} | None = {initial}
            result = ""
            if value is not None:
                read = lambda: {read}
{textwrap.indent(body, "                ")}
            return result
        def main() -> str:
            gc_set_threshold(1)
            return exercise(True) + exercise(False)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_captured_finally_failure_has_a_checked_traceback(tmp_path, optimize):
    source = '''
        def render(value: str | None) -> str:
            if value is None:
                return "missing"
            read = lambda: value.upper()
            try:
                value = None
            finally:
                result = read()
            return result
    '''
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    try:
        with pytest.raises(LLVMRuntimeError, match="TypeError: optional local value changed after narrowing") as caught:
            library.render("old")
        assert "lambda.0" in caught.value.native_traceback
        assert library.render(None) == "missing"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_portable_fields_and_fstrings(optimize):
    LLVM().assert_matches_python('''
        from pyjs import int8, float32
        class Box:
            number: int8 | None
            floating: float32 | None
            def __init__(self) -> None:
                self.number = int8(128)
                self.floating = float32(1.5)
        def main() -> str:
            box = Box()
            result = f"{box.number}:{box.floating}"
            box.number = None
            box.floating = None
            return result + f"{box.number}:{box.floating}"
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("annotation,value", [("float | None", "3"), ("int | None", "True"), ("float", "3")])
def test_numeric_annotations_do_not_implicitly_cast_values(annotation, value):
    with pytest.raises(LLVMUnsupported, match="explicit.*conversion"):
        transpile_llvm(f'''
            def render(value: {annotation}) -> str:
                return str(value)
            def main() -> str:
                return render({value})
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_runtime_type_checks_use_reached_vtables(optimize):
    LLVM().assert_matches_python('''
        class Base:
            def name(self) -> str:
                return "base"
        class Left(Base):
            def name(self) -> str:
                return "left"
        class Right(Base):
            def name(self) -> str:
                return "right"
        class Leaf(Left):
            def name(self) -> str:
                return "leaf"
        def inspect(value: Base | None) -> str:
            result = value.name() if value is not None else "missing"
            return result + str(isinstance(value, Left)) + str(isinstance(value, Base)) + str(isinstance(value, Right)) + str(isinstance(value, Leaf)) + str(isinstance(value, object))
        def main() -> str:
            return inspect(Base()) + inspect(Left()) + inspect(Right()) + inspect(Leaf()) + inspect(None)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


def test_optional_nonempty_format_specifiers_require_narrowing():
    with pytest.raises(LLVMUnsupported, match="optional formatting requires an empty specification"):
        transpile_llvm('''
            def render(value: float | None) -> str:
                return f"{value:.2f}"
            def main() -> str:
                return render(None)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_repr_uses_supported_representation_protocol(optimize):
    LLVM().assert_matches_python('''
        def render(value: float | None) -> str:
            return f"{value!r}"
        def main() -> str:
            return render(None) + "|" + render(1.25)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_indirect_optional_calls_and_mapping_defaults(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        import json
        def take(value: int | None) -> int | None:
            return None if value is None else value + 1
        def main() -> str:
            callback: Callable[[int | None], int | None] = take
            absent: int | None = None
            result = str(callback(1)) + str(callback(None)) + str(callback(absent))
            values: dict[str, int | None] = {"one": 1, "none": None}
            result += str(values.pop("absent", None)) + str(values.pop("one", None))
            result += str(values.pop("absent", 2)) + str(values.pop("none", 3))
            result += str(values.setdefault("new"))
            return result + json.dumps(values)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("annotation,values,expected", [
    ("list[int8] | None", [128, 255], "[-128, -1]"),
    ("tuple[int8, int8] | None", (128, 255), "[-128, -1]"),
    ("list[float32] | None", [1.1], "[1.100000023841858]"),
    ("list[list[int8]] | None", [[128, 255]], "[[-128, -1]]"),
])
def test_host_container_payload_normalization_keeps_canonical_stride(tmp_path, annotation, values, expected):
    library = LLVM().compile_library(f'''
        from pyjs import int8, float32
        import json
        def render(values: {annotation}) -> str:
            return json.dumps(values)
    ''', tmp_path, entry_point="render")
    try:
        assert library.render(values) == expected
        assert library.render(None) == "null"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_scalar_local_and_field_branch_merges(optimize):
    LLVM().assert_matches_python('''
        class Box:
            value: int | None
            def __init__(self, value: int | None) -> None:
                self.value = value
            def flip(self) -> str:
                if self.value is not None:
                    self.value = None
                else:
                    self.value = 0
                return str(self.value)
        def flip(flag: bool) -> str:
            value: int | None = 7 if flag else None
            if value is not None:
                value = None
            else:
                value = 0
            return str(value)
        def main() -> str:
            return flip(True) + flip(False) + Box(7).flip() + Box(None).flip()
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_scalar_lists_link_comparison_runtime(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def numbers(flag: bool) -> list[int] | None:
            return [0, 1] if flag else None
        def text(flag: bool) -> list[str] | None:
            gc_collect()
            return [str(123)] if flag else None
        def main() -> str:
            gc_set_threshold(1)
            return str(numbers(True) == numbers(True)) + str(numbers(True) == numbers(False)) + str(numbers(False) == numbers(False)) + str(text(True) == text(True)) + str(text(True) != text(False))
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("operation", ["value == None", "None == value", "value != None"])
@pytest.mark.parametrize("annotation", ["Base", "object"])
@pytest.mark.parametrize("method", ["__eq__", "__ne__"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_base_equality_checks_reached_overrides(tmp_path, operation, annotation, method, optimize):
    result = LLVM().assert_matches_python(f'''
        class Base:
            def __init__(self) -> None:
                self.label = "base"
        class Child(Base):
            def {method}(self, other: object) -> bool:
                return True
        def inspect(value: {annotation} | None) -> bool:
            return {operation}
        def main() -> str:
            return str(inspect(Child())) + str(inspect(Base())) + str(inspect(None))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("kind,initial", [("int", "1"), ("str", '"one"')])
def test_omitted_setdefault_requires_semantically_optional_values(kind, initial):
    with pytest.raises(LLVMUnsupported, match="setdefault without a concrete default requires optional dictionary values.*at line"):
        transpile_llvm(f'''
            def main() -> str:
                values: dict[str, {kind}] = {{"a": {initial}}}
                values.setdefault("missing")
                return str(values["a"])
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_object_optional_join_does_not_treat_none_as_present(optimize):
    LLVM().assert_matches_python('''
        def flip(value: object | None) -> bool:
            if value is None:
                value = "present"
            else:
                value = None
            return value is None
        def main() -> str:
            return str(flip("old")) + str(flip(None))
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_none_identity_after_optional_local_assignment(optimize):
    LLVM().assert_matches_python('''
        def main() -> str:
            number: int | None = None
            number = 4
            floating: float | None = None
            floating = 0.0
            return str(number is None) + str(None is number) + str(number is not None) + str(floating is None) + str(floating is not None)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
