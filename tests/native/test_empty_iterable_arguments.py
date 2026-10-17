import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import ITERABLE_LITERAL_CONTEXT_CONTRACT


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", ["rows.extend(LITERAL)", "rows[0:0] = LITERAL"])
@pytest.mark.parametrize("literal", ["[[], [[]], [[int8(3)]]]", "([], [[]], [[int8(3)]])"])
def test_receiver_context_retains_width_in_empty_only_descendants(tmp_path, optimize, operation, literal):
    result = LLVM().assert_matches_python(f'''
        from pyjs import int8
        from pyjs.native import gc_collect
        def main() -> str:
            rows: list[list[list[int8]]] = []
            {operation.replace('LITERAL', literal)}
            output = ''
            for group in rows:
                group.append([int8(127)])
                for row in group:
                    row.append(int8(127))
                    gc_collect()
                    output += str(row[-1] + 1) + ':'
            return output
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_iterable_literal_context_contract(optimize):
    result = LLVM().assert_matches_python(
        ITERABLE_LITERAL_CONTEXT_CONTRACT.source, optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert result.native.returncode == 0, ITERABLE_LITERAL_CONTEXT_CONTRACT.failure(result.native.returncode)
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("literal", ["[[], [[]], [[9]]]", "([], [[]], [[9]])"])
def test_static_slice_replacement_infers_nested_empty_members(optimize, literal):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> str:
            gc_set_threshold(1)
            values: list[list[list[int]]] = [[[1]], [[2]]]
            values[0:1] = {literal}
            gc_collect()
            values[0].append([3])
            values[1][0].append(4)
            return repr(values)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == '[[[3]], [[4]], [[9]], [[2]]]'
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_static_slice_receiver_keeps_represented_empty_sibling_storage(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8
        from pyjs.native import gc_collect
        def main() -> str:
            rows: list[list[int8]] = []
            rows[0:0] = [[], [int8(3)]]
            rows[0:0] = [[int8(3)], []]
            rows[0:0] = ([], [int8(3)])
            rows[0:0] = ([int8(3)], [])
            rows[0:0] = [[], []]
            result = ''
            for row in rows:
                row.append(int8(127))
                gc_collect()
                result += str(row[-1] + 1) + ':'
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == '-128:' * 10
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["Iterable[list[int8]]", "list[list[int8]]"])
def test_fresh_populated_siblings_convert_slots_without_changing_source(optimize, annotation):
    result = LLVM().run_source(f'''
        from collections.abc import Iterable
        from pyjs import int8
        def consume(rows: {annotation}) -> str:
            result = ''
            for row in rows:
                for item in row:
                    result += str(item) + ':' + str(item + 1)
            return result
        def main() -> str:
            value = 200
            return consume([[], [value]]) + '|' + consume([[value], []]) + '|' + str(value + 1)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    # CPython ignores annotations. Check the compiled fresh-slot conversion
    # contract against explicit arithmetic, including the unchanged source.
    assert result.returncode == 0
    assert not result.stderr
    assert result.stdout == '-56:-55|-56:-55|201'


@pytest.mark.parametrize("item", ["str", "int8", "float32", "list[int]", "Iterable[str]"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_fresh_empty_list_uses_iterable_item_context(tmp_path, item, optimize):
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Callable, Iterable
        from pyjs import int8, float32
        from pyjs.native import gc_collect, gc_set_threshold
        def consume(values: Iterable[{item}]) -> str:
            gc_collect()
            return str(bool(values)) + str(len(list(values))) + str(len(list(values)))
        def produce() -> Iterable[{item}]:
            return []
        def main() -> str:
            gc_set_threshold(1)
            callback: Callable[[Iterable[{item}]], str] = consume
            value: Iterable[{item}] = []
            return consume([]) + consume(values=[]) + callback([]) + consume(produce()) + consume(value)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "False00" * 5
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_empty_and_populated_iterables_keep_reuse_and_source_truth(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable
        def consume(values: Iterable[str]) -> str:
            result = str(bool(values))
            for value in values:
                result += value
            for value in values:
                result += value
            return result + "|".join(values)
        def main() -> str:
            empty: dict[str, int] = {}
            return (consume(["a", "b"]) + consume(("c", "d")) + consume(())
                    + consume("é😀") + consume({"x": 1, "y": 2})
                    + consume({"z": 1}.keys()) + consume(iter(["once"]))
                    + consume([]) + consume(empty) + consume(empty.keys())
                    + consume({"set"}) + consume(frozenset(["frozen"])))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_aliased_untyped_list_does_not_acquire_a_destination_layout():
    with pytest.raises(CompilationError, match="Type of 'values' cannot be inferred"):
        transpile_llvm('''
            from collections.abc import Iterable
            def consume(values: Iterable[int]) -> int:
                return sum(values)
            def main() -> int:
                values = []
                return consume(values)
        ''')
