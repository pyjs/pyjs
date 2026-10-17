import json

import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_scalar_enum_keys_are_not_omitted_or_rejected(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        import json
        from enum import IntEnum, StrEnum

        class Number(IntEnum):
            HIGH = 5
            LOW = -2

        class Word(StrEnum):
            HIGH = "雪"
            LOW = "a"

        def main() -> str:
            numbers = {Number.HIGH: "high", Number.LOW: "low"}
            words = {Word.HIGH: 5, Word.LOW: -2}
            output = ""
            for skip in (False, True):
                for ordered in (False, True):
                    output += json.dumps(numbers, skipkeys=skip, sort_keys=ordered)
                    output += json.dumps(words, skipkeys=skip, sort_keys=ordered, ensure_ascii=False)
            return output
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


def test_generic_key_error_uses_runtime_class_name(tmp_path):
    result = LLVM().assert_matches_python('''
        import json
        class Key[T]:
            def __init__(self, value: T):
                self.value = value
        def main() -> str:
            try:
                return json.dumps({Key(1): "value"})
            except TypeError as error:
                return str(error)
    ''', directory=tmp_path, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_native_key_domains_skip_before_punctuation_and_value_traversal(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        import json
        from pyjs.native import gc_collect

        def encode(skip: bool, indent: int) -> str:
            first: dict[str | bytes | int | float | bool | None, list[float]] = {
                b"first": [float("nan")], "text": [1.0], None: [],
                b"middle": [float("inf")], -0.0: [2.0], b"last": [float("nan")],
            }
            omitted: dict[bytes, list[float]] = {b"only": [float("nan")]}
            last: dict[int | None, str] = {None: "null", -3: "negative"}
            try:
                return json.dumps((first, omitted, last), skipkeys=skip,
                                  allow_nan=False, indent=indent, separators=(",", ":"))
            except TypeError as error:
                gc_collect()
                return str(error)

        def main() -> str:
            return "|".join([encode(skip, indent) for skip in [False, True]
                             for indent in [0, 2]])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_json_numeric_null_and_string_keys_preserve_order_and_collisions(tmp_path):
    library = LLVM().compile_library('''
        import json

        def render(values: dict[str | int | float | bool | None, str]) -> str:
            return json.dumps(values, separators=(",", ":"), ensure_ascii=False)
    ''', tmp_path, entry_point="render")
    try:
        for values in (
            {},
            {True: "boolean", False: "false", None: "null"},
            {1: "integer", "1": "string", "null": "text", None: "none"},
            {-0.0: "zero", 1.25: "fraction", 2**53 + 1: "exact", "é": "café"},
            {float("nan"): "nan", float("inf"): "infinity", -float("inf"): "negative"},
        ):
            assert library.render(values) == json.dumps(
                values, separators=(",", ":"), ensure_ascii=False,
            )
    finally:
        library.close()


def test_json_skipped_keys_do_not_emit_delimiters_or_visit_values(tmp_path):
    library = LLVM().compile_library('''
        import json

        type JSON = str | float | list[JSON] | dict[str, JSON] | None

        def render(values: dict[str | bytes | int, JSON]) -> str:
            try:
                ordinary = json.dumps(values)
            except TypeError:
                ordinary = "invalid key"
            return ordinary + "|" + json.dumps(
                values, skipkeys=True, allow_nan=False, separators=(",", ":"),
            )
    ''', tmp_path, entry_point="render")
    try:
        cycle = []
        cycle.append(cycle)
        for values in (
            {},
            {b"first": float("nan"), "valid": "first", b"last": cycle},
            {b"only": cycle},
            {"first": "a", b"middle": cycle, 3: "b", b"last": float("inf")},
            {"next": ["recovered", None]},
        ):
            try:
                ordinary = json.dumps(values)
            except TypeError:
                ordinary = "invalid key"
            expected = ordinary + "|" + json.dumps(
                values, skipkeys=True, allow_nan=False, separators=(",", ":"),
            )
            assert library.render(values) == expected
    finally:
        library.close()


def test_json_optional_and_unsupported_tuple_keys():
    comparison = LLVM().assert_matches_python('''
        import json

        def main() -> str:
            numbers: dict[int | None, str] = {None: "none", -3: "integer"}
            strings: dict[str | None, str] = {None: "none", "null": "string"}
            tuples: dict[tuple[int, int], list[float]] = {(1, 2): [float("nan")]}
            empty: dict[tuple[int, int], str] = {}
            result = json.dumps((numbers, strings, empty))
            result += "|" + json.dumps(tuples, skipkeys=True, allow_nan=False)
            try:
                json.dumps(tuples)
            except TypeError:
                return result + "|invalid key"
            return "missed error"
    ''')
    assert comparison.matches


def test_json_nonfinite_keys_remain_errors_when_skipping_is_enabled(tmp_path):
    library = LLVM().compile_library('''
        import json

        def render(values: dict[float, str]) -> str:
            try:
                return json.dumps(values, skipkeys=True, allow_nan=False)
            except ValueError:
                return "nonfinite key"
    ''', tmp_path, entry_point="render")
    try:
        for key in (float("nan"), float("inf"), -float("inf")):
            assert library.render({key: "value"}) == "nonfinite key"
        assert library.render({1.5: "recovered"}) == '{"1.5": "recovered"}'
    finally:
        library.close()
