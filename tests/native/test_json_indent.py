import json

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import EMPTY_LITERAL_SIBLING_CONTRACT
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_empty_literal_sibling_contract(optimize):
    comparison = LLVM().assert_matches_python(
        EMPTY_LITERAL_SIBLING_CONTRACT.source, optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert comparison.native.returncode == 0, EMPTY_LITERAL_SIBLING_CONTRACT.failure(comparison.native.returncode)
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_json_runtime_indent_matches_python_for_recursive_values(tmp_path, optimize):
    library = LLVM().compile_library('''
        import json

        type Value = str | int | list[Value] | dict[str, Value] | None

        def render(values: Value, indent: int | str | None,
                   separators: tuple[str, str] | None, ascii: bool) -> str:
            try:
                return json.dumps(values, indent=indent, separators=separators,
                                  ensure_ascii=ascii)
            except ValueError:
                return "cycle"
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        shared = [1, None, "café 雪", {"x": [2, 3], "empty": []}]
        cycle = []
        cycle.append(cycle)
        for indent in (None, -2, 0, 1, 3, "", "\t", "雪\x00", None):
            for separators in (None, (",", ":"), (" | ", " => "), ("", "")):
                for ascii in (False, True):
                    for values in (None, 7, [], {}, shared, {"a": shared, "b": shared}):
                        expected = json.dumps(values, indent=indent, separators=separators,
                                              ensure_ascii=ascii)
                        assert library.render(values, indent, separators, ascii) == expected
                    assert library.render(cycle, indent, separators, ascii) == "cycle"
                    assert library.render([1, 2], indent, separators, ascii) == json.dumps(
                        [1, 2], indent=indent, separators=separators, ensure_ascii=ascii,
                    )
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_json_indent_preserves_skipped_keys_and_tuple_layout(tmp_path, optimize):
    LLVM().assert_matches_python('''
        import json

        def optional_integer(indent: int | None) -> str:
            return json.dumps((1, "é", [2, 3], ()), indent=indent)

        def optional_string(indent: str | None) -> str:
            return json.dumps({"a": [], "b": [1]}, indent=indent,
                              separators=(", ", " = "))

        def skipped(indent: int | str | None) -> str:
            values: dict[str | bytes, list[int]] = {b"only": [1]}
            result = json.dumps(values, indent=indent, skipkeys=True)
            values["kept"] = [2, 3]
            values[b"tail"] = [4]
            result += json.dumps(values, indent=indent, skipkeys=True)
            return result

        def main() -> str:
            result = optional_integer(None) + optional_integer(2)
            result += optional_string(None) + optional_string("雪")
            result += skipped(None) + skipped(0) + skipped("  ")
            result += json.dumps([1, 2], indent=True)
            result += json.dumps([1, 2], indent=False)
            result += json.dumps([1, 2], indent=2, separators=None)
            result += json.dumps([1, 2], indent="\t", separators=(";", "="))
            return result
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_json_indent_callbacks_evaluate_once_and_keep_managed_strings(tmp_path, optimize):
    LLVM().assert_matches_python('''
        import json
        from pyjs.native import gc_collect, gc_set_threshold

        def indentation(events: list[str], fail: bool) -> str:
            events.append("indent")
            gc_collect()
            if fail:
                raise ValueError("indent callback failed")
            return "雪" + str(len(events))

        def separators(events: list[str]) -> tuple[str, str] | None:
            events.append("separators")
            gc_collect()
            return None

        def ascii_flag(events: list[str]) -> bool:
            events.append(json.dumps([1, 2], indent=1))
            gc_collect()
            return False

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            values = {"a": [1, 2], "é": []}
            result = ""
            for fail in (False, True, False):
                try:
                    result += json.dumps(
                        values,
                        separators=separators(events),
                        indent=indentation(events, fail),
                        ensure_ascii=ascii_flag(events),
                    )
                except ValueError:
                    result += "caught"
            result += json.dumps(
                [1, 2], indent=indentation(events, False),
                separators=separators(events),
            )
            return result + "|" + str(events)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_json_indent_allocation_failure_is_catchable_and_retryable(tmp_path, optimize):
    source = transpile_llvm('''
        import json
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def encode(values: list[list[int]], indent: int | str | None) -> str:
            return json.dumps(values, indent=indent)

        def main() -> int:
            values = [[1, 2], [], [3]]
            indent = "雪" * 2000
            expected = encode(values, indent)
            arm(1000)
            probe = encode(values, indent)
            stages = 1000 - remaining()
            arm(0)
            if probe != expected or stages < 5:
                return 1
            failure = 1
            while failure <= stages:
                result = "unchanged"
                caught = False
                arm(failure)
                try:
                    result = encode(values, indent)
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                if not caught or result != "unchanged":
                    return 2
                if encode(values, indent) != expected:
                    return 3
                if encode(values, None) != json.dumps(values):
                    return 4
                failure += 1
            try:
                result = encode(values, 9223372036854775807)
            except MemoryError:
                gc_collect()
                return 0 if encode(values, indent) == expected else 5
            return 6
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
