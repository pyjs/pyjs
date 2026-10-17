import json

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("ensure_ascii", [True, False])
def test_recursive_json_values_shared_subtrees_and_cycles(tmp_path, ensure_ascii):
    library = LLVM().compile_library(f"""
        import json
        from pyjs.native import gc_count

        type JSON = str | int | float | bool | list[JSON] | dict[str, JSON] | None

        def render(value: JSON) -> str:
            try:
                return json.dumps(value, ensure_ascii={ensure_ascii})
            except ValueError as error:
                if gc_count() != 0:
                    return "leaked JSON roots"
                return "error: " + str(error)
    """, tmp_path, entry_point="render")
    try:
        shared = [None, True, False, "snow ☃ / 🚢", {"quoted\"": "line\nend"}]
        for value in (
            None, 7, -3.5, float("inf"), "", [], {},
            {"left": shared, "right": shared, "number": 2**53 + 1},
            # Grow the output both incrementally and with a single large leaf.
            [shared] * 180,
            [{str(index): [index, {"label": str(index)}]} for index in range(300)],
            {"payload": "café 🚢\n\"" * 1400, "tail": shared},
        ):
            assert library.render(value) == json.dumps(value, ensure_ascii=ensure_ascii)
        cycle = []
        cycle.append(cycle)
        cycle.extend([shared] * 3)
        assert library.render(cycle) == "error: Circular reference detected"
        mapping = {}
        mapping["self"] = mapping
        mapping["later"] = shared
        assert library.render(mapping) == "error: Circular reference detected"
        assert library.render({"nested": [cycle, shared]}) == "error: Circular reference detected"
        assert library.render(shared) == json.dumps(shared, ensure_ascii=ensure_ascii)
    finally:
        library.close()


def test_recursive_json_mutual_aliases_and_retained_results(tmp_path):
    library = LLVM().compile_library("""
        import json
        from pyjs.native import gc_collect, gc_set_threshold

        type Tree = str | list[Branch]
        type Branch = int | dict[str, Tree]
        SAVED: list[str] = []

        def render(value: Tree) -> str:
            gc_set_threshold(1)
            SAVED.append(json.dumps(value) + "|" + json.dumps(value, ensure_ascii=False))
            gc_collect()
            return "|".join(SAVED)
    """, tmp_path, entry_point="render")
    try:
        value = [{"title": "café" * 1400, "children": [1, {"leaf": "done"}]}]
        first = json.dumps(value) + "|" + json.dumps(value, ensure_ascii=False)
        assert library.render(value) == first
        assert library.render("next") == first + '|"next"|"next"'
    finally:
        library.close()


def test_json_and_html_output_buffers_are_independent():
    comparison = LLVM().assert_matches_python('''
        import json
        from pyjs.web.domx import div
        from pyjs.web.ssr import render_html

        def main() -> str:
            values: list[str | None] = ["café <&>" * 900, None]
            encoded = json.dumps((values, True, 3.5), ensure_ascii=False)
            html = render_html(div(encoded))
            print(json.dumps(None))
            return json.dumps((html, encoded, values))
    ''')
    assert comparison.matches


@pytest.mark.parametrize("check_circular", [False, True])
def test_recursive_json_depth_failure_is_catchable_and_call_local(tmp_path, check_circular):
    library = LLVM().compile_library(f"""
        import json
        from pyjs.native import gc_count

        type JSON = str | list[JSON]

        def render(depth: int) -> str:
            value: JSON = "leaf"
            for _ in range(depth):
                value = [value]
            try:
                return json.dumps(value, check_circular={check_circular})
            except RecursionError:
                return "too deep" if gc_count() == 0 else "leaked JSON roots"
    """, tmp_path, entry_point="render")
    try:
        assert library.render(1000) == "[" * 1000 + '"leaf"' + "]" * 1000
        assert library.render(1001) == "too deep"
        assert library.render(1100) == "too deep"
        assert library.render(3) == '[[["leaf"]]]'
    finally:
        library.close()


def test_recursive_json_options_do_not_share_incompatible_helpers(tmp_path):
    library = LLVM().compile_library('''
        import json

        type JSON = str | float | list[JSON] | dict[str, JSON] | None

        def render(value: JSON) -> str:
            ordinary = json.dumps(value)
            compact = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
            custom = json.dumps(value, separators=(" / ", " → "))
            try:
                strict = json.dumps(value, allow_nan=False, separators=("", ""))
            except ValueError as error:
                if not str(error).startswith("Out of range float values are not JSON compliant"):
                    return "unexpected error"
                strict = "nonfinite"
            return "|".join((ordinary, compact, custom, strict))
    ''', tmp_path, entry_point="render")
    try:
        shared = ["café", None, {"number": 1.25}]
        for value in (
            {"left": shared, "right": shared},
            float("nan"), float("inf"), -float("inf"),
            {"nested": [shared, float("nan"), shared]},
            {"after": [0.0, -0.0, 1e300, "recovered"]},
        ):
            try:
                strict = json.dumps(value, allow_nan=False, separators=("", ""))
            except ValueError:
                strict = "nonfinite"
            expected = "|".join((
                json.dumps(value),
                json.dumps(value, separators=(",", ":"), ensure_ascii=False),
                json.dumps(value, separators=(" / ", " → ")),
                strict,
            ))
            assert library.render(value) == expected
    finally:
        library.close()


