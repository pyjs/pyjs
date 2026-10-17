import subprocess

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.source import analyze_source
from pyjs.java import JVMUnsupported, read_jvm_class, transpile_jvm
from pyjs.java.analysis import JVM_ENVIRONMENT
from tests.backend_semantics import (
    APPLICATION_GENERIC_UNION_ORDER_CONTRACT,
    CALLABLE_INPUT_CONTRACT,
    DATACLASS_NAN_IDENTITY_SOURCE,
    DIRECT_UNION_RESULT_CONTRACT,
    GENERIC_UNION_ORDER_CONTRACT,
    POSTPONED_DATACLASS_CONTRACT,
)
from tests.java.test_jvm import java
from tests.semantics.helpers import run_python


def test_bytes_construction_keeps_the_jvm_binary_boundary():
    from tests.backend_semantics import BYTES_CONSTRUCTION_CONTRACT
    with pytest.raises(CompilationError, match="bytes literals are not supported"):
        transpile_jvm(BYTES_CONSTRUCTION_CONTRACT.source)


@pytest.mark.parametrize("expression, diagnostic", [
    ("range(Index())", "JVM range arguments must be int"),
    ("enumerate([1], Index())", "JVM cannot iterate over Iterator"),
])
def test_index_constructors_keep_the_jvm_boundary(expression, diagnostic):
    with pytest.raises(JVMUnsupported, match=diagnostic):
        transpile_jvm(f'''
            class Index:
                def __index__(self) -> int:
                    return 3
            def main() -> int:
                total = 0
                for value in {expression}:
                    total += 1
                return total
        ''')


def test_slice_values_keep_the_jvm_boundary():
    from tests.backend_semantics import SLICE_VALUE_CONTRACT
    with pytest.raises(JVMUnsupported, match="unsupported JVM type annotation"):
        transpile_jvm(SLICE_VALUE_CONTRACT.source)


@pytest.mark.parametrize("expression", ["len(values[slice(1, None)])", "values[slice(1)]", "slice(1)"])
def test_inline_slice_construction_has_a_located_jvm_boundary(expression):
    with pytest.raises(JVMUnsupported, match="JVM first-class slice construction is not implemented"):
        transpile_jvm(f"def main():\n    values = [1, 2, 3]\n    {expression}\n    return 0\n")


def test_bounded_text_search_keeps_a_focused_jvm_boundary():
    from tests.backend_semantics import BOUNDED_TEXT_SEARCH_CONTRACT
    with pytest.raises(JVMUnsupported, match="unsupported JVM type annotation"):
        transpile_jvm(BOUNDED_TEXT_SEARCH_CONTRACT.source)


def test_extracted_union_result_reaches_the_jvm_callable_boundary():
    from tests.backend_semantics import UNION_CALLBACK_RESULT_CONTRACT
    with pytest.raises(JVMUnsupported, match="unsupported JVM type annotation"):
        transpile_jvm(UNION_CALLBACK_RESULT_CONTRACT.source)


@pytest.mark.parametrize("contract", [DIRECT_UNION_RESULT_CONTRACT, GENERIC_UNION_ORDER_CONTRACT,
                                     APPLICATION_GENERIC_UNION_ORDER_CONTRACT],
                         ids=["direct-method", "generic-container", "application-generic"])
def test_union_result_keeps_the_jvm_mixed_layout_boundary(contract):
    with pytest.raises(JVMUnsupported, match="JVM union has incompatible runtime types"):
        transpile_jvm(contract.source)


def test_callable_iterable_views_reach_a_focused_jvm_boundary():
    from tests.backend_semantics import CALLABLE_ITERABLE_CONTRACT
    with pytest.raises(JVMUnsupported, match="function values are not implemented|unsupported JVM type annotation"):
        transpile_jvm(CALLABLE_ITERABLE_CONTRACT.source)


def test_nested_literal_context_reaches_the_jvm_iterable_boundary():
    from tests.backend_semantics import ITERABLE_LITERAL_CONTEXT_CONTRACT
    with pytest.raises(JVMUnsupported, match="unsupported JVM value type Iterable__list__list__int"):
        transpile_jvm(ITERABLE_LITERAL_CONTEXT_CONTRACT.source)


