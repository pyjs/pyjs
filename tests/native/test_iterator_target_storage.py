import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_reused_iterator_targets_keep_tagged_storage_and_source_types(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int):
                self.value = value

        def describe(value: Box | str) -> str:
            gc_collect()
            if isinstance(value, str):
                return value
            return str(value.value)

        def main() -> int:
            gc_set_threshold(1)
            for item in [Box(1)]:
                print(item.value)
            mixed: list[Box | str] = [Box(2), "text"]
            for item in mixed:
                print(describe(item))
            for item in [Box(3)]:
                gc_collect()
                print(item.value)

            for number in [1, 2]:
                print(number + 1)
            numbers: list[int | str] = [3, "four"]
            for number in numbers:
                gc_collect()
                print(number)
            for number in [5]:
                print(number + 1)

            for label, (left, right) in [("first", (Box(6), Box(7)))]:
                print(label, left.value, right.value)
            pairs: list[tuple[str, tuple[Box | str, Box | str]]] = [
                ("second", (Box(8), "missing")),
                ("third", ("missing", Box(9))),
            ]
            for label, (left, right) in pairs:
                print(label, describe(left), describe(right))
            return 0
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_reused_tuple_targets_use_each_loops_layout(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int):
                self.value = value

        def main() -> int:
            gc_set_threshold(1)
            for row in [(1, 2)]:
                gc_collect()
                print(row[0] + row[1])
            for row in [(Box(3), Box(4))]:
                gc_collect()
                print(row[0].value + row[1].value)
            for label, row in [("nested", (5, 6))]:
                gc_collect()
                print(label, row[0] + row[1])
            for label, row in [("nested objects", (Box(7), Box(8)))]:
                gc_collect()
                print(label, row[0].value + row[1].value)
            for row in [(9, 10)]:
                gc_collect()
                print(row[0] + row[1])
            return 0
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_declared_loop_slots_keep_boxing_and_zero_iteration_values(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            results: list[str] = []
            value: object = "initial"
            empty: list[int] = []
            for value in empty:
                raise AssertionError()
            results.append(repr(value))
            for value in [3]:
                gc_collect()
                results.append(repr(value))
            for value in ["four"]:
                gc_collect()
                results.append(repr(value))
            results.append(repr(value))
            for value in [5]:
                gc_collect()
                results.append(repr(value))
            results.append(repr(value))
            pair: object = "before"
            for label, pair in [("tuple", (6, 7))]:
                gc_collect()
                results.append(label + repr(pair))
            results.append(repr(pair))
            return repr(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_reused_loop_slots_keep_branch_and_break_values(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def run(choose: bool) -> str:
            result: list[str] = []
            values: list[int | str] = ["start", 2]
            for item in values:
                result.append(repr(item))
            if choose:
                for item in [3, 4]:
                    gc_collect()
                    result.append(repr(item))
                    break
            else:
                for item in ["end"]:
                    gc_collect()
                    result.append(repr(item))
            result.append(repr(item))
            return repr(result)

        def main() -> str:
            gc_set_threshold(1)
            return run(True) + run(False)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
