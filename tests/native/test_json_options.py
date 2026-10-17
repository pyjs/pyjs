import itertools
import json

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_json_flags_are_call_scoped_and_propagate_to_children(tmp_path, optimize):
    library = LLVM().compile_library('''
        import json

        type JSON = str | float | list[JSON] | dict[str, JSON] | None

        def render(values: dict[str | bytes | float, JSON], ascii: bool,
                   nan: bool, skip: bool) -> str:
            try:
                return json.dumps(values, ensure_ascii=ascii, allow_nan=nan,
                                  skipkeys=skip, separators=(",", ":"))
            except ValueError:
                return "value error"
            except TypeError:
                return "type error"
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        cycle = []
        cycle.append(cycle)
        for ascii, nan, skip in itertools.product((False, True), repeat=3):
            for values in (
                {},
                {"é": ["雪", {"😀": "café"}, None]},
                {"numbers": [1.25, float("inf"), float("nan")]},
                {float("inf"): "key"},
                {b"first": cycle, "valid": "雪", b"last": float("nan")},
                {"valid": "first", b"middle": "bad key", "last": "last"},
                {b"only": "bad key"},
                {"nested": {"number": float("inf")}},
                {"recovered": "é"},
            ):
                try:
                    expected = json.dumps(values, ensure_ascii=ascii,
                                          allow_nan=nan, skipkeys=skip,
                                          separators=(",", ":"))
                except ValueError:
                    expected = "value error"
                except TypeError:
                    expected = "type error"
                assert library.render(values, ascii, nan, skip) == expected
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_json_flags_evaluate_once_in_call_order_before_encoding(optimize):
    LLVM().assert_matches_python('''
        import json
        from pyjs.native import gc_collect

        def input_value(events: list[str]) -> dict[str, str]:
            events.append("input")
            return {"é": "雪"}

        def flag(events: list[str], name: str, value: bool, fail: bool) -> bool:
            events.append(name)
            gc_collect()
            events.append(json.dumps(["é"], ensure_ascii=value))
            if fail:
                raise ValueError("flag failed")
            return value

        def main() -> str:
            events: list[str] = []
            output = ""
            for fail in (False, True, False):
                try:
                    output += json.dumps(
                        input_value(events),
                        skipkeys=flag(events, "skip", False, fail),
                        ensure_ascii=flag(events, "ascii", False, False),
                        allow_nan=flag(events, "nan", True, False),
                    )
                except ValueError:
                    output += "failed"
            for enabled in (False, True):
                output += json.dumps("雪", ensure_ascii=enabled)
                try:
                    output += json.dumps(float("nan"), allow_nan=enabled)
                except ValueError:
                    output += "strict"
            return output + "|" + str(events)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_json_separators_are_call_scoped_for_recursive_values(tmp_path, optimize):
    library = LLVM().compile_library('''
        import json

        type Value = str | int | list[Value] | dict[str, Value] | None

        def render(values: Value, separators: tuple[str, str] | None, ascii: bool) -> str:
            try:
                return json.dumps(values, separators=separators, ensure_ascii=ascii)
            except ValueError:
                return "cycle"
    ''', tmp_path, entry_point="render", optimize=optimize)
    try:
        shared = [1, None, "café 雪", {"x": [2, 3]}]
        cycle = []
        cycle.append(cycle)
        for separators in (None, (",", ":"), ("", ""), ("\n雪\x00", " => "), None):
            for ascii in (False, True):
                for values in (None, [], {}, shared, {"left": shared, "right": shared}):
                    expected = json.dumps(values, separators=separators, ensure_ascii=ascii)
                    assert library.render(values, separators, ascii) == expected
                assert library.render(cycle, separators, ascii) == "cycle"
                assert library.render(shared, separators, ascii) == json.dumps(
                    shared, separators=separators, ensure_ascii=ascii,
                )
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_json_separator_callbacks_keep_argument_order_and_gc_roots(tmp_path, optimize):
    LLVM().assert_matches_python('''
        import json
        from pyjs.native import gc_collect, gc_set_threshold

        def separators(events: list[str], value: str, fail: bool) -> tuple[str, str]:
            events.append("separators")
            gc_collect()
            if fail:
                raise ValueError("separator callback failed")
            return value + " | ", value + " = "

        def ascii_flag(events: list[str]) -> bool:
            events.append("ascii")
            gc_collect()
            events.append(json.dumps([1, 2], separators=("!", "?")))
            return False

        def default_separators(events: list[str]) -> None:
            events.append("default")
            gc_collect()

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            result = ""
            for fail in (False, True, False):
                try:
                    result += json.dumps(
                        (7, "é", [1, 2]),
                        separators=separators(events, "雪", fail),
                        ensure_ascii=ascii_flag(events),
                    )
                except ValueError:
                    result += "caught"
            result += json.dumps(
                {"a": [1, 2], "b": "雪"},
                ensure_ascii=ascii_flag(events),
                separators=separators(events, "next", False),
            )
            result += json.dumps([1, 2], separators=default_separators(events))
            return result + "|" + str(events)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_runtime_json_separators_survive_encoding_allocation_failures(tmp_path, optimize):
    source = transpile_llvm('''
        import json
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def encode(values: dict[str, list[str]], separators: tuple[str, str] | None) -> str:
            return json.dumps(values, separators=separators, ensure_ascii=False)

        def main() -> int:
            values = {"é": ["雪" * 4000, "quoted'"], "tail": ["last"]}
            separators = ("!" + str(7), " => " + str(8))
            expected = encode(values, separators)
            arm(1000)
            probe = encode(values, separators)
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
                    result = encode(values, separators)
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                if not caught or result != "unchanged":
                    return 2
                if encode(values, separators) != expected:
                    return 3
                if encode(values, None) != json.dumps(values, ensure_ascii=False):
                    return 4
                failure += 1
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
