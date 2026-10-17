import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("reverse", [False, True])
def test_keyed_object_sort_is_stable_and_retains_receivers(optimize, reverse):
    LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        class Row:
            def __init__(self, key: int, name: str):
                self.key = key
                self.name = name

        class Recorder:
            def __init__(self, events: list[str]):
                self.events = events

            def key(self, row: Row) -> str:
                self.events.append(row.name)
                gc_collect()
                return "key:" + str(row.key)

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            rows = [Row(2, "a"), Row(1, "b"), Row(2, "c"), Row(1, "d")]
            result = sorted(iter(rows), key=Recorder(events).key, reverse={reverse})
            assert result is not rows
            gc_collect()
            names: list[str] = []
            for row in result:
                names.append(row.name)
            assert "".join(events) == "abcd"
            assert rows[0].name == "a"
            return "".join(names)
    ''', optimize=optimize)


@pytest.mark.parametrize("return_type, expression", [
    ("bool", "value % 2 == 0"),
    ("int", "-value"),
    ("float", "float(value % 3)"),
    ("str", '"prefix:" + str(value % 3)'),
    ("bytes", 'b"a" if value % 3 == 0 else b"b"'),
    ("int8", "int8(value % 3)"),
    ("float32", "float32(value % 3)"),
])
def test_key_return_storage_and_empty_input(return_type, expression):
    LLVM().assert_matches_python(f'''
        from pyjs import int8, float32

        def key(value: int) -> {return_type}:
            return {expression}

        def main() -> str:
            values = [3, 1, 4, 2, 5]
            empty: list[int] = []
            assert len(sorted(empty, key=key)) == 0
            assert sorted((7,), key=key)[0] == 7
            parts: list[str] = []
            for value in sorted(values, key=key, reverse=True):
                parts.append(str(value))
            return ",".join(parts)
    ''')


def test_sorted_snapshots_before_keys_mutate_input_and_propagates_failures():
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Mutator:
            def __init__(self, values: list[int], events: list[int]):
                self.values = values
                self.events = events
                self.fail = False

            def key(self, value: int) -> int:
                self.events.append(value)
                self.values.clear()
                gc_collect()
                if self.fail and value == 1:
                    raise ValueError("key failed")
                return -value

        def main() -> str:
            gc_set_threshold(1)
            values = [3, 1, 2]
            events: list[int] = []
            mutator = Mutator(values, events)
            result = sorted(iter(values), key=mutator.key)
            assert len(values) == 0
            assert len(events) == 3
            assert events[0] == 3 and events[1] == 1 and events[2] == 2
            events.clear()
            mutator.fail = True
            caught = False
            try:
                sorted([3, 1, 2], key=mutator.key)
            except ValueError as error:
                caught = str(error) == "key failed"
            assert caught and len(events) == 2
            gc_collect()
            mutator.fail = False
            retry = sorted(result, key=mutator.key)
            return str(retry[0]) + str(retry[1]) + str(retry[2])
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_key_result_uses_structural_ordering(optimize):
    LLVM().assert_matches_python('''
        def key(value: int) -> tuple[int, int]:
            return (value % 2, -(value % 3))
        def main() -> str:
            values = [7, 2, 5, 4, 1, 8]
            parts: list[str] = []
            for value in sorted(values, key=key):
                parts.append(str(value))
            parts.append("/")
            for value in sorted(values, key=key, reverse=True):
                parts.append(str(value))
            return ",".join(parts)
    ''', optimize=optimize)


@pytest.mark.parametrize("item_type, parameter", [("int", "int8"), ("int8", "int")])
def test_key_parameter_cannot_silently_change_item_representation(item_type, parameter):
    with pytest.raises(CompilationError, match="incompatible representations"):
        transpile_llvm(f'''
            from pyjs import int8

            def key(value: {parameter}) -> int:
                return int(value)

            def main() -> int:
                return int(sorted([{item_type}(257)], key=key)[0])
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_keyed_sort_allocation_failure_sweep_preserves_input(optimize, tmp_path):
    from tests.native.allocation_support import run_allocation_case

    source = transpile_llvm('''
        from tests.native.allocation_support import arm, remaining
        from pyjs.native import gc_collect, gc_set_threshold

        def key(value: int) -> str:
            gc_collect()
            return "prefix:" + str(value % 3)

        def main() -> int:
            gc_set_threshold(1)
            values = [3, 1, 4, 2, 5]
            attempt = 1
            caught = 0
            while attempt < 100:
                arm(attempt)
                succeeded = False
                try:
                    result = sorted(values, key=key)
                    succeeded = True
                except MemoryError:
                    caught += 1
                exhausted = remaining() == 0
                arm(0)
                assert len(values) == 5 and values[0] == 3 and values[4] == 5
                gc_collect()
                if succeeded:
                    assert len(result) == 5
                    assert result[0] == 3 and result[1] == 1 and result[2] == 4
                if not exhausted:
                    assert succeeded and caught > 0
                    return 0
                attempt += 1
            return 1
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