def test_json_strict_fixed_tuple_and_option_defaults():
    comparison = LLVM().assert_matches_python('''
        import json

        def main() -> str:
            good = json.dumps((None, -0.0, ["é"]), allow_nan=False, separators=(",", ":"))
            default = json.dumps((True, [1, 2]), separators=None, allow_nan=True)
            try:
                json.dumps((1.0, float("inf"), [2.0]), allow_nan=False)
            except ValueError:
                return good + "|" + default + "|rejected"
            return "missed error"
    ''')
    assert comparison.matches


def test_json_partially_dynamic_separator_tuple_matches_python():
    LLVM().assert_matches_python('''
        import json

        def encode(separator: str) -> str:
            return json.dumps([1.0, 2.0], separators=(separator, ':'))

        def main() -> str:
            return encode(",") + "|" + encode(" / ")
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_dynamic_options_cycles_and_retry(tmp_path, optimize):
    library = LLVM().compile_library('''
        import json
        from pyjs.native import gc_set_threshold
        type JSON = str | float | bool | list[JSON] | dict[str, JSON] | None
        def main(value: JSON, ascii: bool, finite: bool, circular: bool,
                 sort: bool, token: str, separators: tuple[str, str]) -> str:
            gc_set_threshold(1)
            try:
                first = json.dumps(value, ensure_ascii=ascii, allow_nan=finite,
                                   check_circular=circular, sort_keys=sort)
                return first + "|" + json.dumps(value, ensure_ascii=ascii, allow_nan=finite,
                                               check_circular=circular, sort_keys=sort,
                                               indent=token, separators=separators)
            except ValueError:
                return "invalid"
            except RecursionError:
                return "too deep"
    ''', tmp_path, optimize=optimize)
    shared = ["café 🐍", None, {"z": True, "a": -0.0}]
    value = {"right": shared, "left": [shared, {"tail": "done"}]}
    try:
        for ascii in (False, True):
            for sort in (False, True):
                for token, separators in (("", (",", ":")), ("→", (" / ", " : "))):
                    expected = json.dumps(value, ensure_ascii=ascii, sort_keys=sort) + "|" + json.dumps(
                        value, ensure_ascii=ascii, sort_keys=sort, indent=token, separators=separators)
                    assert library.render(value, ascii, True, True, sort, token, separators) == expected
        cycle = {}
        cycle["self"] = [cycle]
        assert library.render(cycle, True, True, True, True, "  ", (",", ":")) == "invalid"
        assert library.render(cycle, True, True, False, True, "  ", (",", ":")) == "too deep"
        assert library.render([shared, float("nan")], True, False, True, True, "", (",", ":")) == "invalid"
        assert library.render(None, True, True, True, True, "", (",", ":")) == "null|null"
    finally:
        library.close()


def test_recursive_optional_tuple_json(tmp_path):
    library = LLVM().compile_library('''
        import json
        type Chain = tuple[int, Chain] | None
        def main(value: Chain) -> str:
            return json.dumps(value, indent=2)
    ''', tmp_path)
    try:
        value = None
        for number in range(20):
            value = number, value
        assert library.render(value) == json.dumps(value, indent=2)
        assert library.render(None) == "null"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_native_construction_and_cleanup_under_sanitizers(optimize):
    comparison = LLVM().assert_matches_python('''
        import json
        from pyjs.native import gc_collect, gc_set_threshold
        type JSON = str | list[JSON] | dict[str, JSON]
        def main() -> str:
            gc_set_threshold(1)
            value: JSON = []
            if isinstance(value, list):
                value.append(value)
            try:
                json.dumps(value)
            except ValueError:
                pass
            value = {"later": ["é", {"again": "ok"}]}
            result = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2)
            gc_collect()
            return result + "|" + json.dumps(value)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_pending_frame_allocation_failure_recovers(tmp_path, optimize):
    source = '''
        import json
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm
        type Tree = str | list[Tree]
        def main() -> int:
            gc_set_threshold(1)
            value: Tree = "é" * 5000
            for _ in range(80):
                value = [value]
            expected = json.dumps(value, indent=1)
            failures = 0
            for attempt in range(1, 160):
                complete = False
                try:
                    arm(attempt)
                    result = json.dumps(value, indent=1)
                    arm(0)
                    assert result == expected
                    complete = True
                except MemoryError:
                    arm(0)
                    failures += 1
                finally:
                    arm(0)
                gc_collect()
                assert json.dumps(value, indent=1) == expected
                if complete:
                    return 0 if failures else 1
            return 2
    '''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=True, optimize=optimize)
