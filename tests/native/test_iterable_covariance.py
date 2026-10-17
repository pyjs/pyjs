import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize('optimize', [0, 2])
def test_refined_tuple_cursor_is_ready_before_iterable_view_emission(optimize):
    # Keep this standalone: a float-list use elsewhere in the same program can
    # incidentally instantiate Iterator[float] and hide a missing dependency.
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable
        def consume(values: Iterable[int | float]) -> str:
            return repr(list(values))
        def main() -> str:
            return consume((1.5, 2.5))
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_reusable_item_views_preserve_source_identity_and_live_mutation(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable
        from pyjs.native import gc_collect, gc_set_threshold

        def integers(source: list[int]) -> Iterable[int]:
            return source
        def union(source: Iterable[int]) -> Iterable[int | str]:
            return source
        def boxed(source: Iterable[int | str]) -> Iterable[object]:
            return source
        def consume(source: Iterable[int | str]) -> str:
            return repr(list(source))
        def main() -> str:
            gc_set_threshold(1)
            rows = [1, 2]
            first = integers(rows)
            middle = union(first)
            view = boxed(middle)
            assert view is rows and middle is first and id(view) == id(rows)
            one, two = iter(view), iter(view)
            assert next(one) == 1 and next(two) == 1
            rows.append(3)
            gc_collect()
            observations = [repr(list(one)), repr(list(two)), repr(list(view)), repr(list(view))]
            observations.append(consume(rows))
            observations.append(consume(["a", "b"]))
            observations.append(consume(range(2)))
            observations.append(consume(()))
            once = iter(rows)
            observations.append(consume(once))
            observations.append(consume(once))
            assert view is rows and id(view) == id(rows)
            return repr(observations)
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_item_views_defer_custom_acquisition_and_preserve_truth_retry(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable, Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Source:
            def __init__(self, events: list[str]):
                self.events = events
                self.failed = False
                self.rows = [3, 4]
            def __bool__(self) -> bool:
                gc_collect()
                self.events.append("truth")
                if self.failed:
                    raise ValueError("truth failed")
                return bool(self.rows)
            def __iter__(self) -> Iterator[int]:
                gc_collect()
                self.events.append("iter")
                if self.failed:
                    raise ValueError("iter failed")
                return iter(self.rows)
        def expose(source: Source) -> Iterable[object]:
            return source
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            original = Source(events)
            view = expose(original)
            assert events == [] and view is original
            assert bool(view)
            first = list(view)
            original.failed = True
            for operation in [0, 1]:
                try:
                    if operation == 0:
                        bool(view)
                    else:
                        iter(view)
                    assert False
                except ValueError as error:
                    events.append(str(error))
            original.failed = False
            original.rows.append(5)
            gc_collect()
            second = list(view)
            assert id(view) == id(original)
            return repr((first, second, events))
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_nested_iterable_items_and_callback_protocols_are_adapted_lazily(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable, Iterable, Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Cursor:
            def __init__(self):
                self.position = 0
            def __iter__(self) -> "Cursor":
                gc_collect()
                return self
            def __next__(self) -> int:
                self.position += 1
                if self.position > 2:
                    raise StopIteration()
                return self.position
        def total(values: Iterator[int]) -> int:
            return sum(values)
        def rows(values: list[list[int]]) -> Iterable[Iterable[object]]:
            return values
        def integers(value: list[int]) -> Iterable[int]:
            return value
        def nested(values: Iterable[Iterable[int]]) -> Iterable[Iterable[object]]:
            return values
        def callbacks(values: list[Callable[[Iterator[int]], int]]) -> Iterable[Callable[[Cursor], object]]:
            return values
        def main() -> str:
            gc_set_threshold(1)
            source = [[1, 2], [3]]
            view = rows(source)
            callback = next(iter(callbacks([total])))
            result = callback(Cursor())
            first = next(iter(view))
            assert first is source[0]
            source[0].append(4)
            gc_collect()
            forwarded = nested([integers(source[0]), integers(source[1])])
            assert next(iter(forwarded)) is source[0]
            return repr((list(first), [list(row) for row in view],
                         [list(row) for row in forwarded], result))
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_nullable_chains_and_captures_keep_source_layout(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable, Iterable
        from pyjs.native import gc_collect, gc_set_threshold

        def initial(value: list[int] | None) -> Iterable[int] | None:
            return value
        def wider(value: Iterable[int] | None) -> Iterable[object] | None:
            return value
        def capture(value: Iterable[int]) -> Callable[[], str]:
            held: Iterable[object] = value
            return lambda: repr(list(held))
        def observe(value: Iterable[object] | None) -> str:
            if value is None:
                return "missing"
            return repr(list(value)) + str(bool(value))
        def change(narrow: Iterable[int], wide: Iterable[object]) -> str:
            held = wide
            before = repr(list(held))
            held = narrow
            gc_collect()
            return before + str(sum(held))
        def main() -> str:
            gc_set_threshold(1)
            rows = [1]
            first = initial(rows)
            view = wider(first)
            assert view is rows
            if first is None:
                return "unexpected"
            read = capture(first)
            held: Iterable[object] = first
            assert list(held) == [1]
            rows.append(2)
            gc_collect()
            if view is None:
                return "unexpected"
            return repr((observe(view), read(), change(first, view), observe(wider(initial(None))),
                         observe(wider(initial([]))), id(view) == id(rows)))
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_chained_view_allocation_and_acquisition_failures_are_retryable(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Iterable
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def initial(value: list[int]) -> Iterable[int]:
            return value
        def middle(value: Iterable[int]) -> Iterable[int | str]:
            return value
        def wider(value: Iterable[int | str]) -> Iterable[object]:
            return value
        def main() -> int:
            rows = [1, 2]
            original = initial(rows)
            previous = [9]
            held: Iterable[object] = previous
            union = middle(original)
            caught = False
            arm(1)
            try:
                held = wider(union)
            except MemoryError:
                caught = True
            arm(0)
            gc_collect()
            if not caught or held is not previous:
                return 1
            held = wider(union)
            arm(1000)
            cursor = iter(held)
            stages = 1000 - remaining()
            arm(0)
            if stages < 3 or stages > 10 or next(cursor) != 1:
                return 2
            for failure in range(1, stages + 1):
                caught = False
                arm(failure)
                try:
                    iter(held)
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                if not caught or list(held) != [1, 2] or held is not rows:
                    return 3
            if next(cursor) != 2:
                return 4
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stdout and not result.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_nested_widening_recovers_from_each_allocation_failure(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Iterable
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def integers(values: list[int]) -> Iterable[int]:
            return values
        def consume(groups: Iterable[Iterable[int | str]]) -> int:
            total = 0
            for values in groups:
                gc_collect()
                for value in values:
                    gc_collect()
                    if isinstance(value, int):
                        total += int(value)
            return total
        def forward(groups: Iterable[Iterable[int]]) -> int:
            return consume(groups)
        def main() -> int:
            rows = [3, 4]
            groups = [integers(rows), integers([5])]
            arm(1000)
            result = forward(groups)
            stages = 1000 - remaining()
            arm(0)
            if result != 12 or stages < 5 or stages > 100:
                return 1
            for failure in range(1, stages + 1):
                result = -1
                caught = False
                arm(failure)
                try:
                    result = forward(groups)
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                if not caught or result != -1 or forward(groups) != 12:
                    return 2
            rows.append(6)
            if forward(groups) != 18 or next(iter(groups)) is not rows:
                return 3
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stdout and not result.stderr


def test_aliased_iterable_storage_remains_invariant():
    with pytest.raises(LLVMUnsupported, match='storage|stored|invariant'):
        transpile_llvm('''
            from collections.abc import Iterable
            def unsafe(values: list[Iterable[int]]) -> list[Iterable[object]]:
                return values
            def source(value: list[int]) -> Iterable[int]:
                return value
            def main() -> int:
                unsafe([source([1])])
                return 0
        ''')
