import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.source import analyze_source
from pyjs.java import JVMUnsupported, transpile_jvm
from pyjs.java.analysis import JVM_ENVIRONMENT
from tests.backend_semantics import EXCEPTION_ARGS_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exception_causes import NATIVE_CAUSES
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
    run_jvm,
)


def test_shared_exception_arguments_contract(tmp_path):
    assert_matches_python(EXCEPTION_ARGS_CONTRACT.source, tmp_path)


def test_exception_arguments_contract_compiles_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(EXCEPTION_ARGS_CONTRACT.source, tmp_path)


def test_javascript_keeps_its_unsupported_arguments_boundary():
    from pyjs.javascript.source import compile_source
    with pytest.raises(CompilationError) as caught:
        with compile_source('''
from pyjs import js
@js
def main() -> int:
    return len(ValueError("message").args)
''', filename="argument_boundary.py"):
            pass
    assert caught.value.diagnostic.message == "Attribute 'args' is not defined on 'ValueError'"


@pytest.mark.parametrize("expression", [
    "cast(int, value) == 1", "1 == value", "cast(int, value) != 0", "0 != value",
])
def test_erased_arguments_compare_to_unboxed_literals(tmp_path, expression):
    assert_matches_python(f'''
from typing import cast
def main() -> int:
    value = ValueError(True).args[0]
    assert {expression}
    return 42
''', tmp_path)


@pytest.mark.parametrize(("operator", "method"), [("==", "__eq__"), ("!=", "__ne__")])
def test_forward_object_integer_comparison_keeps_the_shared_analysis_boundary(operator, method):
    with pytest.raises(CompilationError) as caught:
        transpile_jvm(f'''
def main() -> bool:
    value = ValueError(True).args[0]
    return value {operator} 1
''', filename="argument_boundary.py")
    assert caught.value.diagnostic.code == "PYJS1104"
    assert caught.value.diagnostic.message == f"Operator '{operator}' is not supported for object and int"
    assert caught.value.diagnostic.help == (
        f"Use operands with compatible types or define the corresponding {method}() method.",
    )
    assert (caught.value.filename, caught.value.lineno) == ("argument_boundary.py", 4)


def test_nullable_integer_comparison_distinguishes_none(tmp_path):
    assert_matches_python('''
from pyjs import int64
def compare(value: int64 | None) -> bool:
    return value == 9007199254740993
def main() -> int:
    return int(not compare(None) and compare(int64(9007199254740993)))
''', tmp_path)


@pytest.mark.parametrize("value", ["int64(0)", "int64(9007199254740993)"])
def test_optional_integer_comparison_keeps_exact_nonnull_values(tmp_path, value):
    assert_matches_python(f'''
from pyjs import int64
def compare(value: int64 | None) -> bool:
    return value == 9007199254740993
def main() -> int:
    return int(compare({value}))
''', tmp_path)


def test_reset_to_no_arguments_does_not_modify_a_saved_tuple(tmp_path):
    assert_matches_python('''
from typing import cast
class Failure(Exception):
    def clear(self) -> None:
        super().__init__()

def main() -> int:
    error = Failure("first")
    saved = error.args
    error.clear()
    assert len(error.args) == 0
    assert error.args is not saved
    assert cast(str, saved[0]) == "first"
    assert str(error) == ""
    return 42
''', tmp_path)


def test_args_analysis_preserves_variadic_object_tuple():
    source = "def main() -> tuple[object, ...]:\n    return ValueError(42).args\n"
    with analyze_source(source, wrap=False, environment=JVM_ENVIRONMENT) as analysis:
        result = analysis.entry_point.return_type
        assert result.name == "tuple__object__variadic"
        assert result.tuple_variadic
        assert {name: item.name for name, item in result.generic_types.items()} == {"T1": "object"}


@pytest.mark.parametrize("kind", ["BaseException", "Exception", "ValueError", "KeyError"])
@pytest.mark.parametrize("payload, value_type", [
    ('""', "str"), (repr("a'b\n📝"), "str"), ("42", "int"),
    ("(-9223372036854775807 - 1)", "int"), ("True", "bool"), ("False", "bool"),
])
def test_args_retain_original_scalar_not_rendered_message(tmp_path, kind, payload, value_type):
    assert_matches_python(f'''
from typing import cast

def main() -> int:
    empty = {kind}()
    error = {kind}({payload})
    assert len(empty.args) == 0
    assert len(error.args) == 1
    assert error.args is error.args
    assert cast({value_type}, error.args[0]) == {payload}
    assert cast({value_type}, error.args[-1]) == {payload}
    try:
        raise error
    except BaseException as caught:
        assert caught is error
        assert caught.args is error.args
    return 42
''', tmp_path)


