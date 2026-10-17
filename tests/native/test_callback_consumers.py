import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_callback_consumers(optimize):
    LLVM().assert_matches_python('''
        from functools import reduce

        def key(value: int) -> int:
            return -value

        def add(left: int, right: int) -> int:
            return left + right

        def main() -> int:
            values = [3, 1, 2]
            values.sort(key=key)
            assert values[0] == 3
            assert min(values, key=key) == 3
            assert max(values, key=key) == 1
            assert min(1, 3, 2, key=key) == 3
            assert reduce(add, values) == 6
            return reduce(add, values, initial=4)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("reverse", [False, True])
def test_in_place_keys_see_empty_list_and_sort_stably(optimize, reverse):
    LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        class Row:
            def __init__(self, group: int, name: str):
                self.group = group
                self.name = name

        class Recorder:
            def __init__(self, rows: list[Row], events: list[str]):
                self.rows = rows
                self.events = events

            def key(self, row: Row) -> str:
                assert len(self.rows) == 0
                self.rows.reverse()
                self.events.append(row.name)
                gc_collect()
                return "group:" + str(row.group)

        def main() -> str:
            gc_set_threshold(1)
            rows = [Row(2, "a"), Row(1, "b"), Row(2, "c"), Row(1, "d")]
            alias = rows
            events: list[str] = []
            rows.sort(key=Recorder(rows, events).key, reverse={reverse})
            assert rows is alias
            assert "".join(events) == "abcd"
            gc_collect()
            return rows[0].name + rows[1].name + rows[2].name + rows[3].name
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("mutate, fail", [(False, True), (True, False), (True, True)])
def test_in_place_sort_restores_on_mutation_and_key_failure(optimize, mutate, fail):
    LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, values: list[str]):
                self.values = values
                self.events: list[str] = []
                self.mutate = {mutate}
                self.fail = {fail}

            def key(self, value: str) -> str:
                self.events.append(value)
                assert len(self.values) == 0
                if self.mutate:
                    self.values.append("temporary")
                    self.values.clear()
                gc_collect()
                if self.fail and value == "b":
                    raise RuntimeError("key failed")
                return value

        def main() -> str:
            gc_set_threshold(1)
            values = ["c", "b", "a"]
            alias = values
            key = Key(values)
            error = ""
            try:
                values.sort(key=key.key)
            except ValueError as caught:
                error = str(caught)
            except RuntimeError as caught:
                error = str(caught)
            gc_collect()
            assert values is alias and len(values) == 3
            state = "".join(values) + ":" + "".join(key.events) + ":" + error
            key.mutate = False
            key.fail = False
            values.sort(key=key.key)
            assert "".join(values) == "abc"
            return state
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_extrema_keys_retain_winners_and_current_items(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Row:
            def __init__(self, group: int, name: str):
                self.group = group
                self.name = name

        class Key:
            def __init__(self, source: list[Row], clear: bool):
                self.source = source
                self.clear = clear
                self.events: list[str] = []

            def key(self, row: Row) -> str:
                self.events.append(row.name)
                if self.clear:
                    self.source.clear()
                gc_collect()
                return "group:" + str(row.group)

        def main() -> str:
            gc_set_threshold(1)
            source = [Row(1, "a"), Row(1, "b"), Row(2, "c")]
            recorder = Key(source, False)
            winner = min(iter(source), key=recorder.key)
            assert winner is source[0]
            assert "".join(recorder.events) == "abc"
            recorder.events.clear()
            recorder.clear = True
            winner = max(source[0], source[1], source[2], key=recorder.key)
            assert len(source) == 0 and winner.name == "c"
            assert "".join(recorder.events) == "abc"
            recorder.events.clear()
            fallback = Row(9, "fallback")
            assert min(source, key=recorder.key, default=fallback) is fallback
            assert len(recorder.events) == 0
            source.append(Row(0, "last"))
            winner = min(source, key=recorder.key)
            gc_collect()
            return winner.name
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_reduce_distinct_accumulator_and_item_types_under_gc(optimize):
    LLVM().assert_matches_python('''
        from functools import reduce
        from pyjs.native import gc_collect, gc_set_threshold

        class Reducer:
            def __init__(self, source: list[str]):
                self.source = source

            def combine(self, result: list[str], item: str) -> list[str]:
                self.source.clear()
                gc_collect()
                result.append(item + "!")
                return result

        def add(left: str, right: str) -> str:
            gc_collect()
            return left + right

        def main() -> str:
            gc_set_threshold(1)
            source = ["a", "b", "c"]
            initial: list[str] = []
            result = reduce(Reducer(source).combine, iter(source), initial)
            assert result is initial
            assert len(source) == 0 and len(result) == 1
            empty: list[str] = []
            assert reduce(add, empty, initial="seed") == "seed"
            caught = False
            try:
                reduce(add, empty)
            except TypeError as error:
                caught = str(error) == "reduce() of empty iterable with no initial value"
            assert caught
            return result[0] + reduce(add, ["x", "y", "z"])
    ''', optimize=optimize)


@pytest.mark.parametrize("numeric", ["int8", "int64", "float32"])
def test_reduce_and_extrema_preserve_portable_representations(numeric):
    LLVM().assert_matches_python(f'''
        from functools import reduce
        from pyjs import {numeric}

        def add(left: {numeric}, right: {numeric}) -> {numeric}:
            return left + right

        def key(value: {numeric}) -> {numeric}:
            return -value

        def main() -> str:
            values = [{numeric}(120), {numeric}(20), {numeric}(1)]
            values.sort(key=key)
            total = reduce(add, iter(values), {numeric}(0))
            assert reduce(add, (), {numeric}(7)) == {numeric}(7)
            return str(total) + ":" + str(min(values, key=key)) + ":" + str(max(values, key=key))
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_callback_failures_leave_iterator_consumption_visible(optimize):
    LLVM().assert_matches_python('''
        from functools import reduce
        from pyjs.native import gc_collect, gc_set_threshold

        def key(value: int) -> int:
            gc_collect()
            if value == 2:
                raise ValueError("key failed")
            return value

        def add(left: int, right: int) -> int:
            gc_collect()
            if right == 2:
                raise ValueError("reducer failed")
            return left + right

        def main() -> int:
            gc_set_threshold(1)
            cursor = iter([1, 2, 3, 4])
            caught = False
            try:
                min(cursor, key=key)
            except ValueError:
                caught = True
            assert caught and next(cursor) == 3
            assert max(cursor, key=key) == 4
            cursor = iter([1, 2, 3, 4])
            caught = False
            try:
                reduce(add, cursor)
            except ValueError:
                caught = True
            assert caught and next(cursor) == 3
            assert reduce(add, cursor, initial=10) == 14
            gc_collect()
            return 0
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_sort_and_reduction_restore_enclosing_roots(optimize):
    LLVM().assert_matches_python('''
        from functools import reduce
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, values: list[str]):
                self.values = values

            def key(self, value: str) -> str:
                self.values.sort(key=self.key)
                inner = ["x", "y"]
                caught = False
                try:
                    inner.sort(key=self.fail)
                except ValueError:
                    caught = True
                assert caught and inner[0] == "x"
                gc_collect()
                return value

            def fail(self, value: str) -> str:
                raise ValueError("inner")

        def append(left: str, right: str) -> str:
            gc_collect()
            return left + right

        def combine(left: str, right: str) -> str:
            return reduce(append, [left, right])

        def main() -> str:
            gc_set_threshold(1)
            values = ["b", "a"]
            values.sort(key=Key(values).key)
            return reduce(combine, values, "prefix:")
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_sort_and_reducer_allocation_failures_are_recoverable(optimize, tmp_path):
    from tests.native.allocation_support import run_allocation_case

    llvm_ir = transpile_llvm('''
        from functools import reduce
        from tests.native.allocation_support import arm, remaining
        from pyjs.native import gc_collect, gc_set_threshold

        def key(value: str) -> str:
            gc_collect()
            return "key:" + value

        def combine(left: str, right: str) -> str:
            gc_collect()
            return left + right

        def main() -> int:
            gc_set_threshold(1)
            attempt = 1
            caught = 0
            while attempt < 150:
                values = ["c", "b", "a"]
                alias = values
                arm(attempt)
                succeeded = False
                try:
                    values.sort(key=key)
                    best = min(values, key=key)
                    joined = reduce(combine, iter(values), "")
                    succeeded = True
                except MemoryError:
                    caught += 1
                exhausted = remaining() == 0
                arm(0)
                assert values is alias and len(values) == 3
                assert "a" in values and "b" in values and "c" in values
                gc_collect()
                if succeeded:
                    assert values[0] == "a" and best == "a" and joined == "abc"
                if not exhausted:
                    assert succeeded and caught > 0
                    return 0
                attempt += 1
            return 1
    ''')
    run_allocation_case(llvm_ir, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("expression", [
    "reduce(add, [int8(1)], 0)",
    "min([1, 2], key=key)",
    "values.sort(key=key)",
])
def test_callback_consumers_reject_representation_mismatches(expression):
    with pytest.raises(CompilationError, match="incompatible representations"):
        transpile_llvm(f'''
            from functools import reduce
            from pyjs import int8

            def add(left: int8, right: int8) -> int8:
                return left + right

            def key(value: int8) -> int8:
                return value

            def main() -> int:
                values = [1, 2]
                {expression}
                return 0
        ''')


def test_key_none_aliases_and_empty_singleton_callbacks():
    LLVM().assert_matches_python('''
        from functools import reduce as fold

        def fail(left: int, right: int) -> int:
            raise ValueError("not called")

        def key(value: int) -> int:
            raise ValueError("not called")

        def main() -> int:
            values = [3, 1, 2]
            values.sort(key=None)
            assert values[0] == 1
            assert min(values, key=None) == 1 and max(values, key=None) == 3
            assert fold(fail, [7]) == 7
            assert fold(fail, (), 10) == 10
            assert min((), key=key, default=42) == 42
            return 0
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_reduce_none_accumulator_preserves_callback_effects(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from functools import reduce
        from pyjs.native import gc_collect

        def consume(accumulator: None, item: int) -> None:
            assert accumulator is None
            gc_collect()

        class Recorder:
            def __init__(self, events: list[int]):
                self.events = events
            def consume(self, accumulator: None, item: int) -> None:
                assert accumulator is None
                gc_collect()
                self.events.append(item)

        def main() -> str:
            events: list[int] = []
            assert reduce(consume, [1, 2], None) is None
            assert reduce(Recorder(events).consume, [3, 4], None) is None
            assert reduce(Recorder(events).consume, (), None) is None
            return repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_reduce_concrete_iterable_sources(optimize):
    LLVM().assert_matches_python('''
        from functools import reduce

        def text(left: str, right: str) -> str:
            return left + ":" + right

        def add(left: int, right: int) -> int:
            return left + right

        def item(left: str, right: tuple[str, int]) -> str:
            return left + right[0] + str(right[1])

        def main() -> str:
            assert reduce(add, b"abc", 0) == 294
            assert reduce(add, range(4), 0) == 6
            assert reduce(add, {1, 2, 3}, 0) == 6
            assert reduce(add, (1, 2, 3), 0) == 6
            rows = {"a": 1, "b": 2}
            assert reduce(item, rows.items(), "") == "a1b2"
            return reduce(text, "é🦆a")
    ''', optimize=optimize)
