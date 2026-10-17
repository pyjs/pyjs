import pytest

from pyjs.native.errors import LLVMUnsupported
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_reduce_numeric_union_preserves_empty_start_and_float_transition(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable
        from functools import reduce
        def multiply(left: int | float, right: float) -> int | float:
            if isinstance(left, int): return left * right
            return left * right
        def product(values: Iterable[float], start: int | float) -> int | float:
            return reduce(multiply, values, start)
        def main() -> str:
            empty: list[float] = []
            return repr((product(empty, 1), product([0.5, 1.0, 1.5], 2),
                         product(empty, 2.0), product([2.0, 3.0], 1.0),
                         reduce(multiply, empty, 1), reduce(multiply, [2.0, 3.0], initial=2)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_reduce_concrete_callback_result_widens_to_accumulator(optimize):
    result = LLVM().assert_matches_python('''
        from functools import reduce
        from pyjs.native import gc_collect
        class Box:
            def __init__(self, value: int): self.value = value
        def combine(left: int | Box, right: int | Box) -> Box:
            gc_collect()
            lhs = left if isinstance(left, int) else left.value
            rhs = right if isinstance(right, int) else right.value
            return Box(lhs + rhs)
        def main() -> str:
            empty: list[int] = []
            values = reduce(combine, [1, 2], 0)
            return repr((reduce(combine, empty, 0),
                         values.value if isinstance(values, Box) else -1,
                         reduce(combine, [1])))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_reduce_union_items_nullable_results_and_no_initial(optimize):
    result = LLVM().assert_matches_python('''
        from functools import reduce
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, value: int): self.value = value
        def combine(left: int | Box, right: int | Box) -> int | Box:
            gc_collect()
            lhs = left if isinstance(left, int) else left.value
            rhs = right if isinstance(right, int) else right.value
            return Box(lhs + rhs)
        def maybe(left: Box | None, right: int) -> Box | None:
            gc_collect()
            if left is None: return Box(right)
            return None
        def number(left: int | None, right: int) -> int | None:
            if left is None: return right
            return None
        def show(value: int | Box) -> int:
            if isinstance(value, int): return int(value)
            return value.value
        def main() -> str:
            gc_set_threshold(1)
            values: list[int | Box] = [1, Box(2), 3]
            empty: list[int | Box] = []
            ints: list[int] = []
            original = Box(8)
            singleton: list[int | Box] = [original]
            saved = reduce(combine, singleton)
            assert saved is original
            caught = False
            try: reduce(combine, empty)
            except TypeError: caught = True
            first = reduce(combine, values)
            widened = reduce(combine, [1, 2, 3], Box(4))
            unseeded = reduce(combine, [1, 2, 3])
            only_bool = reduce(combine, [True])
            assert only_bool is True
            absent = reduce(maybe, ints, None)
            present = reduce(maybe, [5], None)
            assert present is not None
            cleared = reduce(maybe, [1, 2], initial=None)
            return repr((show(saved), show(first), show(widened), show(unseeded), caught,
                         absent is None, present.value if isinstance(present, Box) else -1,
                         cleared is None, reduce(number, ints, None),
                         reduce(number, [0], None), reduce(number, [0, 1], None),
                         reduce(number, ints, 0)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("items, annotation", [("[1]", "float"), ("[True]", "int")])
def test_reduce_without_initial_does_not_promote_the_first_item(items, annotation):
    with pytest.raises(LLVMUnsupported, match="use an explicit numeric conversion"):
        transpile_llvm(f'''
            from functools import reduce
            def combine(left: {annotation}, right: {annotation}) -> {annotation}:
                return left + right
            def main() -> str:
                return repr(reduce(combine, {items}))
        ''')


@pytest.mark.parametrize("initial", ["source()", "initial=source()"])
def test_reduce_union_initial_does_not_reinterpret_mutable_storage(initial):
    with pytest.raises(LLVMUnsupported, match="collection views require.*invariant"):
        transpile_llvm(f'''
            from functools import reduce
            def source() -> list[bool]:
                return [True]
            def combine(left: list[int] | str, right: int) -> list[int] | str:
                if isinstance(left, str): return left + str(right)
                left.append(right)
                return left
            def main() -> str:
                return repr(reduce(combine, [2], {initial}))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_reduce_widened_items_survive_source_mutation(optimize):
    result = LLVM().assert_matches_python('''
        from functools import reduce
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, value: int): self.value = value
        class Reducer:
            def __init__(self): self.items: list[Box] = [Box(2), Box(3)]
            def combine(self, left: int | Box, right: int | Box) -> int | Box:
                self.items.clear()
                gc_collect()
                lhs = left if isinstance(left, int) else left.value
                rhs = right if isinstance(right, int) else right.value
                return Box(lhs + rhs)
        def main() -> str:
            gc_set_threshold(1)
            first, second = Reducer(), Reducer()
            seeded = reduce(first.combine, first.items, Box(4))
            unseeded = reduce(second.combine, second.items)
            gc_collect()
            return repr((seeded.value if isinstance(seeded, Box) else -1,
                         unseeded.value if isinstance(unseeded, Box) else -1,
                         len(first.items), len(second.items)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_reduce_union_allocation_failure_recovers_roots(optimize, tmp_path):
    from tests.native.allocation_support import run_allocation_case

    source = transpile_llvm('''
        from functools import reduce
        from tests.native.allocation_support import arm, remaining
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, value: int): self.value = value
        def combine(left: int | Box, right: int | Box) -> int | Box:
            gc_collect()
            lhs = left if isinstance(left, int) else left.value
            rhs = right if isinstance(right, int) else right.value
            return Box(lhs + rhs)
        def main() -> int:
            gc_set_threshold(1)
            caught = 0
            for attempt in range(1, 100):
                values: list[int | Box] = [1, Box(2), 3]
                original = Box(4)
                arm(attempt)
                succeeded = False
                try:
                    result = reduce(combine, iter(values), original)
                    assert isinstance(result, Box) and result.value == 10
                    succeeded = True
                except MemoryError:
                    caught += 1
                exhausted = remaining() == 0
                arm(0)
                gc_collect()
                assert original.value == 4 and len(values) == 3
                recovered = reduce(combine, values, original)
                assert isinstance(recovered, Box) and recovered.value == 10
                if not exhausted:
                    assert succeeded and caught > 0
                    return 0
            return 1
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_reduce_managed_union_transitions_roots_exceptions_and_empty_identity(optimize):
    result = LLVM().assert_matches_python('''
        from functools import reduce
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, value: int): self.value = value
        def combine(left: int | Box, right: int) -> int | Box:
            gc_collect()
            if right < 0: raise ValueError("stop")
            if isinstance(left, int): return Box(left + right)
            return left.value + right
        def show(value: int | Box) -> str:
            if isinstance(value, int): return "int:" + str(value)
            return "box:" + str(value.value)
        def main() -> str:
            gc_set_threshold(1)
            empty: list[int] = []
            value = Box(4)
            saved = reduce(combine, empty, value)
            assert saved is value
            first = reduce(combine, [1, 2, 3], 0)
            second = reduce(combine, iter([1, 2, 3]), initial=Box(4))
            cursor = iter([1, -1, 9])
            message = ""
            try: reduce(combine, cursor, Box(5))
            except ValueError as error: message = str(error)
            remaining = next(cursor)
            gc_collect()
            recovered = reduce(combine, [4, 5], Box(6))
            return repr((show(saved), show(first), show(second), message, remaining, show(recovered)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