def test_callback_input_views_reach_the_jvm_callable_boundary():
    with pytest.raises(JVMUnsupported, match="unsupported JVM type annotation"):
        transpile_jvm(CALLABLE_INPUT_CONTRACT.source)


def test_default_callable_views_reach_the_jvm_callable_boundary():
    from tests.backend_semantics import CALLABLE_DEFAULT_CONTRACT
    with pytest.raises(JVMUnsupported, match="function values are not implemented|unsupported JVM type annotation"):
        transpile_jvm(CALLABLE_DEFAULT_CONTRACT.source)


@pytest.mark.parametrize("parameter", ["int", "int | None"])
def test_named_function_values_have_a_located_jvm_diagnostic(parameter):
    with pytest.raises(JVMUnsupported, match=r"JVM function values are not implemented at line 2 while compiling .*factory"):
        transpile_jvm(f'''
            from collections.abc import Callable
            def broad(value: {parameter}) -> int:
                return 7
            def factory() -> Callable[[int], int]:
                return broad
            def main() -> int:
                return factory()(3)
        ''')


def test_generic_fromkeys_reaches_a_located_classmethod_boundary():
    with pytest.raises(JVMUnsupported, match="Python classmethod calls are not implemented"):
        transpile_jvm('''
            def main() -> int:
                values = dict.fromkeys(['a', 'b'], 'value')
                return len(values)
        ''')


@pytest.mark.parametrize("expression,return_type", [
    ("round(number=2.5)", "int"),
    ("round(number=2.675, ndigits=2)", "float"),
    ("round(ndigits=2, number=2.675)", "float"),
    ("round(number=int64(125), ndigits=-1)", "int64"),
    ("round(ndigits=2, number=float32(2.675))", "float32"),
])
def test_keyword_round_reaches_supported_backend_boundary(expression, return_type):
    source = f"from pyjs import int64, float32\ndef main() -> {return_type}: return {expression}\n"
    with pytest.raises((JVMUnsupported, CompilationError), match="round"):
        transpile_jvm(source)


def run_jvm(source, directory):
    transpile_jvm(source).write(directory)
    return subprocess.run(
        [java(), "-Xmx128m", "-Xverify:all", "-cp", str(directory), "PyjsProgram"],
        capture_output=True, text=True, timeout=30,
    )


def test_shared_empty_literal_sibling_contract(tmp_path):
    from tests.backend_semantics import EMPTY_LITERAL_SIBLING_CONTRACT
    result = run_jvm(EMPTY_LITERAL_SIBLING_CONTRACT.source, tmp_path)
    assert result.returncode == 0, result.stderr or EMPTY_LITERAL_SIBLING_CONTRACT.failure(result.returncode)
    assert not result.stderr


def test_postponed_dataclass_shared_contract(tmp_path):
    result = run_jvm(POSTPONED_DATACLASS_CONTRACT, tmp_path)
    assert result.returncode == 42, result.stderr
    assert result.stderr == ""


def test_dataclass_equality_retains_explicit_jvm_runtime_type_boundary():
    with pytest.raises(JVMUnsupported, match="same_dataclass_type has no emitted definition"):
        transpile_jvm(DATACLASS_NAN_IDENTITY_SOURCE)


def test_annotation_only_field_without_js_is_available_to_early_root(tmp_path):
    source = '''
class Deferred:
    value: int

def read(item: Deferred) -> int:
    return item.value

def main() -> str:
    item = Deferred()
    item.value = 7
    return str(read(item))
'''
    with analyze_source(source, entry_point="read", wrap=False, environment=JVM_ENVIRONMENT) as analysis:
        assert analysis.entry_point.name == "read"
    compilation = transpile_jvm(source)
    holder = read_jvm_class(compilation.classes["PyjsProgram$Deferred"])
    assert [(field.name, field.descriptor) for field in holder.fields] == [("value", "J")]
    compilation.write(tmp_path)
    result = subprocess.run(
        [java(), "-Xmx128m", "-Xverify:all", "-cp", str(tmp_path), "PyjsProgram"],
        capture_output=True, text=True, timeout=30,
    )
    expected = run_python(source + "\nprint(main())")
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected.stdout.strip() == "7"


