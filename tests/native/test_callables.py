import ctypes

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import CALLABLE_VALUE_CONTRACT


def test_shared_callable_values():
    LLVM().assert_matches_python(CALLABLE_VALUE_CONTRACT.source)


def test_generic_opaque_callback_consumers_require_concrete_native_signatures():
    with pytest.raises(LLVMUnsupported, match="matching parameter and result types"):
        transpile_llvm('''
            from collections.abc import Callable
            from pyjs import int8
            def narrow(value: int8) -> int8:
                return value + int8(1)
            def accept[T](callback: Callable[..., T]) -> int:
                return 11
            def main() -> int:
                callback: Callable[[int8], int8] = narrow
                return accept(callback)
        ''')


@pytest.mark.parametrize("module", ["typing", "collections.abc"])
def test_functions_and_bound_methods(module):
    LLVM().assert_matches_python(f'''
        from {module} import Callable

        class Counter:
            def __init__(self, value: int):
                self.value = value

            def add(self, value: int) -> int:
                return self.value + value

        def increment(value: int) -> int:
            return value + 1

        def apply(callback: Callable[[int], int], value: int) -> int:
            return callback(value)

        def main() -> int:
            plain: Callable[[int], int] = increment
            counter = Counter(1)
            bound = counter.add
            return apply(plain, 1) + apply(bound, 2)
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_returned_callbacks_in_fields_and_collections(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        class Counter:
            def __init__(self, value: int):
                self.value = value

            def add(self, value: int) -> int:
                self.value += value
                return self.value

        class Holder:
            def __init__(self, callback: Callable[[int], int]):
                self.callback = callback

        def make(value: int) -> Callable[[int], int]:
            return Counter(value).add

        def increment(value: int) -> int:
            return value + 1

        def select(flag: bool) -> Callable[[int], int]:
            return increment if flag else make(10)

        def main() -> int:
            gc_set_threshold(1)
            holder = Holder(make(20))
            callbacks: list[Callable[[int], int]] = [increment, make(30)]
            mapping: dict[str, Callable[[int], int]] = {"a": make(40)}
            pair = (make(50), make(60))
            callbacks.append(holder.callback)
            gc_collect()
            total = 0
            for callback in callbacks:
                total += callback(1)
            total += mapping["a"](2) + pair[0](3) + pair[1](4)
            total += select(True)(5) + select(False)(6)
            return total
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_callback_numeric_storage_and_checked_exceptions(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        from pyjs import int8, float32

        def narrow(value: int8) -> int8:
            return value + int8(1)

        def rounded(value: float32) -> float32:
            return value * float32(2.0)

        def apply(callback: Callable[[int8], int8], value: int8) -> int8:
            return callback(value)

        def change(callback: Callable[[float32], float32], value: float32) -> float32:
            return callback(value)

        def fail(value: int) -> int:
            return 12 // value

        def checked(callback: Callable[[int], int]) -> int:
            try:
                return callback(0)
            except ZeroDivisionError:
                return callback(3)

        def main() -> str:
            return str(apply(narrow, int8(127))) + ":" + str(change(rounded, float32(1.25))) + ":" + str(checked(fail))
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_static_and_super_method_values(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable

        class Base:
            def __init__(self, events: list[int]):
                self.events = events

            def value(self, number: int) -> int:
                return number + 1

        class Child(Base):
            def value(self, number: int) -> int:
                return number + 10

            def parent(self) -> Callable[[int], int]:
                return super().value

            @staticmethod
            def twice(number: int) -> int:
                return number * 2

        def bind(value: Base) -> Callable[[int], int]:
            return value.value

        def record(value: Child) -> Child:
            value.events.append(1)
            return value

        def main() -> int:
            events: list[int] = []
            value = Child(events)
            virtual = bind(value)
            parent = value.parent()
            static = Child.twice
            through_instance = record(value).twice
            bound = record(value).value
            return virtual(1) + parent(2) + static(3) + through_instance(4) + bound(5) + len(events) * 100
    ''', optimize=optimize)


