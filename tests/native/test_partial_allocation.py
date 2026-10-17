import ctypes

import pytest

from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_partial_retains_temporary_receiver_and_arguments_across_collection(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from functools import partial
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int):
                self.value = value

        class Formatter:
            def __init__(self, prefix: str):
                self.prefix = prefix

            def format(self, left: Box, right: Box, final: int) -> str:
                gc_collect()
                return self.prefix + str(left.value + right.value + final)

        def source(events: list[int]) -> Callable[[Box, Box, int], str]:
            events.append(1)
            gc_collect()
            return Formatter("item-" + str(1)).format

        def argument(value: int, events: list[int]) -> Box:
            events.append(value)
            gc_collect()
            return Box(value)

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            callback = partial(source(events), argument(2, events), argument(3, events))
            gc_collect()
            return callback(4) + repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_partial_evaluates_arguments_before_allocation_and_recovers(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Callable
        from functools import partial
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def combine(left: str, value: int, right: str) -> str:
            gc_collect()
            return left + str(value) + right

        def argument(value: str, events: list[int], index: int, fail: bool) -> str:
            events.append(index)
            gc_collect()
            if fail:
                raise ValueError("argument failed")
            return value

        def sentinel(value: int) -> str:
            return "unchanged"

        def main() -> int:
            left = "café" + str(1)
            right = "雪" + str(2)
            events: list[int] = []
            arm(1000)
            callback: Callable[[int], str] = partial(
                combine, argument(left, events, 1, False),
                right=argument(right, events, 2, False),
            )
            allocations = 1000 - remaining()
            arm(0)
            gc_collect()
            if allocations != 1 or events != [1, 2] or callback(3) != "café13雪2":
                return 1
            for fail_argument in [False, True]:
                events.clear()
                callback = sentinel
                failure = 0
                arm(1)
                try:
                    callback = partial(
                        combine, argument(left, events, 1, False),
                        right=argument(right, events, 2, fail_argument),
                    )
                except MemoryError:
                    failure = 1
                except ValueError:
                    failure = 2
                arm(0)
                gc_collect()
                if failure != (2 if fail_argument else 1):
                    return 2
                if callback is not sentinel or events != [1, 2]:
                    return 3
                callback = partial(combine, left, right=right)
                gc_collect()
                if callback(3) != "café13雪2":
                    return 4
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_escaped_partial_cycle_survives_collection_then_is_reclaimed(tmp_path, optimize):
    from pyjs.native.runtime import collector, heap, roots
    from pyjs.native.runtime.pointers import free
    from pyjs.native.runtime.traces import _Exception
    from tests.native.runtime_support import runtime_functions

    source = transpile_llvm('''
        from collections.abc import Callable
        from functools import partial

        class Box:
            def __init__(self, value: int):
                self.value = value
                self.callbacks: list[Callable[[int], int]] = []

        def read(box: Box, extra: int) -> int:
            return box.value + extra + len(box.callbacks)

        def make(value: int) -> Callable[[int], int]:
            box = Box(value)
            callback = partial(read, box)
            box.callbacks.append(callback)
            return callback

        def observe(callback: Callable[[int], int]) -> int:
            return callback(1)

        def main() -> int:
            return observe(make(40))
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
    make.argtypes = [ctypes.c_void_p] * 3 + [ctypes.c_int64]
    make.restype = ctypes.c_void_p
    observe = getattr(library, "fn.observe")
    observe.argtypes = [ctypes.c_void_p] * 4
    observe.restype = ctypes.c_int64
    pointer = invoke("pyjs.gc.try.new")
    state = heap._Heap.from_address(pointer.address)
    exception = _Exception()
    try:
        callback = make(None, pointer.address, ctypes.byref(exception), 40)
        assert callback and not exception.active
        invoke("pyjs.gc.pin", pointer, callback)
        assert invoke("pyjs.gc.try.collect", pointer)
        assert state.count > 0
        assert observe(None, pointer.address, ctypes.byref(exception), callback) == 42
        assert not exception.active
        invoke("pyjs.gc.unpin", pointer, callback)
        assert invoke("pyjs.gc.try.collect", pointer)
        assert state.count == 0
    finally:
        invoke("pyjs.gc.destroy", pointer)
        free(pointer)


@pytest.mark.parametrize("optimize", [0, 2])
def test_partial_capture_conversion_failures_do_not_publish_or_invoke(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Callable
        from functools import partial
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def consume(left: object, right: object, events: list[str]) -> None:
            gc_collect()
            events.append(repr((left, right)))

        def sentinel(events: list[str]) -> None:
            events.append("unchanged")

        def main() -> int:
            events: list[str] = []
            values = [1, 2]
            callback: Callable[[list[str]], None] = sentinel
            # Two boxes and the partial descriptor can each fail independently.
            for stage in [1, 2, 3]:
                events.clear()
                callback = sentinel
                caught = False
                arm(stage)
                try:
                    callback = partial(consume, 42, values)
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                if not caught or events or callback is not sentinel:
                    return 1
                callback = partial(consume, 42, values)
                gc_collect()
                callback(events)
                if events != ["(42, [1, 2])"]:
                    return 2
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