def test_custom_initializer_replaces_args_without_mutating_saved_tuple(tmp_path):
    assert_text_matches_python('''
from typing import cast

class Failure(Exception):
    def __init__(self, path: str, revision: int = 0):
        self.path = path
        self.revision = revision

class Wrapped(Failure):
    def __init__(self, path: str, revision: int):
        super().__init__(path, revision)
        self.original = self.args
        super().__init__(path, revision + 1)

class Message(Exception):
    def __init__(self, path: str):
        super().__init__("failed: " + path)

def main() -> str:
    empty = Failure(path="note", revision=1)
    assert len(empty.args) == 0
    partial = Failure("note", revision=1)
    assert len(partial.args) == 1
    error = Wrapped("note", 42)
    assert len(error.args) == 2
    assert cast(str, error.args[0]) == "note"
    assert cast(int, error.args[1]) == 42
    assert error.args is error.original
    message = Message("first")
    saved = message.args
    message.__init__("second")
    assert saved is not message.args
    assert cast(str, saved[0]) == "failed: first"
    assert cast(str, message.args[0]) == "failed: second"
    return str(error) + "|" + str(message)
''', tmp_path)


def test_args_iteration_and_payload_evaluation_order(tmp_path):
    assert_text_matches_python('''
from typing import cast

class Failure(Exception):
    def __init__(self, first: str, second: str):
        pass

def payload(events: list[str], name: str) -> str:
    events.append(name)
    return name

def describe(args: tuple[object, ...]) -> str:
    result = ""
    for item in args:
        result += cast(str, item)
    return result

def main() -> str:
    events: list[str] = []
    error = Failure(payload(events, "first"), payload(events, "second"))
    assert len(events) == 2
    assert describe(error.args) == "firstsecond"
    assert describe(ValueError().args) == ""
    return "|".join(events)
''', tmp_path)


def test_failed_reinitialization_keeps_saved_args(tmp_path):
    assert_matches_python('''
from typing import cast
def message(fail: bool) -> str:
    if fail:
        raise ValueError("failed argument")
    return "new"
class Failure(Exception):
    def __init__(self, text: str):
        super().__init__(text)
    def reset(self, fail: bool) -> None:
        super().__init__(message(fail))
def main() -> int:
    error = Failure("original")
    saved = error.args
    try:
        error.reset(True)
    except ValueError:
        assert error.args is saved
        assert str(error) == "original"
    error.reset(False)
    assert error.args is not saved
    assert cast(str, saved[0]) == "original"
    assert cast(str, error.args[0]) == "new"
    return 42
''', tmp_path)


def test_boxed_args_preserve_boolean_integer_equality(tmp_path):
    assert_matches_python('''
from typing import cast
def main() -> int:
    true = ValueError(True).args[0]
    one = ValueError(1).args[0]
    false = ValueError(False).args[0]
    zero = ValueError(0).args[0]
    assert true == one
    assert one == true
    assert false == zero
    assert zero == false
    assert true != zero
    assert true != ValueError("True").args[0]
    assert cast(int, one) == 1
    assert cast(int, false) == 0
    assert cast(int, true) == 1
    return 42
''', tmp_path)


def test_union_args_and_nullable_missing_key(tmp_path):
    assert_matches_python('''
def inspect(error: ValueError | KeyError) -> int:
    return len(error.args)
def main() -> int:
    assert inspect(ValueError()) == 0
    assert inspect(KeyError("key")) == 1
    values: dict[str | None, str] = {}
    try:
        values[None]
    except KeyError as missing:
        assert len(missing.args) == 1
        assert missing.args[0] is None
    return 42
''', tmp_path)


