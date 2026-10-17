import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_cursor_forwarding_keeps_state_identity_and_representation(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def keep[T](value: Iterator[T]) -> Iterator[T]:
            gc_collect()
            return value

        forward = keep

        def relay[T](value: Iterator[T], again: bool) -> Iterator[T]:
            if again:
                return relay(forward(value), False)
            return iter(value)

        def labels(prefix: str) -> Iterator[str]:
            for index in range(3):
                gc_collect()
                yield prefix + str(index)

        def numbers() -> Iterator[int8]:
            yield int8(120)
            yield int8(10)

        def main() -> str:
            gc_set_threshold(1)
            source = labels("v")
            stored: list[Iterator[str]] = [relay(source, True)]
            first = next(stored[0])
            gc_collect()
            narrow = relay(numbers(), True)
            pair = next(keep(iter([(int8(127), "tuple")])))
            total = int8(0)
            for value in narrow:
                total = int8(total + value)
            return repr((stored[0] is source, first, list(source), int(total),
                         int(pair[0] + 1), pair[1]))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_cursor_arguments_adapt_before_opaque_selection(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def select[T](left: Iterator[T], right: Iterator[T], first: bool) -> Iterator[T]:
            gc_collect()
            return left if first else right

        def main() -> str:
            gc_set_threshold(1)
            results: list[str] = []
            for first in [False, True]:
                left = iter([10, 20])
                right = iter(["one", "two"])
                chosen = select(left=left, right=right, first=first)
                gc_collect()
                results.append(repr((chosen is left, chosen is right, list(chosen), list(left), list(right))))
            return repr(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_generic_cursor_cannot_advance_without_a_concrete_item_layout():
    with pytest.raises(LLVMUnsupported, match="unsupported LLVM value type T"):
        transpile_llvm('''
            from collections.abc import Iterator
            def advance[T](value: Iterator[T]) -> Iterator[T]:
                next(value)
                return value
            def main() -> int:
                return next(advance(iter([1, 2])))
        ''')


@pytest.mark.parametrize("other", ["int16(2)", "'text'"])
def test_generic_cursor_arguments_cannot_erase_conflicting_numeric_representations(other):
    with pytest.raises(CompilationError, match="Type variable arguments use incompatible representations"):
        transpile_llvm(f'''
            from collections.abc import Iterator
            from pyjs import int8, int16
            def choose[T](a: Iterator[T], b: Iterator[T]) -> Iterator[T]: return a
            def main() -> int:
                return int(next(choose(iter([int8(1)]), iter([{other}]))))
        ''')


def test_generic_cursor_argument_expansion_requires_a_concrete_signature():
    with pytest.raises(CompilationError, match="argument expansion requires a concrete, non-overloaded signature"):
        transpile_llvm('''
            from collections.abc import Iterator
            def keep[T](value: Iterator[T]) -> Iterator[T]: return value
            def main() -> int:
                return next(keep(*(iter([1]),)))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_application_cursor_preserves_identity_without_early_iteration(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        class Payload:
            def __init__(self, value: int): self.value = value
        class Cursor:
            def __init__(self, events: list[str]):
                self.events = events
                self.index = 0
            def __iter__(self) -> "Cursor":
                self.events.append("iter")
                gc_collect()
                return self
            def __next__(self) -> Payload:
                self.events.append("next")
                self.index += 1
                gc_collect()
                if self.index > 2:
                    raise StopIteration()
                return Payload(self.index)
        def keep[T](value: Iterator[T]) -> Iterator[T]:
            gc_collect()
            return value
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            source = Cursor(events)
            stored = keep(source)
            before = repr(events)
            first = next(stored)
            same = iter(stored)
            second = next(same)
            gc_collect()
            return repr((stored is source, same is source, before, first.value, second.value, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_cursor_argument_conversion_failure_is_retryable(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm
        def select[T](left: Iterator[T], right: Iterator[T], events: list[int]) -> Iterator[T]:
            events[0] += 1
            gc_collect()
            return left
        def main() -> int:
            gc_set_threshold(1)
            for denied in (1, 2):
                left = iter([10])
                right = iter(["kept"])
                events = [0]
                caught = False
                arm(denied)
                try:
                    select(left, right, events)
                except MemoryError:
                    caught = True
                arm(0)
                if not caught or events != [0]:
                    return 1
                gc_collect()
                if repr(list(select(left, right, events))) != "[10]" or events != [1]:
                    return 2
                if next(right) != "kept" or next(left, None) is not None:
                    return 3
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stdout and not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_iterable_factories_reacquire_concrete_cursors(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable, Iterator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        def keep[T](value: Iterable[T]) -> Iterable[T]:
            gc_collect()
            return value
        def acquire[T](value: Iterable[T]) -> Iterator[T]:
            gc_collect()
            return iter(keep(value))
        class Source:
            def __init__(self, events: list[str]): self.events = events
            def __iter__(self) -> Iterator[str]:
                self.events.append("iter")
                gc_collect()
                yield "kept"
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            original = Source(events)
            source = keep(original)
            before = repr(events)
            first = acquire(source)
            second = acquire(source)
            values = [next(first), next(second)]
            numbers = keep([int8(127), int8(-128)])
            left = acquire(numbers)
            right = acquire(numbers)
            result = (int(next(left) + 1), int(next(right)), int(next(left)))
            gc_collect()
            return repr((source is original, before, values, events, result))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_generic_chain_forwards_wide_items_to_concrete_buffering_consumers(tmp_path, optimize):
    # Erased chain composition must forward the consumer's output buffer, not
    # copy items using an assumed pointer-sized layout. Unlike a heap tuple's
    # pointer handle, int|str uses a 16-byte tag/payload slot on the native ABI.
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable, Iterator
        from itertools import chain, cycle, islice, tee
        from pyjs.native import gc_collect, gc_set_threshold
        def combine[T](left: Iterator[T], right: Iterable[T]) -> Iterator[T]:
            gc_collect()
            return chain(left, right)
        def flatten[T](value: Iterator[T]) -> Iterator[T]:
            gc_collect()
            return chain.from_iterable([value, value])
        def source() -> Iterator[int | str]:
            for index in range(3):
                gc_collect()
                yield index * 1000003 if index % 2 == 0 else "item" + str(index)
        def main() -> str:
            gc_set_threshold(1)
            extra: list[int | str] = ["last", 7]
            joined = flatten(combine(source(), extra))
            left, right = tee(joined)
            middle = list(islice(left, 1, 3))
            gc_collect()
            repeated = cycle(right)
            items = [next(repeated) for _ in range(7)]
            gc_collect()
            last = next(left)
            return repr((middle, items, last, list(joined)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_generic_buffering_iterator_requires_a_concrete_item_layout():
    with pytest.raises(LLVMUnsupported, match="unsupported LLVM value type T"):
        transpile_llvm('''
            from collections.abc import Iterator
            from itertools import cycle
            def buffer[T](value: Iterator[T]) -> Iterator[T]: return cycle(value)
            def main() -> int: return next(buffer(iter([1])))
        ''')
