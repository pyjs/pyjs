from textwrap import dedent

import pytest

from pyjs.tooling.llvm import LLVM
from tests.semantics.helpers import run_python


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation, values", [
    ("str | None", '''["quoted'value", "", None]'''),
    ("int64 | None", "[int64(9007199254740993), int64(0), None]"),
    ("int | str | float | bool | None", '[7, "text", -0.5, True, None]'),
])
def test_nullable_and_union_exception_messages_preserve_payloads(optimize, annotation, values):
    LLVM().assert_matches_python(f'''
        from pyjs import int64
        from pyjs.native import gc_collect

        class MissingKey(KeyError):
            pass

        def message(value: {annotation}, quoted: bool) -> str:
            try:
                if quoted:
                    raise MissingKey(value)
                raise ValueError(value)
            except Exception as error:
                gc_collect()
                return str(error)

        def main() -> str:
            values: list[{annotation}] = {values}
            result: list[str] = []
            for value in values:
                result.append(message(value, False))
                result.append(message(value, True))
            return repr(result)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_nullable_collection_exception_message(optimize):
    result = LLVM().assert_matches_python('''
            def fail(value: list[int] | None) -> None:
                raise ValueError(value)
            def main() -> str:
                output: list[str] = []
                for value in [[1], None]:
                    try:
                        fail(value)
                    except ValueError as error:
                        output.append(str(error))
                return repr(output)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("name", ["str", "bytes", "int", "bool", "float", "object"])
@pytest.mark.parametrize("error", ["RuntimeError", "KeyError"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_exception_messages_do_not_read_application_records_as_builtin_text(name, error, optimize):
    source = dedent(f'''
            from builtins import int as Integer, str as Text
            from pyjs.native import gc_collect
            class {name}:
                def __init__(self, rank: Integer):
                    self.rank = rank
                def __str__(self) -> Text:
                    return 'record:' + Text(self.rank)
                def __repr__(self) -> Text:
                    return 'repr:' + Text(self.rank)
            def fail(value: {name} | None) -> Integer:
                gc_collect()
                raise {error}(value)
            def main() -> Integer:
                return fail({name}(123456))
    ''')
    # The borrowed snapshot guard intentionally accepts only literal str(error),
    # not aliases when a fixture shadows str. Compare uncaught formatting instead.
    expected = run_python(source + '\ntry:\n    main()\nexcept Exception as error:\n    print(Text(error), end="")\n')
    actual = LLVM().run_source(source, optimize=optimize, sanitizers=("address", "undefined"))
    assert expected.returncode == 0 and actual.returncode != 0
    assert actual.stderr.endswith(error + ": " + expected.stdout + "\n")
    assert "AddressSanitizer" not in actual.stderr and "runtime error:" not in actual.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("setup, operation, error", [
    ("", "1 // 0", "ZeroDivisionError"),
    ("", "1 % 0", "ZeroDivisionError"),
    ("", "1 / 0", "ZeroDivisionError"),
    ("", "1.0 // 0.0", "ZeroDivisionError"),
    ("", "1.0 % 0.0", "ZeroDivisionError"),
    ("", "1.0 / 0.0", "ZeroDivisionError"),
    ("", "divmod(1, 0)", "ZeroDivisionError"),
    ("", "divmod(1.0, 0.0)", "ZeroDivisionError"),
    ("", "1 << -1", "ValueError"),
    ("", "1 >> -1", "ValueError"),
    ("", "range(0, 1, 0)", "ValueError"),
    ("", "range(3)[-4]", "IndexError"),
    ("", "len(range(-9223372036854775808, 9223372036854775807))", "OverflowError"),
    ("", "'☃雪'[2]", "IndexError"),
    ("", "'☃雪'[::-0]", "ValueError"),
    ("", "'value'.split('')", "ValueError"),
    ("", 'int("12x")', "ValueError"),
    ("", 'int("١٢x", 16)', "ValueError"),
    ("", 'int("9" * 100 + "!")', "ValueError"),
    ("", 'int("1", 1)', "ValueError"),
    ("", 'float("abc")', "ValueError"),
    ("", 'int(float("inf"))', "OverflowError"),
    ("", 'int(float("-inf"))', "OverflowError"),
    ("items = [1, 2]", "items[2]", "IndexError"),
    ("items = [1, 2]", "items[-3] = 4", "IndexError"),
    ("items = [1, 2]", "items.pop(2)", "IndexError"),
    ("items: list[int] = []", "items.pop()", "IndexError"),
    ("items = [1, 2]", "items.index(3)", "ValueError"),
    ("items = [1, 2]", "items.remove(3)", "ValueError"),
    ("items = [1, 2]", "items[::0]", "ValueError"),
    ("items = {'yes': 1}", "items['missing\\t☃']", "KeyError"),
    ("items = {1: 2}", "items.pop(3)", "KeyError"),
    ("items = {True: 1}", "del items[False]", "KeyError"),
    ("items = {'yes'}", "items.remove('no')", "KeyError"),
    ("items = {1: 2}", "for key in items:\n            items[3] = 4", "RuntimeError"),
    ("items = {1}", "for key in items:\n            items.add(3)", "RuntimeError"),
])
def test_implicit_errors_match_cpython(tmp_path, optimize, setup, operation, error):
    source = f'''
def main() -> str:
    {setup or 'pass'}
    try:
        {operation}
    except {error} as error:
        return str(error)
    return "error not raised"
'''
    result = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize)
    assert result.native.stdout != "error not raised"


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("key", ["plain", "a'b", 'a"b', "a'\"b", "\\\n\r\t\x00", "☃雪\u200b\U000e0001"])
def test_explicit_and_implicit_key_errors_share_repr(tmp_path, optimize, key):
    source = f'''
def main() -> str:
    messages: list[str] = []
    try:
        raise KeyError({key!r})
    except KeyError as error:
        messages.append(str(error))
    items = {{"different": 1}}
    try:
        items[{key!r}]
    except LookupError as error:
        messages.append(str(error))
    return "|".join(messages)
'''
    LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_numeric_error_messages_survive_gc_and_distinguish_native_limits(tmp_path, optimize):
    LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
def main() -> str:
    gc_set_threshold(1)
    messages: list[str] = []
    for text in ["bad'\\\"\\t", "١٢x", "9" * 100 + "!"]:
        try:
            int(text, 16)
        except ValueError as error:
            messages.append(str(error))
        try:
            float(text)
        except ValueError as error:
            messages.append(str(error))
        gc_collect()
    try:
        value = int("9" * 100)
        # CPython supports this value; LLVM deliberately remains signed i64.
        if value > 9223372036854775807:
            messages.append("integer value is outside native signed i64 range")
    except ValueError as error:
        messages.append(str(error))
    gc_collect()
    return "|".join(messages)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("error_type", ["KeyError", "MissingKey", "ValueError"])
@pytest.mark.parametrize("payload", ["[65]", "{'x': 65}", "(65,)", "Box()"])
def test_non_scalar_exception_payloads_and_inherited_key_formatting(error_type, payload):
    result = LLVM().assert_matches_python(f'''
class MissingKey(KeyError):
    pass
class Box:
    def __init__(self):
        self.value = 65
    def __str__(self) -> str:
        return "str:" + str(self.value)
    def __repr__(self) -> str:
        return "repr:" + str(self.value)
def main() -> str:
    try:
        raise {error_type}({payload})
    except Exception as error:
        return str(error)
    return "missing"
''', sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("payload", ['"quoted\\\"value"', "65", "True", "1.25", "None", ""])
def test_key_error_scalar_and_subclass_messages(tmp_path, optimize, payload):
    LLVM().assert_matches_python(f'''
class MissingKey(KeyError):
    pass
def main() -> str:
    messages: list[str] = []
    try:
        raise KeyError({payload})
    except KeyError as error:
        messages.append(str(error))
    try:
        raise MissingKey({payload})
    except KeyError as error:
        messages.append(str(error))
    return "|".join(messages)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("setup, mutation", [
    ("items = {1: 2}", "items[3] = 4"),
    ("items = {1}", "items.add(3)"),
])
def test_collection_iteration_recovers_after_a_caught_size_change(tmp_path, optimize, setup, mutation):
    LLVM().assert_matches_python(f'''
def main() -> str:
    {setup}
    messages: list[str] = []
    try:
        for item in items:
            {mutation}
    except RuntimeError as error:
        messages.append(str(error))
    total = 0
    for item in items:
        total += item
    return "|".join(messages) + ":" + str(total)
''', directory=tmp_path, optimize=optimize)
