import ctypes

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError
from tests.backend_semantics import ITERATOR_CALLBACK_CONTRACT


def test_shared_iterator_callback_contract():
    result = LLVM().assert_matches_python(ITERATOR_CALLBACK_CONTRACT.source)
    assert result.native.returncode == 0, ITERATOR_CALLBACK_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
def test_map_filter_are_lazy_and_resume_after_callback_errors(optimize):
    LLVM().assert_matches_python('''
        def checked(value: int) -> int:
            if value == 2:
                raise ValueError("two")
            if value == 4:
                raise StopIteration("four")
            return value * 10

        def record(seen: list[int], value: int) -> int:
            seen.append(value)
            return value * 2

        def main() -> str:
            seen: list[int] = []
            values = map(lambda value: record(seen, value), [1, 2, 3])
            assert len(seen) == 0
            assert next(values) == 2 and seen == [1]
            assert list(values) == [4, 6]
            pairs = map(lambda a, b: a + b, [1, 2, 3], [10, 20])
            assert list(pairs) == [11, 22]
            assert list(filter(lambda n: n > 1, [0, 1, 2, 3])) == [2, 3]
            assert list(filter(None, ["", "yes", "", "no"])) == ["yes", "no"]
            values = map(checked, [1, 2, 3, 4, 5])
            result = str(next(values))
            try:
                next(values)
            except ValueError as error:
                result += str(error)
            result += str(next(values))
            result += str(next(values, -1))
            result += str(next(values))
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_callback_representations_bound_methods_and_adapter_consumers(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs import int8, float32
        from pyjs.native import gc_collect

        class Offset:
            def __init__(self, value: int8):
                self.value = value

            def apply(self, other: int8) -> int8:
                gc_collect()
                return self.value + other

        def floats(value: float32) -> float32:
            return value * float32(2.0)

        def make() -> Iterator[int8]:
            return map(Offset(int8(1)).apply, [int8(126), int8(127)])

        def main() -> int:
            values = make()
            gc_collect()
            assert list(values) == [int8(127), int8(-128)]
            assert list(map(floats, [float32(1.5)])) == [float32(3.0)]
            assert sum(map(lambda n: n * 2, range(4))) == 12
            assert ":".join(map(lambda n: str(n), [1, 2])) == "1:2"
            assert dict(map(lambda n: (str(n), n), [1, 2])) == {"1": 1, "2": 2}
            assert list(filter(None, [0, 2, 0, 3])) == [2, 3]
            empty: list[int] = []
            assert list(filter(None, [empty, [1], empty])) == [[1]]
            selected = filter(lambda n: n != 2, map(lambda n: n + 1, [0, 1, 2]))
            assert list(enumerate(selected)) == [(0, 1), (1, 3)]
            return next(map(lambda a, b, c: a + b + c, [1], [2], [3]))
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_filter_truth_methods_stop_subclasses_and_recovery(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        class End(StopIteration):
            pass

        class Box:
            def __init__(self, value: int):
                self.value = value

            def __bool__(self) -> bool:
                gc_collect()
                if self.value == 2:
                    raise End("skip")
                return self.value != 0

        class Inverted(Box):
            def __bool__(self) -> bool:
                return self.value == 0

        class Sized:
            def __init__(self, size: int):
                self.size = size

            def __len__(self) -> int:
                gc_collect()
                return self.size

        class Plain:
            def __init__(self, value: int):
                self.value = value

        def main() -> int:
            boxes: list[Box] = [Box(0), Box(1), Box(2), Inverted(0), Box(3)]
            nothing = None
            values = filter(nothing, boxes)
            assert next(values).value == 1
            try:
                next(values)
            except StopIteration:
                pass
            else:
                assert False
            assert next(values).value == 0
            assert next(values).value == 3
            assert len(list(filter(None, [Plain(1)]))) == 1
            sizes = filter(None, [Sized(0), Sized(-1), Sized(3)])
            try:
                next(sizes)
            except ValueError:
                pass
            else:
                assert False
            return next(sizes).size
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_callback_collection_roots_partial_rows_and_previous_arguments(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def collect(left: list[str], value: str) -> str:
            left.clear()
            gc_collect()
            return value + "!"

        def make() -> Iterator[tuple[int, tuple[str, str]]]:
            left = ["left" + str(1), "left" + str(2)]
            return enumerate(zip(left, map(lambda value: collect(left, value), ["right" + str(3)])))

        def main() -> str:
            gc_set_threshold(1)
            rows = make()
            gc_collect()
            row = next(rows)
            gc_collect()
            assert row[0] == 0
            first = ["first" + str(4)]
            mapped = map(lambda a, b: a + b, first,
                         map(lambda value: collect(first, value), ["second" + str(5)]))
            result = next(mapped)
            gc_collect()
            return row[1][0] + row[1][1] + result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_multiple_sources_consume_left_to_right_after_exhaustion_and_failures(optimize):
    LLVM().assert_matches_python('''
        def record(events: list[int], value: int) -> int:
            events.append(value)
            if value == 20:
                raise ValueError("twenty")
            return value

        def main() -> int:
            events: list[int] = []
            left = iter([1, 2, 3, 4, 5])
            right = map(lambda value: record(events, value), [10, 20, 30])
            values = map(lambda a, b: a + b, left, right)
            assert next(values) == 11
            try:
                next(values)
            except ValueError:
                pass
            else:
                assert False
            assert next(values) == 33
            assert next(values, -1) == -1
            assert next(left) == 5
            assert events == [10, 20, 30]
            shared = iter([1, 2, 3, 4, 5, 6, 7])
            values = map(lambda a, b, c: a + b + c, shared, shared, shared)
            assert list(values) == [6, 15]
            assert next(shared, -1) == -1
            return next(map(lambda a, b, c, d, e: a + b + c + d + e,
                            [1], [2], [3], [4], [5]))
    ''', optimize=optimize)


def test_adapter_library_tracebacks_and_recovery(tmp_path):
    source = '''
from pyjs.native import gc_set_threshold

def render(value: int) -> str:
    gc_set_threshold(1)
    values = [10 // divisor for divisor in [value]]
    mapped = map(lambda item: str(100 // (item - 10)), values)
    return next(enumerate(mapped))[1]
'''
    library = LLVM().compile_library(source, tmp_path, entry_point="render", filename="adapters.py")
    try:
        for _ in range(3):
            for value, frames in (
                (0, '  File "adapters.py", line 6, in render\n'
                    '  File "adapters.py", line 6, in lambda.0\n'),
                (1, '  File "adapters.py", line 8, in render\n'
                    '  File "adapters.py", line 7, in iterator_step.0\n'
                    '  File "adapters.py", line 7, in lambda.1\n'),
            ):
                with pytest.raises(LLVMRuntimeError) as caught:
                    library.render(value)
                assert caught.value.native_traceback == (
                    "Traceback (native PyJS):\n" + frames + "ZeroDivisionError: division by zero\n"
                )
            assert library.render(2) == "-20"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_enumerate_recursive_advancement_updates_current_index_and_survives_failure(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def consume(cursors: list[Iterator[tuple[int, int]]], events: list[int],
                    fail: bool, value: int) -> int:
            if value == 1:
                inner = next(cursors[0])
                events.append(inner[0])
                assert inner[1] == 2
                gc_collect()
                if fail:
                    raise ValueError("after nested advance")
            return value

        def scenario(start: int, fail: bool) -> int:
            cursors: list[Iterator[tuple[int, int]]] = []
            events: list[int] = []
            values = enumerate(map(lambda value: consume(cursors, events, fail, value), [1, 2, 3]), start)
            cursors.append(values)
            try:
                first = next(values)
                assert not fail and first == (start + 1, 1)
            except ValueError:
                assert fail
            gc_collect()
            second = next(values)
            assert second == (start + (1 if fail else 2), 3)
            assert events == [start]
            try:
                next(values)
            except StopIteration:
                return second[0]
            return -1

        def main() -> int:
            gc_set_threshold(1)
            for start in [0, 7, 9223372036854775805]:
                assert scenario(start, False) == start + 2
                assert scenario(start, True) == start + 1
            return 0
    ''', optimize=optimize)


@pytest.mark.parametrize("expression, diagnostic", [
    ("map(lambda a, b, c, d, e, f: a, [1], [2], [3], [4], [5], [6])", "at most 5 iterables"),
    ("map(lambda value: value, [1], strict=True)", "[Ss]trict|keyword"),
])
def test_callback_iterator_unsupported_boundaries_are_explicit(expression, diagnostic):
    with pytest.raises((CompilationError, LLVMUnsupported), match=diagnostic):
        transpile_llvm(f"def main() -> int:\n    values = {expression}\n    return 0\n")


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression, exhaust", [
    ('map(lambda value: value + str(len(cycle)), ["abc" + str(1)])', False),
    ('(value + str(len(cycle)) for value in ["abc" + str(1)])', False),
    ('(value + str(len(cycle)) for value in ["abc" + str(1)])', True),
    ('generate(cycle)', False),
    ('generate(cycle)', True),
])
def test_iterator_callback_cycle_retains_items_then_is_reclaimed(optimize, tmp_path, expression, exhaust):
    from pyjs.native.runtime import collector, heap, roots
    from pyjs.native.runtime.pointers import free
    from pyjs.native.runtime.traces import _Exception
    from tests.native.runtime_support import runtime_functions

    source = transpile_llvm(f'''
        from collections.abc import Iterator

        def generate(cycle: list[Iterator[str]]) -> Iterator[str]:
            yield "abc" + str(1) + str(len(cycle))

        def make() -> Iterator[str]:
            cycle: list[Iterator[str]] = []
            result = {expression}
            cycle.append(result)
            return result

        def observe(values: Iterator[str]) -> int:
            return len(next(values, ""))

        def main() -> int:
            return observe(make())
    ''')
    library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, shared=True, optimize=optimize)))
    invoke = runtime_functions({
        "pyjs.gc.try.new": collector.new_heap,
        "pyjs.gc.pin": collector.pin,
        "pyjs.gc.unpin": roots.unpin,
        "pyjs.gc.try.collect": collector.try_collect,
        "pyjs.gc.destroy": roots.destroy_heap,
    }, library)
    make = getattr(library, "fn.make")
    make.argtypes = [ctypes.c_void_p] * 3
    make.restype = ctypes.c_void_p
    observe = getattr(library, "fn.observe")
    observe.argtypes = [ctypes.c_void_p] * 4
    observe.restype = ctypes.c_int64
    pointer = invoke("pyjs.gc.try.new")
    state = heap._Heap.from_address(pointer.address)
    exception = _Exception()
    try:
        iterator = make(None, pointer.address, ctypes.byref(exception))
        assert not exception.active
        invoke("pyjs.gc.pin", pointer, iterator)
        assert invoke("pyjs.gc.try.collect", pointer) and state.count > 0
        assert observe(None, pointer.address, ctypes.byref(exception), iterator) == 5
        assert not exception.active and state.roots is None
        if exhaust:
            assert observe(None, pointer.address, ctypes.byref(exception), iterator) == 0
            # Exhaustion severs the frame even while the iterator is pinned.
            assert invoke("pyjs.gc.try.collect", pointer) and state.count == 1
        invoke("pyjs.gc.unpin", pointer, iterator)
        assert invoke("pyjs.gc.try.collect", pointer) and state.count == 0
    finally:
        invoke("pyjs.gc.destroy", pointer)
        free(pointer)