def test_variadic_reference_tuple_literals_share_args_operations(tmp_path):
    assert_matches_python('''
from typing import cast
def values() -> tuple[str, ...]:
    result: tuple[str, ...] = ("one", "two")
    return result
def main() -> int:
    items = values()
    assert len(items) == 2
    assert items[-1] == "two"
    empty: tuple[object, ...] = ()
    assert len(empty) == 0
    result = ""
    for item in items:
        result += item
    assert result == "onetwo"
    return 42
''', tmp_path)


@pytest.mark.parametrize("index", ["0", "-1", "2147483648", "9223372036854775807", "(-9223372036854775807 - 1)"])
def test_args_index_errors_are_python_errors(tmp_path, index):
    assert_text_matches_python(f'''
from typing import cast
def main() -> str:
    error = ValueError()
    try:
        error.args[{index}]
    except IndexError as bounds:
        assert len(bounds.args) == 1
        assert cast(str, bounds.args[0]) == str(bounds)
        return str(bounds)
    return "missing error"
''', tmp_path)


def test_runtime_errors_retain_payloads_including_original_dictionary_keys(tmp_path):
    assert_matches_python('''
from typing import cast
class Key:
    pass

def main() -> int:
    values: list[int] = []
    try:
        values[0]
    except IndexError as bounds:
        assert cast(str, bounds.args[0]) == "list index out of range"
    try:
        assert False
    except AssertionError as empty:
        assert len(empty.args) == 0
    try:
        assert False, 42
    except AssertionError as assertion:
        assert cast(int, assertion.args[0]) == 42
    mapping: dict[str, str] = {}
    key = "missing's title"
    try:
        mapping[key]
    except KeyError as missing:
        assert cast(str, missing.args[0]) == key
    objects: dict[Key, str] = {}
    object_key = Key()
    try:
        objects[object_key]
    except KeyError as missing_object:
        assert missing_object.args[0] is object_key
    return 42
''', tmp_path)


def test_args_are_read_only():
    with pytest.raises(CompilationError) as caught:
        transpile_jvm('''
def main() -> int:
    error = ValueError("original")
    error.args = ("replacement",)
    return 0
''')
    assert caught.value.diagnostic.message == "Property 'args' is read-only"
    assert caught.value.diagnostic.code == "PYJS1103"
    assert caught.value.lineno == 4


@pytest.mark.parametrize("expression, method", [
    ("error.args == error.args", "__eq__"), ("error.args[0:1]", "__slice__"),
])
def test_unsupported_tuple_operations_have_compilation_diagnostics(expression, method):
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(f'''
def main() -> int:
    error = ValueError("message")
    {expression}
    return 0
''')
    assert str(caught.value) == (
        f"JVM variadic tuple {method} is not implemented at line 3 "
        "while compiling _pyjs_java_.main"
    )


def test_argument_tuple_items_cannot_be_assigned():
    with pytest.raises(CompilationError) as caught:
        transpile_jvm('''
def main() -> int:
    error = ValueError("message")
    error.args[0] = "replacement"
    return 0
''')
    assert caught.value.lineno == 4
    assert caught.value.diagnostic.code == "PYJS2001"
    assert caught.value.diagnostic.message == "Cannot assign to tuple items"


def test_erased_tuple_equality_rejects_instead_of_using_array_identity(tmp_path):
    result = run_jvm('''
from typing import cast
def equal(left: object, right: object) -> bool:
    return left == right
def main() -> int:
    first = ValueError("same").args
    second = ValueError("same").args
    try:
        equal(cast(object, first), cast(object, second))
    except TypeError as error:
        assert str(error) == "JVM reference-array equality is not implemented"
        return 42
    return 1
''', tmp_path)
    assert result.returncode == 42, result.stderr


@pytest.mark.parametrize(("annotation", "payload", "cast_type", "expected"), [
    ("float", "1.25", "float", "1.25"),
    ("i32", "i32(2147483647)", "int", "2147483647"),
    ("float32", "float32(1.1)", "float", "float(float32(1.1))"),
    ("int8", "int8(-128)", "int", "-128"),
])
def test_existing_numeric_constructor_payloads_remain_available(tmp_path, annotation, payload, cast_type, expected):
    assert_matches_python(f'''
from typing import cast
from pyjs import int8, float32
from pyjs.java import i32

class Payload(Exception):
    def __init__(self, value: {annotation}):
        self.value = value
    def __str__(self) -> str:
        return "payload"

def main() -> int:
    error = Payload({payload})
    assert cast({cast_type}, error.args[0]) == {expected}
    assert str(error) == "payload"
    return 42
''', tmp_path)