@pytest.mark.parametrize("child_initializer", [
    "pass",
    "def __init__(self, name: str):\n        super().__init__(name)",
])
def test_native_constructor_arguments_survive_application_subclasses(
    tmp_path, child_initializer,
):
    source = f'''
from pyjs import jvm

@jvm.native("java/lang/Thread")
class Thread:
    def __init__(self, name: str):
        self.name = name

    @jvm.native("java/lang/Thread", name="getName", invocation="virtual")
    def get_name(self) -> str:
        return self.name

class Worker(Thread):
    def __init__(self, name: str):
        super().__init__(name)
        self.calls = 1

class Child(Worker):
    {child_initializer}

class Grandchild(Child):
    def __init__(self, name: str):
        super().__init__(name)
        self.calls = self.calls + 1

def main() -> str:
    child = Grandchild("hello")
    return child.get_name() + str(child.calls)
'''
    expected = run_python(source + "\nprint(main())")
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected.stdout.strip() == "hello2"


@pytest.mark.parametrize(("item", "descriptor", "value"), [
    ("i32", "I", "i32(7)"), ("f32", "F", "f32(1.5)"),
    ("JVMArray[i32]", "[I", "JVMArray[i32](2)"),
])
def test_array_fields_and_optional_boundaries_keep_recursive_abi(
    tmp_path, item, descriptor, value,
):
    first_item = "len(values[0]) == 2" if descriptor == "[I" else f"values[0] == {value}"
    source = f'''
from typing import cast
from pyjs.java import JVMArray, i32, f32

class Holder:
    def __init__(self):
        self.values = JVMArray[{item}](2)
        self.values[0] = {value}

    def get(self) -> JVMArray[{item}]:
        return self.values

def identity(values: JVMArray[{item}] | None) -> JVMArray[{item}] | None:
    return values

def make(flag: bool) -> JVMArray[{item}] | None:
    if flag:
        return Holder().get()
    return None

def main() -> int:
    optional = identity(make(True))
    assert optional is not None
    values = cast(JVMArray[{item}], optional)
    assert values is not None
    assert len(values) == 2
    assert {first_item}
    assert identity(make(False)) is None
    return 0
'''
    compilation = transpile_jvm(source)
    holder = read_jvm_class(compilation.classes["PyjsProgram$Holder"])
    assert [(field.name, field.descriptor) for field in holder.fields] == [
        ("values", "[" + descriptor),
    ]
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("annotation", ["JVMArray[i32] | None", "None | JVMArray[i32]"])
def test_optional_array_fields_preserve_none_and_branch_assignments(tmp_path, annotation):
    source = f'''
from typing import cast
from pyjs.java import JVMArray, i32

class Holder:
    def __init__(self):
        self.values: {annotation} = None

    def fill(self, flag: bool) -> None:
        if flag:
            values = JVMArray[i32](2)
        else:
            values = JVMArray[i32](3)
        values[0] = i32(7)
        self.values = values

def main() -> int:
    holder = Holder()
    assert holder.values is None
    holder.fill(True)
    assert holder.values is not None
    values = cast(JVMArray[i32], holder.values)
    assert values[0] == 7
    holder.fill(False)
    assert len(holder.values) == 3
    return 0
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr


KEY_SOURCE = '''
class Base:
    pass

class Key(Base):
    def __init__(self, value: int):
        self.value = value

    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 1

class Child(Key):
    pass
'''


@pytest.mark.parametrize("key_type", ["Key", "Child"])
def test_custom_dictionary_keys_reject_java_identity_semantics(key_type):
    source = KEY_SOURCE + f'''
def main() -> str:
    values: dict[{key_type}, str] = {{{key_type}(1): "found"}}
    return values.get({key_type}(1), "missing")
'''
    assert run_python(source + "\nprint(main())").stdout.strip() == "found"
    with pytest.raises(JVMUnsupported, match="dictionary keys.*Python __eq__/__hash__"):
        transpile_jvm(source)


@pytest.mark.parametrize("operator", ["==", "!="])
def test_nullable_custom_equality_requires_python_bridges(operator):
    source = KEY_SOURCE + f'''
