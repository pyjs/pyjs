import sys

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import (
    CALLABLE_IDENTITY_CONTRACT,
    OPTIONAL_CALLBACK_OVERLOAD_CONTRACT,
)
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


@pytest.mark.parametrize("expression", ["double", "lambda value: value * 2"])
def test_typed_unary_callback_matches_python(tmp_path, expression):
    assert_text_matches_python(f'''
from collections.abc import Callable
def double(value: int) -> int:
    return value * 2
def apply(callback: Callable[[int], int], value: int) -> int:
    return callback(value)
def main() -> str:
    return str(apply({expression}, 21))
''', tmp_path)


def test_optional_callback_overload_preserves_lambda_context(tmp_path):
    assert_matches_python(OPTIONAL_CALLBACK_OVERLOAD_CONTRACT.source, tmp_path)


def test_callback_results_and_runtime_function_selection(tmp_path):
    assert_text_matches_python('''
from collections.abc import Callable
def add(left: int, right: int) -> int:
    return left + right
def subtract(left: int, right: int) -> int:
    return left - right
def choose(addition: bool) -> Callable[[int, int], int]:
    if addition:
        return add
    return subtract
def main() -> str:
    result = ""
    for addition in [True, False]:
        operation = choose(addition)
        result += str(operation(23, 19)) + ","
    return result
''', tmp_path)


def test_callback_exception_propagates_without_losing_caller_handler(tmp_path):
    assert_text_matches_python('''
from collections.abc import Callable
def checked(value: int) -> str:
    if value < 0:
        raise ValueError("negative key")
    return str(value)
def apply(callback: Callable[[int], str]) -> str:
    try:
        return callback(-1)
    except ValueError as error:
        return str(error) + ":" + callback(42)
def main() -> str:
    return apply(checked)
''', tmp_path)


def test_callback_observes_object_identity(tmp_path):
    assert_text_matches_python('''
from collections.abc import Callable
class Row:
    def __init__(self, rank: int):
        self.rank = rank
def update(row: Row) -> int:
    row.rank += 1
    return row.rank
def apply(callback: Callable[[Row], int], row: Row) -> int:
    return callback(row)
def main() -> str:
    row = Row(41)
    return str(apply(update, row)) + ":" + str(row.rank)
''', tmp_path)


def test_immediate_returned_callback_call(tmp_path):
    assert_text_matches_python('''
from collections.abc import Callable
def twice(value: int) -> int:
    return value * 2
def factory() -> Callable[[int], int]:
    return twice
def main() -> str:
    return str(factory()(21))
''', tmp_path)


def test_callback_fields_and_generic_local_annotations(tmp_path):
    assert_text_matches_python('''
from collections.abc import Callable
class Box[T]:
    def __init__(self, value: T):
        self.value = value
def negate(value: bool) -> bool:
    return not value
def main() -> str:
    box: Box[Callable[[bool], bool]] = Box(negate)
    callback: Callable[[bool], bool] = box.value
    return str(callback(False)) + str(box.value(True))
''', tmp_path)


def test_named_function_identity_and_fresh_lambda_identity(tmp_path):
    assert_matches_python(CALLABLE_IDENTITY_CONTRACT.source, tmp_path)


def test_callback_identity_compiles_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(CALLABLE_IDENTITY_CONTRACT.source, tmp_path)


def test_named_callback_identity_across_modules(tmp_path, monkeypatch):
    name = "callback_identity_library"
    (tmp_path / f"{name}.py").write_text('''from collections.abc import Callable
def increment(value: int) -> int:
    return value + 1
def named() -> Callable[[int], int]:
    return increment
''')
    monkeypatch.syspath_prepend(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    try:
        assert_text_matches_python(f'''from collections.abc import Callable
from {name} import increment, named
def main() -> str:
    callback: Callable[[int], int] = increment
    return str(callback is named()) + ":" + str(named()(41))
''', tmp_path)
    finally:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("use", [
    "callback: Callable[[str], int] = item.rank\n    return callback('value')",
    "return len(sorted(['a', 'b'], key=item.rank))",
])
def test_bound_method_callback_diagnostic_names_the_user_line(use):
    with pytest.raises(JVMUnsupported) as error:
        transpile_jvm(f'''from collections.abc import Callable
class Item:
    def rank(self, value: str) -> int:
        return len(value)
def main() -> int:
    item = Item()
    {use}
''')
    assert str(error.value) == (
        "JVM bound-method callbacks are not implemented at line 7 while compiling _pyjs_java_.main")


@pytest.mark.parametrize("declarations, expression, result, diagnostic", [
    ("", "lambda value: value + offset", "int", "JVM lambda captures are not implemented"),
    ("def default(value: int = 1) -> int: return value", "default", "int",
     "JVM function values require an emitted fixed-arity module function"),
    ("from pyjs import int64\ndef wide(value: int) -> int64: return int64(value)", "wide", "int64",
     "JVM callbacks with represented parameters or results are not implemented"),
])
def test_unsupported_callback_boundaries(declarations, expression, result, diagnostic):
    with pytest.raises(JVMUnsupported, match=diagnostic):
        transpile_jvm(f'''
from collections.abc import Callable
{declarations}
def main() -> int:
    offset = 2
    callback: Callable[[int], {result}] = {expression}
    return int(callback(21))
''')


def test_inline_only_builtin_callback_keeps_analyzer_diagnostic():
    with pytest.raises(CompilationError, match="Inline function 'abs' cannot be used as a value"):
        transpile_jvm('''
from collections.abc import Callable
def main() -> int:
    callback: Callable[[int], int] = abs
    return callback(-21)
''')


@pytest.mark.parametrize("listener_type", ["Callable[[], None]", "callable"])
def test_void_and_mixed_width_callback_slots(tmp_path, listener_type):
    assert_text_matches_python(f'''
from collections.abc import Callable
def record(values: list[int], value: int, factor: float, accept: bool) -> None:
    if accept:
        values.append(int(value * factor))
def apply(callback: Callable[[list[int], int, float, bool], None]) -> int:
    values: list[int] = []
    callback(values, 21, 2.0, True)
    callback(values, 50, 0.5, False)
    return values[0]
def noop() -> None:
    pass
def run(callback: {listener_type}) -> None:
    callback()
def main() -> str:
    run(noop)
    return str(apply(record))
''', tmp_path)