@pytest.mark.parametrize("definition, expected", [
    ("def value(*numbers: int) -> int: return len(numbers)", "fixed positional"),
    ("def value(**numbers: int) -> int: return len(numbers)", "fixed positional"),
])
def test_callback_rejects_variadic_signatures(definition, expected):
    with pytest.raises(LLVMUnsupported, match=expected):
        transpile_llvm(f'''
            from typing import Callable
            {definition}
            def apply(callback: Callable[[], int]) -> int:
                return callback()
            def main() -> int:
                return apply(value)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_callback_target_is_captured_before_argument_mutation(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        class Counter:
            def __init__(self, value: int):
                self.value = value

            def add(self, number: int) -> int:
                return self.value + number

        class Holder:
            def __init__(self, callback: Callable[[int], int]):
                self.callback = callback

        def replace(holder: Holder) -> int:
            holder.callback = Counter(100).add
            gc_collect()
            return 1

        def main() -> int:
            gc_set_threshold(1)
            holder = Holder(Counter(10).add)
            first = holder.callback(replace(holder))
            return first * 1000 + holder.callback(2)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_callback_allocation_failure_unwinds_and_recovers(optimize, tmp_path):
    from tests.native.allocation_support import run_allocation_case

    source = transpile_llvm('''
        from tests.native.allocation_support import arm, remaining
        from pyjs.native import gc_collect, gc_set_threshold

        class Counter:
            def __init__(self, value: int):
                self.value = value

            def add(self, number: int) -> int:
                return self.value + number

        def main() -> int:
            gc_set_threshold(1)
            counter = Counter(40)
            arm(1)
            caught = False
            try:
                failed = counter.add
            except MemoryError:
                caught = True
            arm(0)
            assert caught
            callback = counter.add
            gc_collect()
            assert callback(2) == 42
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


def test_callable_annotations_accept_aliases():
    LLVM().assert_matches_python('''
        import collections.abc as abc
        import typing as types
        from collections.abc import Callable as Callback

        def identity(value: int) -> int:
            return value

        def left(callback: abc.Callable[[int], int]) -> types.Callable[[int], int]:
            return callback

        def main() -> int:
            callback: Callback[[int], int] = identity
            return left(callback)(42)
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("binding", ["Counter(value).add", "Child(value).parent()", "Cycle(value).callback"])
@pytest.mark.parametrize("returned", ["int", "object"])
def test_callback_owns_receiver_and_releases_both_after_unpinning(optimize, binding, returned, tmp_path):
    from pyjs.native.runtime import collector, heap, roots
    from pyjs.native.runtime.pointers import free
    from pyjs.native.runtime.traces import _Exception
    from tests.native.runtime_support import runtime_functions

    source = transpile_llvm(f'''
        from typing import Callable

        class Counter:
            def __init__(self, value: int):
                self.value = value

            def add(self, number: int) -> int:
                return self.value + number

        class Child(Counter):
            def parent(self) -> Callable[[int], int]:
                return super().add

        class Cycle(Counter):
            def __init__(self, value: int):
                super().__init__(value)
                self.callback = self.add

        def make(value: int) -> Callable[[int], {returned}]:
            return {binding}

        def observe(callback: Callable[[int], {returned}]) -> int:
            value = callback(1)
            return int(value) if isinstance(value, int) else 0

        def main() -> int:
            return observe(make(41))
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
        callback = make(None, pointer.address, ctypes.byref(exception), 41)
        assert callback and not exception.active
        assert state.count == (3 if returned == "object" else 2)
        invoke("pyjs.gc.pin", pointer, callback)
        assert invoke("pyjs.gc.try.collect", pointer)
        assert state.count == (3 if returned == "object" else 2)
        assert observe(None, pointer.address, ctypes.byref(exception), callback) == 42
        assert not exception.active
        invoke("pyjs.gc.unpin", pointer, callback)
        assert invoke("pyjs.gc.try.collect", pointer)
        assert state.count == 0
    finally:
        invoke("pyjs.gc.destroy", pointer)
        free(pointer)


def test_higher_order_callbacks_and_void_results():
    LLVM().assert_matches_python('''
        from collections.abc import Callable

        class Log:
            def __init__(self, entries: list[int]):
                self.entries = entries

            def record(self, number: int) -> None:
                self.entries.append(number)

        def emit(callback: Callable[[int], None]) -> None:
            callback(40)
            callback(2)

        def increment(number: int = 1, /) -> int:
            return number + 1

        def apply(callback: Callable[[int], int], value: int) -> int:
            return callback(value)

        def twice(callback: Callable[[Callable[[int], int], int], int], value: int) -> int:
            return callback(increment, callback(increment, value))

        def main() -> int:
            values: list[int] = []
            emit(Log(values).record)
            return twice(apply, values[0] + values[1])
    ''')


def test_unbound_method_values_are_diagnosed():
    source = '''
class Counter:
    def add(self, value: int) -> int:
        return value + 1

def main() -> int:
    callback = Counter.add
    return 0
'''
    with pytest.raises(LLVMUnsupported, match="bound receiver"):
        transpile_llvm(source)