@pytest.mark.parametrize(("integer", "floating"), [
    ("0", "0.0"), ("0", "-0.0"), ("1", "1.0"), ("1", "1.5"),
    ("-1", "-1.0"), ("True", "1.0"), ("False", "-0.0"),
    ("9007199254740992", "9007199254740992"),
    ("9007199254740993", "9007199254740992"),
    ("9223372036854775807", "9223372036854775808"),
    ("-9223372036854775808", "-9223372036854775808"),
    ("-9223372036854775807", "-9223372036854775808"),
    ("0", "NaN"), ("1", "Infinity"), ("-1", "-Infinity"),
])
def test_erased_numeric_equality_preserves_integer_precision(tmp_path, integer, floating):
    assert_text_matches_python(f'''
from pyjs import jvm

@jvm.native("java/lang/Double", name="parseDouble")
def number(value: str) -> float:
    return float(value)

class Payload(Exception):
    def __init__(self, value: float):
        pass

def main() -> str:
    left = ValueError({integer}).args[0]
    right = Payload(number({floating!r})).args[0]
    assert (left == right) == (right == left)
    assert (left != right) == (right != left)
    return str(left == right) + str(left != right)
''', tmp_path)


@pytest.mark.parametrize(("left", "right"), [
    ("NaN", "NaN"), ("Infinity", "Infinity"),
    ("-Infinity", "Infinity"), ("-0.0", "0.0"), ("1.25", "1.5"),
])
def test_erased_float_equality_keeps_nan_and_signed_zero_semantics(tmp_path, left, right):
    assert_text_matches_python(f'''
from pyjs import jvm

@jvm.native("java/lang/Double", name="parseDouble")
def number(value: str) -> float:
    return float(value)

class Payload(Exception):
    def __init__(self, value: float):
        pass

def main() -> str:
    left = Payload(number({left!r})).args[0]
    right = Payload(number({right!r})).args[0]
    return str(left == right) + str(left == left)
''', tmp_path)


def test_original_reference_arguments_keep_identity_without_rich_formatting(tmp_path):
    assert_matches_python('''
from typing import cast

class Item:
    def __init__(self):
        self.value = 1

class Payload(Exception):
    def __init__(self, item: Item, values: list[int], absent: Item | None):
        pass
    def __str__(self) -> str:
        return "opaque"

def main() -> int:
    item = Item()
    values = [1, 2]
    error = Payload(item, values, None)
    assert error.args[0] is item
    assert error.args[2] is None
    cast(Item, error.args[0]).value = 42
    cast(list[int], error.args[1]).append(3)
    assert item.value == 42
    assert len(values) == 3
    assert str(error) == "opaque"
    return 42
''', tmp_path)


@pytest.mark.parametrize("payload", [
    "ValueError(1).args[0]", "ValueError(True).args[0]",
    "Payload(-0.0).args[0]", "cast(object, ValueError().args)",
])
@pytest.mark.parametrize(("operation", "events"), [
    ("mapping = {key(events): value(events)}", "keyvalue"),
    ("mapping.__setitem__(key(events), value(events))", "keyvalue"),
    ("mapping[key(events)]", "key"),
    ("mapping.get(key(events))", "key"),
    ("mapping.get(key(events), value(events))", "keyvalue"),
    ("key(events) in mapping", "key"),
])
def test_erased_dictionary_keys_reject_unsupported_hashing_after_arguments(
    tmp_path, payload, operation, events,
):
    actual = run_jvm(f'''
from typing import cast
class Payload(Exception):
    def __init__(self, value: float):
        pass
def key(events: list[str]) -> object:
    events.append("key")
    return {payload}
def value(events: list[str]) -> str:
    events.append("value")
    return "unused"
def main() -> int:
    mapping: dict[object, str] = {{}}
    events: list[str] = []
    outer = ValueError("outer")
    try:
        raise outer
    except ValueError:
        try:
            {operation}
        except TypeError as error:
            assert str(error) == "JVM erased numeric and reference-array dictionary keys are not implemented"
            assert error.__context__ is outer
            assert "".join(events) == {events!r}
            assert len(mapping) == 0
            return 42
    return 1
''', tmp_path)
    assert actual.returncode == 42, actual.stderr