def compare(left: Key | None, right: Key | None) -> bool:
    return left {operator} right

def main() -> int:
    return int(compare(Key(1), Key(2)))
'''
    assert run_python(source + "\nprint(main())").stdout.strip() == (
        "1" if operator == "==" else "0"
    )
    with pytest.raises(JVMUnsupported, match="dynamic equality.*Python __eq__/__hash__"):
        transpile_jvm(source)


def test_base_typed_keys_cannot_hide_custom_subclass_equality():
    source = KEY_SOURCE + '''
def main() -> str:
    values: dict[Base, str] = {Child(1): "found"}
    return values.get(Child(1), "missing")
'''
    with pytest.raises(JVMUnsupported, match="dictionary keys.*Python __eq__/__hash__"):
        transpile_jvm(source)


def test_identity_keys_and_nullable_identity_equality_remain_supported(tmp_path):
    source = '''
class Key:
    pass

def compare(left: Key | None, right: Key | None) -> bool:
    return left == right and not (left != right)

def main() -> str:
    key = Key()
    other = Key()
    values: dict[Key, str] = {key: "found"}
    assert compare(key, key)
    assert compare(None, None)
    assert not compare(key, other)
    assert not compare(key, None)
    assert values.get(other, "missing") == "missing"
    return values[key]
'''
    expected = run_python(source + "\nprint(main())")
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected.stdout.strip() == "found"


@pytest.mark.parametrize(("item", "maximum"), [
    ("uint8", 255), ("uint16", 65535), ("uint32", 4294967295),
])
def test_unsigned_array_reads_preserve_values_and_wrapping(tmp_path, item, maximum):
    source = f'''
from pyjs import {item}
from pyjs.java import JVMArray

class Holder:
    def __init__(self):
        self.values = JVMArray[{item}](1)
        self.values[0] = {item}({maximum})

def read(values: JVMArray[{item}]) -> {item}:
    return values[0]

def read_nested(values: JVMArray[JVMArray[{item}]]) -> {item}:
    return values[0][0]

def main() -> int:
    values = JVMArray[{item}](1)
    values[0] = {item}({maximum})
    nested = JVMArray[JVMArray[{item}]](1)
    nested[0] = values
    assert values[0] == {maximum}
    assert values[0] + 1 == 0
    assert read(values) == {maximum}
    assert read(values) + 1 == 0
    assert read_nested(nested) == {maximum}
    assert read_nested(nested) + 1 == 0
    assert Holder().values[0] == {maximum}
    return 0
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("index", [-2**63, -2**32, -1, 1, 2**31, 2**32, 2**63 - 1])
@pytest.mark.parametrize("operation", ["read", "write"])
def test_array_indexes_never_wrap_to_another_element(tmp_path, index, operation):
    expression = f"return values[{index}]" if operation == "read" else (
        f"values[{index}] = i32(7)\n    return values[0]"
    )
    source = f'''
from pyjs.java import JVMArray, i32

def main() -> int:
    values = JVMArray[i32](1)
    values[0] = i32(0)
    {expression}
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode != 0
    assert "java.lang.ArrayIndexOutOfBoundsException" in result.stderr


@pytest.mark.parametrize("length", [-2**32, 2**31, 2**32, 2**63 - 1])
def test_array_lengths_never_wrap_before_allocation(tmp_path, length):
    source = f'''
from pyjs.java import JVMArray, i32

def main() -> int:
    return len(JVMArray[i32]({length}))
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode != 0
    assert "java.lang.NegativeArraySizeException" in result.stderr


def test_array_write_evaluates_value_before_rejecting_a_wide_index(tmp_path):
    source = '''
from pyjs.java import JVMArray, i32

def value() -> i32:
    raise ValueError("value evaluated")

def main() -> int:
    values = JVMArray[i32](1)
    values.__setitem__(4294967296, value())
    return 0
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode != 0
    assert "value evaluated" in result.stderr
    assert "ArrayIndexOutOfBoundsException" not in result.stderr
