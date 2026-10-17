"""A selected overload changes transport, not the returned Python value."""

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_direct_union_result_preserves_numeric_representation(tmp_path, optimize):
    from tests.backend_semantics import DIRECT_UNION_RESULT_CONTRACT
    comparison = LLVM().assert_matches_python(
        DIRECT_UNION_RESULT_CONTRACT.source, directory=tmp_path,
        optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_generic_union_orders_keep_instance_methods(tmp_path, optimize):
    from tests.backend_semantics import APPLICATION_GENERIC_UNION_ORDER_CONTRACT
    comparison = LLVM().assert_matches_python(
        APPLICATION_GENERIC_UNION_ORDER_CONTRACT.source, directory=tmp_path,
        optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_union_orders_preserve_numeric_items(tmp_path, optimize):
    from tests.backend_semantics import GENERIC_UNION_ORDER_CONTRACT
    comparison = LLVM().assert_matches_python(
        GENERIC_UNION_ORDER_CONTRACT.source, directory=tmp_path,
        optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def overloaded(actual, selected, value):
    return f'''
from typing import overload
@overload
def read(key: int) -> {selected}: ...
@overload
def read(key: str) -> {actual}: ...
def read(key: int | str) -> {actual}:
    return {value}
'''


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize(("actual", "selected", "value"), [
    ("int", "int | str", "4"),
    ("int | None", "int | str", "4"),
    ("list[int]", "list[int] | int", "[4, 7]"),
    ("list[int] | None", "list[int] | str", "[4, 7]"),
    ("str", "str | int", "'hello'"),
    ("float", "float | str", "1.25"),
    ("bool", "int | str", "True"),
    ("list[int]", "object", "[4, 7]"),
    ("int | str", "object | str", "4"),
    ("int | None", "object", "None"),
    ("str | None", "object", "None"),
    ("list[int] | None", "object", "None"),
])
def test_overload_results_construct_selected_transport(tmp_path, optimize, actual, selected, value):
    comparison = LLVM().assert_matches_python(overloaded(actual, selected, value) + f'''
from pyjs.native import gc_collect, gc_set_threshold
def forward() -> {selected}:
    return read(0)
def main() -> str:
    gc_set_threshold(1)
    direct = str(read(0))
    stored: {selected} = read(0)
    values: list[{selected}] = [read(0), forward()]
    gc_collect()
    return direct + ':' + str(stored) + ':' + str(values)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_integer_projection_retains_boolean_kind(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from typing import overload
from pyjs.native import gc_collect, gc_set_threshold
@overload
def read(key: int) -> int | None: ...
@overload
def read(key: str) -> int | str | None: ...
def read(key: int | str) -> int | str | None:
    values: list[int | str | None] = [True, False, 4, None]
    return values[key] if isinstance(key, int) else key
def main() -> str:
    gc_set_threshold(1)
    output: list[str] = []
    for index in [0, 1, 2, 3]:
        value = read(index)
        copied = value
        gc_collect()
        output.append(str(value))
        output.append(str(copied))
        output.append(value.__str__())
        output.append(repr(read(index)))
        output.append(str((bool(value), value is None, isinstance(value, bool))))
        if value is not None:
            output.append(str(int(value)))
            output.append(str(float(value)))
        try:
            output.append(str(int(read(index))))
        except TypeError:
            output.append('absent')
        erased: object = read(index)
        output.append(str(erased))
        converted: int | None = int(value) if value is not None else None
        output.append(str(converted))
    return '|'.join(output)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("actual", ["int | None", "list[int] | None"])
def test_optional_to_closed_union_checks_missing_arm(tmp_path, optimize, actual):
    selected = actual.replace("None", "str")
    result = LLVM().run_source(overloaded(actual, selected, "None") + '''
def main() -> str:
    try:
        return str(read(0))
    except TypeError:
        return 'checked'
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    # CPython ignores overload annotations; the native checked-result contract
    # rejects an absent arm before a consumer can interpret its payload.
    assert result.returncode == 0
    assert result.stdout == "checked"
    assert result.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_boolean_result_keeps_identity_until_explicit_integer_conversion(tmp_path, optimize):
    comparison = LLVM().assert_matches_python(overloaded("bool", "int", "True") + '''
def main() -> str:
    return str(read(0)) + ':' + str(read(0) + 1) + ':' + str(int(read(0)))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize(("actual", "selected", "value", "diagnostic"), [
    ("int", "float", "3", "explicit numeric conversion"),
    ("int | None", "float | None", "3", "explicit conversion"),
])
def test_overload_annotation_is_not_a_numeric_cast(actual, selected, value, diagnostic):
    with pytest.raises(LLVMUnsupported, match=diagnostic):
        transpile_llvm(overloaded(actual, selected, value) + '''
def main() -> str:
    return str(read(0))
''')


@pytest.mark.parametrize(("selected", "diagnostic"), [
    ("int", "narrowed int may be bool"), ("int | None", "explicit conversion"),
])
@pytest.mark.parametrize("boundary", ["local", "return", "argument"])
def test_boolean_overload_requires_conversion_before_integer_only_storage(selected, diagnostic, boundary):
    consumer = {
        "local": f'''
def main() -> str:
    value: {selected} = read(0)
    return str(value)
''',
        "return": f'''
def forward() -> {selected}:
    return read(0)
def main() -> str:
    return str(forward())
''',
        "argument": f'''
def consume(value: {selected}) -> str:
    return str(value)
def main() -> str:
    return consume(read(0))
''',
    }[boundary]
    with pytest.raises(LLVMUnsupported, match=diagnostic):
        transpile_llvm(overloaded("bool", selected, "True") + consumer)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize(("actual", "value"), [
    ("bool", "True"), ("bool | None", "False"), ("bool | None", "None"), ("bool | str", "True"),
])
def test_boolean_body_can_use_optional_integer_result_transport(tmp_path, optimize, actual, value):
    comparison = LLVM().assert_matches_python(overloaded(actual, "int | None", value) + '''
def main() -> str:
    inferred = read(0)
    return str(read(0)) + ':' + str(inferred) + ':' + str(inferred is None)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_static_union_validates_the_selected_signature_and_recovers(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
class Base:
    @staticmethod
    def label(value: int = 1) -> str:
        return str(value)
class Child(Base):
    @staticmethod
    def label(value: int, extra: int) -> str:
        return str(value + extra)
class Other:
    @staticmethod
    def label(value: int = 3) -> str:
        return str(value)
def read(value: Base | Other) -> str:
    return value.label()
def main() -> str:
    result = read(Base())
    try:
        result += read(Child())
    except TypeError:
        result += ":missing:"
    return result + read(Other()) + read(Base())
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_static_and_instance_methods_select_signature_once(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
class First:
    @staticmethod
    def read(value: int = 1, *, suffix: str = 'a') -> str:
        gc_collect()
        return str(value) + suffix
class Second:
    @staticmethod
    def read(value: int = 2, *, suffix: str = 'b') -> int:
        gc_collect()
        return value + len(suffix)
class Third:
    def read(self, value: int = 3, *, suffix: str = 'c') -> str:
        return str(value) + suffix
def pick(index: int, events: list[int]) -> First | Second | Third:
    events.append(index)
    return First() if index == 1 else Second() if index == 2 else Third()
def argument(events: list[int], fail: bool) -> int:
    events.append(9)
    gc_collect()
    if fail:
        raise ValueError('argument failed')
    return 7
def main() -> str:
    gc_set_threshold(1)
    events: list[int] = []
    output: list[str] = []
    for index in [1, 2, 3]:
        output.append(str(pick(index, events).read()))
        output.append(str(pick(index, events).read(argument(events, False), suffix='!')))
        try:
            output.append(str(pick(index, events).read(argument(events, True))))
        except ValueError:
            output.append('caught')
    return str((output, events))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_static_method_preserves_runtime_subclass_selection(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
class Base:
    @staticmethod
    def label() -> str:
        return 'base'
class Child(Base):
    @staticmethod
    def label() -> str:
        return 'child'
class Other:
    @staticmethod
    def label() -> str:
        return 'other'
def view(value: Base) -> Base | Other:
    return value
def read(value: Base | Other) -> str:
    return value.label()
def main() -> str:
    return read(view(Base())) + read(view(Child())) + read(Other())
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("result_type", ["int", "int | None"])
def test_static_subclass_boolean_result_uses_tagged_join(tmp_path, optimize, result_type):
    comparison = LLVM().assert_matches_python(f'''
class Base:
    @staticmethod
    def value() -> {result_type}:
        return 4
class Child(Base):
    @staticmethod
    def value() -> bool:
        return True
class Other:
    @staticmethod
    def value() -> {result_type}:
        return 7
def read(value: Base | Other) -> str:
    result = value.value()
    return str(result) + ':' + str(int(result) + 1)
def main() -> str:
    return read(Base()) + ':' + read(Child()) + ':' + read(Other())
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_union_method_arms_project_overloads_before_joining(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from typing import overload
class Number:
    @overload
    @staticmethod
    def read(key: int) -> int | str: ...
    @overload
    @staticmethod
    def read(key: str) -> int: ...
    @staticmethod
    def read(key: int | str) -> int:
        return 4
    @staticmethod
    def flag() -> int:
        return 3
class Text:
    def read(self, key: int | str) -> str:
        return 'text'
    @staticmethod
    def flag() -> bool:
        return True
def label(value: Number | Text) -> str:
    return str(value.read(0)) + ':' + str(value.flag()) + ':' + str(int(value.flag()) + 1)
def main() -> str:
    return label(Number()) + ':' + label(Text()) + ':' + str(Number.read(0))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
