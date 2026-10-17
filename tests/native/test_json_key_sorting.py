import json
import random

import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("collect", [False, True])
def test_sorting_borrowed_recursive_graphs_and_cycle_recovery(tmp_path, optimize, collect):
    source = '''
        import json
        from pyjs.native import gc_collect, gc_set_threshold
        type JSON = str | int | list[JSON] | dict[str, JSON]
        def render(value: JSON, ordered: bool) -> str:
            COLLECT
            try:
                return json.dumps(value, sort_keys=ordered, ensure_ascii=False, indent=1)
            except ValueError:
                return "cycle"
    '''.replace("COLLECT", "gc_set_threshold(1); gc_collect()" if collect else "pass")
    library = LLVM().compile_library(source, tmp_path, entry_point="render", optimize=optimize)
    randomizer = random.Random(714)
    names = ["", "a", "aa", "a\x00", '"', "\\", "é", "雪", "😀", *(str(index) for index in range(24))]
    try:
        assert library.managed is collect
        for length in range(len(names) + 1):
            keys = names[:length]
            randomizer.shuffle(keys)
            child = {key: index for index, key in enumerate(keys)}
            shared = {"z": child, "a": [child, {}, child]}
            for value in (child, shared, [shared, child]):
                original = json.dumps(value)
                for ordered in (True, False):
                    assert library.render(value, ordered) == json.dumps(
                        value, sort_keys=ordered, ensure_ascii=False, indent=1)
                    assert json.dumps(value) == original
        cycle = {"z": 1}
        cycle["a"] = cycle
        assert library.render(cycle, True) == "cycle"
        assert library.render({"z": 2, "a": 1}, True) == json.dumps(
            {"z": 2, "a": 1}, sort_keys=True, ensure_ascii=False, indent=1)
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("key_type", ["float", "float | None", "float | int"])
def test_nan_key_values_keep_their_source_position(tmp_path, optimize, key_type):
    comparison = LLVM().assert_matches_python(f'''
        import json
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            first: dict[{key_type}, list[str]] = {{float("nan"): ["first"], 2.0: ["second"]}}
            second: dict[{key_type}, list[str]] = {{float("nan"): ["third"], 1.0: ["fourth"]}}
            output = json.dumps(first, sort_keys=True)
            for enabled in (False, True, False):
                output += json.dumps([first, second, first], sort_keys=enabled, indent=1)
                try:
                    json.dumps(first, sort_keys=enabled, allow_nan=False)
                except ValueError:
                    output += "|strict"
                gc_collect()
                output += json.dumps(second, sort_keys=enabled)
            return output
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_json_sorts_nested_keys_without_mutating_borrowed_inputs(tmp_path, optimize):
    LLVM().assert_matches_python('''
        import json
        from pyjs.native import gc_collect, gc_set_threshold

        type JSON = str | list[JSON] | dict[str, JSON]

        def main() -> str:
            gc_set_threshold(1)
            child: dict[str, JSON] = {"é": "accent", "a": "first", "😀": "last"}
            value: dict[str, JSON] = {"z": child, "a": [child, {}, child]}
            before = json.dumps(value)
            outputs: list[str] = []
            for ordered in [False, True, True, False]:
                outputs.append(json.dumps(value, sort_keys=ordered, indent=2,
                                          ensure_ascii=False))
                gc_collect()
                if json.dumps(value) != before:
                    return "input was reordered"
            outputs.append(json.dumps(value, sort_keys=True, separators=(";", "=")))
            return json.dumps(outputs)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_json_orders_numeric_keys_without_losing_integer_precision(tmp_path, optimize):
    LLVM().assert_matches_python('''
        import json
        from pyjs import int64, float32

        def main() -> str:
            numeric: dict[int | float | bool, str] = {
                9007199254740993: "wide", 9007199254740992.0: "rounded",
                -2: "negative", 0.25: "fraction", True: "boolean",
                float("inf"): "infinity", float("-inf"): "negative infinity",
            }
            wide = {int64(9007199254740995): "second",
                    int64(9007199254740993): "first"}
            small = {float32(0.3): "third", float32(0.1): "first"}
            optional: dict[int | None, str] = {9: "last", 1: "first"}
            flags = {True: "true", False: "false"}
            empty: dict[str, str] = {}
            null: dict[None, str] = {None: "only"}
            return json.dumps([
                json.dumps(numeric, sort_keys=True),
                json.dumps(wide, sort_keys=True),
                json.dumps(small, sort_keys=True),
                json.dumps(optional, sort_keys=True),
                json.dumps(flags, sort_keys=True),
                json.dumps(empty, sort_keys=True),
                json.dumps(null, sort_keys=True),
            ])
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_json_sort_errors_precede_value_traversal_and_recover(tmp_path, optimize):
    LLVM().assert_matches_python('''
        import json
        from pyjs.native import gc_collect

        type JSON = str | list[JSON]

        def main() -> str:
            cycle: list[JSON] = []
            cycle.append(cycle)
            mixed: dict[str | int | None, JSON] = {"first": cycle, 2: "second"}
            nullable: dict[str | int | None, JSON] = {"first": cycle, None: "second"}
            outputs: list[str] = []
            for skip in [False, True]:
                for value in [mixed, nullable]:
                    try:
                        json.dumps(value, sort_keys=True, skipkeys=skip)
                        outputs.append("missing failure")
                    except TypeError:
                        outputs.append("ordering error")
                    except ValueError:
                        outputs.append("visited cycle before sorting")
                    gc_collect()
                    outputs.append(json.dumps({"z": 2, "a": 1}, sort_keys=True))
            skipped = {b"z": cycle, b"a": cycle}
            outputs.append(json.dumps(skipped, sort_keys=True, skipkeys=True, indent=2))
            return json.dumps(outputs)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_sorted_tuple_keys_are_compared_before_skipkeys(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        import json
        def main() -> str:
            values = {(2, 1): "skipped", (1, 2): "also skipped"}
            incompatible: dict[tuple[int, int] | str, str] = {(2, 1): "tuple", "s": "string"}
            output = json.dumps(values, skipkeys=True)
            output += json.dumps(values, sort_keys=True, skipkeys=True)
            output += json.dumps(incompatible, skipkeys=True)
            try:
                json.dumps(incompatible, sort_keys=True, skipkeys=True)
            except TypeError:
                output += "|ordering before skipping"
            return output + json.dumps(values, sort_keys=True, skipkeys=True)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