def test_erased_supported_dictionary_keys_and_missing_arguments(tmp_path):
    assert_matches_python('''
from typing import cast
class Item:
    pass
class Payload(Exception):
    def __init__(self, value: Item | None):
        pass
def main() -> int:
    item = Item()
    object_key = Payload(item).args[0]
    string_key = ValueError("key").args[0]
    absent_key = Payload(None).args[0]
    mapping: dict[object, str] = {object_key: "object", string_key: "string"}
    mapping[absent_key] = "none"
    assert object_key in mapping
    assert mapping[object_key] == "object"
    assert mapping.get(string_key, "default") == "string"
    assert mapping.get(absent_key) == "none"
    assert mapping.get(cast(object, "missing"), "default") == "default"
    missing = Payload(Item()).args[0]
    try:
        mapping[missing]
    except KeyError as error:
        assert error.args[0] is missing
        return 42
    return 1
''', tmp_path)


@pytest.mark.parametrize(("annotation", "payload", "exposed"), [
    ("Inner", 'Inner("raw")', "error.args[0]"),
    ("Exception", "make()", "error.args[0]"),
    ("list[Exception]", "[make()]", "cast(list[Exception], error.args[0])[0]"),
])
def test_exception_payload_exposed_as_object_retains_java_formatter(
    tmp_path, annotation, payload, exposed,
):
    actual = run_jvm(f'''
from typing import cast
from pyjs import jvm

@jvm.native("java/lang/String", name="valueOf")
def render(value: object) -> str:
    return str(value)

class Inner(ValueError):
    def __str__(self) -> str:
        return "retained inner"

def make() -> Exception:
    return Inner("raw")

class Outer(Exception):
    def __init__(self, inner: {annotation}):
        pass

def main() -> str:
    error = Outer({payload})
    return render({exposed})
''', tmp_path)
    assert actual.returncode == 0, actual.stderr
    assert actual.stdout.endswith(": retained inner"), actual.stdout


@pytest.mark.parametrize("kind", ["NativeWrapper", "ChildWrapper", "GrandchildWrapper"])
def test_foreign_args_are_rejected_through_the_native_hierarchy(kind):
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(NATIVE_CAUSES + f'''
def main() -> int:
    error = {kind}(ValueError("original"))
    return len(error.args)
''')
    assert str(caught.value) == (
        "JVM native exceptions do not expose Python args at line 3 "
        "while compiling _pyjs_java_.main"
    )


def test_widened_foreign_args_raise_type_error_with_context(tmp_path):
    actual = run_jvm(NATIVE_CAUSES + '''
def inspect(error: BaseException) -> int:
    return len(error.args)

def main() -> int:
    try:
        parse("invalid")
    except NativeFailure as original:
        try:
            inspect(original)
        except TypeError as boundary:
            assert boundary.__context__ is original
            assert str(boundary) == "native exceptions do not expose Python args"
            return 42
    return 1
''', tmp_path)
    assert actual.returncode == 42, actual.stderr


@pytest.mark.parametrize("backend", ["llvm", "wasm"])
@pytest.mark.parametrize(("source", "caught_error"), [
    ('def main(error: Exception) -> int:\n    return len(error.args)\n', False),
    ('def main() -> int:\n    try:\n        raise ValueError("bad")\n'
     '    except ValueError as error:\n        return len(error.args)\n', True),
])
def test_other_backends_keep_a_focused_arguments_boundary(backend, source, caught_error):
    from pyjs.native.llvm import transpile_llvm
    from pyjs.webassembly import transpile_webassembly
    compiler = transpile_llvm if backend == "llvm" else transpile_webassembly
    with pytest.raises(CompilationError) as caught:
        compiler(source, filename="argument_boundary.py")
    assert caught.value.diagnostic.code == "PYJS2001"
    expected = "exception arguments are not implemented by this backend"
    if caught_error:
        expected = (
            "native exception details are borrowed: use str(value), compare with None, or reraise a caught exception"
            if backend == "llvm" else "native IR exception handlers are not implemented"
        )
    assert caught.value.diagnostic.message == expected
