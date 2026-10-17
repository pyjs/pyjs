import ctypes

import pytest

from pyjs.analysis.ir import build_program_ir
from pyjs.analysis.lifetime import LifetimeBoundary
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMEmitter, LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError
from tests.backend_semantics import LAMBDA_CLOSURE_CONTRACT, NESTED_CONDITIONAL_CONTRACT
from tests.native.allocation_support import run_allocation_case


def test_shared_lambda_closures():
    LLVM().assert_matches_python(LAMBDA_CLOSURE_CONTRACT.source)


def test_shared_nested_conditional_order():
    LLVM().assert_matches_python(NESTED_CONDITIONAL_CONTRACT.source)


@pytest.mark.parametrize("contract, expected", [
    ("BORROWED", LifetimeBoundary.LOCAL),
    ("EXTERNAL", LifetimeBoundary.EXTERNAL),
])
def test_lifted_lambdas_keep_external_override_lifetime_contracts(contract, expected):
    # Inspect the actual post-lifting summary: the request arena can mask a
    # wrong LOCAL allocation. The probe declaration models an external backend
    # contract only; this test does not execute an unimplemented operation.
    source = f'''
        from collections.abc import Callable
        from pyjs.decorators import native_operation, ParameterLifetime
        class Base:
            def __init__(self, value: int):
                self.value = value
            def __eq__(self, other: "Base") -> bool:
                return True
        class Child(Base):
            @native_operation("probe", self=ParameterLifetime.BORROWED,
                              other=ParameterLifetime.{contract})
            def __ne__(self, other: Base) -> bool: ...
        def direct(right: Base) -> bool:
            return Base(8) != right
        def main() -> int:
            check: Callable[[Base], bool] = lambda right: Base(8) != right
            right: Base = Child(1)
            return int(direct(right)) + int(check(right))
    '''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        emitter = LLVMEmitter("main")
        emitter.emit(build_program_ir(analysis.entry_point))
        module = analysis.entry_point.container
        external = module.search("Child").find("__ne__")
        assert external in analysis.entry_point.compilation_objects
        assert external not in emitter.module.functions
        [lifted] = emitter.module.closures
        for function in (module.search("direct"), lifted):
            [allocation] = function.ir.lifetime.allocations
            assert allocation.boundary is expected


@pytest.mark.parametrize("optimize", [0, 2])
def test_captured_tagged_parameter_releases_its_old_stack_root(tmp_path, optimize):
    source = transpile_llvm('''
        from typing import Callable
        from pyjs.native import gc_collect, gc_count

        def inspect(value: int | str) -> int:
            reader: Callable[[], str] = lambda: str(value)
            value = 0
            gc_collect()
            return gc_count()

        def main() -> int:
            return inspect('temporary')
    ''')
    # Enter the compiled function without a caller-owned root: an ordinary
    # Python call would itself retain its argument until the callee returns,
    # masking the stale *callee* stack copy this regression isolates.
    source += '''
        define i64 @test_released(i1 %allocate) {
          %arena = alloca %pyjs.arena
          call void @pyjs.arena.init(ptr %arena)
          %heap = alloca %pyjs.gc
          call void @pyjs.gc.init(ptr %heap)
          %exception = alloca %pyjs.exception
          store %pyjs.exception zeroinitializer, ptr %exception
          br i1 %allocate, label %owned, label %scalar
        owned:
          %memory = call ptr @pyjs.gc.alloc(ptr %heap, i64 8)
          %address = ptrtoint ptr %memory to i64
          br label %invoke
        scalar:
          br label %invoke
        invoke:
          %bits = phi i64 [%address, %owned], [0, %scalar]
          %tag = select i1 %allocate, i64 4, i64 2
          %first = insertvalue { i64, i64 } zeroinitializer, i64 %tag, 0
          %value = insertvalue { i64, i64 } %first, i64 %bits, 1
          %count = call i64 @fn.inspect(ptr %arena, ptr %heap, ptr %exception, { i64, i64 } %value)
          call void @pyjs.arena.destroy(ptr %arena)
          call void @pyjs.gc.destroy(ptr %heap)
          ret i64 %count
        }
    '''
    library = ctypes.CDLL(str(LLVM().compile(source, tmp_path, optimize=optimize, shared=True)))
    check = library.test_released
    check.argtypes, check.restype = [ctypes.c_bool], ctypes.c_int64
    assert check(True) == check(False)


@pytest.mark.parametrize("optimize", [0, 2])
def test_returned_cells_share_rebinding_but_not_factory_invocations(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def make(offset: int) -> tuple[Callable[[int], int], Callable[[int], int]]:
            first: Callable[[int], int] = lambda value: value + offset
            second: Callable[[int], int] = lambda value: value * offset
            offset += 1
            return first, second

        def main() -> int:
            gc_set_threshold(1)
            pair = make(3)
            other = make(10)
            gc_collect()
            return pair[0](2) + pair[1](3) + other[0](4) + other[1](1)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_conditional_lambda_is_lazy_and_uses_its_own_cfg(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable

        def record(events: list[int], value: int) -> int:
            events.append(value)
            return 12 // value

        def main() -> int:
            events: list[int] = []
            callback: Callable[[int], int] = lambda value: record(events, value) if value > 0 else 9
            assert len(events) == 0
            assert callback(0) == 9
            assert len(events) == 0
            assert callback(3) == 4
            return events[0]
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_lambdas_capture_lexical_bindings_and_shadow_parameters(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def factory(offset: int) -> Callable[[int], Callable[[int], int]]:
            result: Callable[[int], Callable[[int], int]] = lambda value: lambda extra: value + offset + extra
            offset += 1
            return result

        def shadow(offset: int) -> Callable[[int], Callable[[int], int]]:
            return lambda offset: lambda extra: offset + extra

        def main() -> int:
            gc_set_threshold(1)
            make = factory(10)
            first = make(2)
            second = make(3)
            other = shadow(100)(4)
            gc_collect()
            return first(1) + second(1) + other(5)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_loop_late_binding_and_live_pointer_replacement(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: str):
                self.value = value

        def make() -> list[Callable[[], str]]:
            box = Box("first")
            callbacks: list[Callable[[], str]] = []
            for index in range(3):
                callback: Callable[[], str] = lambda: box.value + str(index)
                callbacks.append(callback)
            box = Box("last")
            gc_collect()
            return callbacks

        def main() -> str:
            gc_set_threshold(1)
            callbacks = make()
            gc_collect()
            return callbacks[0]() + callbacks[1]() + callbacks[2]()
    ''', optimize=optimize)


@pytest.mark.parametrize("numeric", ["int8", "uint16", "int64", "float32", "float64"])
def test_represented_parameters_results_and_captures(numeric):
    LLVM().assert_matches_python(f'''
        from typing import Callable
        from pyjs import {numeric}

        def make(offset: {numeric}) -> Callable[[{numeric}], {numeric}]:
            callback: Callable[[{numeric}], {numeric}] = lambda value: value + offset
            offset += {numeric}(1)
            return callback

        def main() -> str:
            return str(make({numeric}(120))({numeric}(20)))
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_lambda_callbacks_in_eager_consumers_and_void_calls(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        from functools import reduce
        from pyjs.native import gc_collect, gc_set_threshold

        def note(events: list[int], value: int) -> None:
            gc_collect()
            events.append(value)

        def main() -> int:
            gc_set_threshold(1)
            scale = -1
            values = [2, 4, 1, 3]
            values.sort(key=lambda value: value * scale)
            assert values[0] == 4 and values[3] == 1
            assert sorted(values, key=lambda value: value)[0] == 1
            assert min(values, key=lambda value: value * scale) == 4
            assert max(iter(values), key=lambda value: value * scale) == 1
            total = reduce(lambda left, right: left + right, values, 0)
            events: list[int] = []
            callback: Callable[[int], None] = lambda value: note(events, value)
            callback(total)
            return events[0]
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_lambda_exception_unwinds_and_retains_captures_for_reuse(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def calculate(values: list[int], divisor: int) -> str:
            gc_collect()
            return str(values[0] // divisor)

        def make() -> Callable[[int], str]:
            values = [12]
            return lambda divisor: calculate(values, divisor)

        def main() -> str:
            gc_set_threshold(1)
            callback = make()
            try:
                callback(0)
            except ZeroDivisionError:
                gc_collect()
            return callback(3)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_capture_free_lambda_has_per_evaluation_identity(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable

        def make() -> Callable[[int], int]:
            return lambda value: value + 1

        def main() -> int:
            first = make()
            alias = first
            second = make()
            assert first is alias
            assert first is not second
            return first(1) + second(2)
    ''', optimize=optimize)


@pytest.mark.parametrize("declaration", [
    "lambda value=1: value",
    "lambda value, *rest: value",
    "lambda value, **named: value",
    "lambda value, *, extra=1: value",
])
def test_lambda_unsupported_binding_shapes_are_explicit(declaration):
    with pytest.raises(LLVMUnsupported, match="fixed positional parameters"):
        transpile_llvm(f'''
            from typing import Callable
            def main() -> int:
                callback: Callable[[int], int] = {declaration}
                return callback(1)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_lambda_can_construct_and_return_objects_and_collections(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: str):
                self.value = value

        def main() -> str:
            gc_set_threshold(1)
            factory: Callable[[str], Box] = lambda value: Box(value + "!")
            collection: Callable[[Box], list[Box]] = lambda box: [box]
            box = factory("hello")
            values = collection(box)
            gc_collect()
            return values[0].value
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_lambda_cycle_and_nested_closure_collections(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def make() -> Callable[[int], int]:
            recurse: Callable[[int], int] = lambda value: value
            recurse = lambda value: value * recurse(value - 1) if value > 1 else 1
            return recurse

        def main() -> int:
            gc_set_threshold(1)
            callbacks: list[Callable[[int], int]] = [make()]
            mapping: dict[str, Callable[[int], int]] = {"factorial": callbacks[0]}
            callbacks.clear()
            gc_collect()
            return mapping["factorial"](5)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_captured_receiver_virtual_dispatch_and_pointer_temporaries(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: str):
                self.value = value

            def label(self) -> str:
                return self.value

            def callback(self) -> Callable[[], str]:
                return lambda: self.label()

        class Child(Box):
            def label(self) -> str:
                return self.value + "!"

        def replace(values: list[Box]) -> str:
            values.clear()
            gc_collect()
            return "tail"

        def combine(box: Box, text: str) -> str:
            return box.value + text

        def main() -> str:
            gc_set_threshold(1)
            bound = Child("child").callback()
            values = [Box("head")]
            callback: Callable[[], str] = lambda: combine(values[0], replace(values))
            result = callback()
            gc_collect()
            return result + bound()
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_cell_and_descriptor_allocation_failures_unwind_to_caller(optimize, tmp_path):
    source = transpile_llvm('''
        from typing import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining

        def make(offset: int, text: str) -> Callable[[int], str]:
            return lambda value: text + str(value + offset)

        def main() -> int:
            gc_set_threshold(1)
            failures = 0
            successes = 0
            for count in range(1, 12):
                arm(count)
                try:
                    callback = make(10, "item:")
                    result = callback(2)
                    arm(0)
                    assert result == "item:12"
                    successes += 1
                except MemoryError:
                    arm(0)
                    failures += 1
                gc_collect()
                callback = make(20, "recovered:")
                assert callback(1) == "recovered:21"
            assert failures >= 3 and successes > 0
            assert remaining() == 0
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_cell_failure_preserves_previous_callback(optimize, tmp_path):
    source = transpile_llvm('''
        from typing import Callable
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def sentinel() -> str:
            return "sentinel"

        def main() -> int:
            make: Callable[[str], Callable[[], str]] = lambda value: lambda: value
            text = "café" + str(42)
            for stage in range(1, 4):
                result: Callable[[], str] = sentinel
                caught = False
                arm(stage)
                try:
                    result = make(text)
                except MemoryError:
                    caught = True
                arm(0)
                gc_collect()
                assert caught == (stage <= 2)
                assert result() == ("sentinel" if caught else text)
                assert make(text)() == text
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


def test_lambda_library_traceback_and_recovery(tmp_path):
    source = '''
from typing import Callable
from pyjs.native import gc_set_threshold

def render(value: int) -> str:
    gc_set_threshold(1)
    callback: Callable[[int], str] = lambda divisor: str(value // divisor)
    return callback(value)
'''
    library = LLVM().compile_library(source, tmp_path, entry_point="render", filename="closure.py")
    try:
        for _ in range(3):
            with pytest.raises(LLVMRuntimeError) as caught:
                library.render(0)
            assert caught.value.exception_type == "ZeroDivisionError"
            assert caught.value.native_traceback == (
                'Traceback (native PyJS):\n'
                '  File "closure.py", line 8, in render\n'
                '  File "closure.py", line 7, in lambda.0\n'
                'ZeroDivisionError: division by zero\n'
            )
            assert library.render(3) == "1"
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_closure_cycle_retains_captured_graph_and_is_collectable(optimize, tmp_path):
    from pyjs.native.runtime import collector, heap, roots
    from pyjs.native.runtime.pointers import free
    from pyjs.native.runtime.traces import _Exception
    from tests.native.runtime_support import runtime_functions

    source = transpile_llvm('''
        from typing import Callable

        class Box:
            def __init__(self, value: int):
                self.value = value

        def make(value: int) -> Callable[[int], int]:
            box = Box(value)
            callback: Callable[[int], int] = lambda number: number
            callback = lambda number: callback(number - 1) if number > 0 else box.value
            return callback

        def observe(callback: Callable[[int], int]) -> int:
            return callback(4)

        def main() -> int:
            return observe(make(42))
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
        callback = make(None, pointer.address, ctypes.byref(exception), 42)
        assert callback and not exception.active
        invoke("pyjs.gc.pin", pointer, callback)
        assert invoke("pyjs.gc.try.collect", pointer)
        # Two lexical cells, the current descriptor, and its Box survive;
        # the replaced capture-free descriptor does not.
        assert state.count == 4
        assert observe(None, pointer.address, ctypes.byref(exception), callback) == 42
        assert not exception.active
        invoke("pyjs.gc.unpin", pointer, callback)
        assert invoke("pyjs.gc.try.collect", pointer)
        assert state.count == 0
    finally:
        invoke("pyjs.gc.destroy", pointer)
        free(pointer)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("kind, initial", [("int", "7"), ("str", '"ready"'), ("None", "None")])
def test_uninitialized_cells_raise_then_recover_after_assignment(optimize, kind, initial):
    LLVM().assert_matches_python(f'''
        from typing import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def empty() -> Callable[[], {kind}]:
            value: {kind}
            return lambda: value

        def main() -> str:
            gc_set_threshold(1)
            value: {kind}
            callback: Callable[[], {kind}] = lambda: value
            errors = ""
            try:
                callback()
            except NameError as error:
                errors += str(error)
            try:
                local = value
            except UnboundLocalError as error:
                errors += ":" + str(error)
            value = {initial}
            assert callback() {"is" if kind == "None" else "=="} value
            escaped = empty()
            gc_collect()
            try:
                escaped()
            except NameError as error:
                errors += ":" + str(error)
            return errors
        ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_represented_signatures_and_static_array_captures(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        from pyjs import StaticArray, int8, float32

        def make(values: StaticArray[int8, 2]) -> Callable[[int8], Callable[[int8], int8]]:
            return lambda value: lambda extra: values[0] + value + extra

        def floats(offset: float32) -> Callable[[float32], Callable[[float32], float32]]:
            return lambda value: lambda extra: offset + value + extra

        def main() -> int:
            values = StaticArray[int8, 2]([120, 2])
            callback = make(values)(int8(3))
            values[0] = int8(127)
            assert callback(int8(1)) == int8(-125)
            assert floats(float32(1.25))(float32(2.5))(float32(3.0)) == float32(6.75)
            return 0
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_private_wide_scalar_cells_do_not_overlap_the_initialization_flag(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        from pyjs.native.runtime.wide import WideInt, widen, shift_left, equal

        def make(value: WideInt) -> Callable[[], bool]:
            return lambda: equal(value, shift_left(widen(1), widen(80)))

        def main() -> int:
            callback = make(shift_left(widen(1), widen(80)))
            return 1 if callback() else 0
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_compound_lambda_body_preserves_argument_and_short_circuit_order(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable

        def record(events: list[int], value: int) -> int:
            events.append(value)
            return value

        def combine(left: int, right: int) -> int:
            return left + right

        def main() -> int:
            events: list[int] = []
            ordered: Callable[[bool], int] = lambda flag: combine(record(events, 1), record(events, 2) if flag else record(events, 3))
            skipped: Callable[[bool], bool] = lambda flag: False and ((record(events, 4) == 4) if flag else (record(events, 5) == 5))
            assert ordered(True) == 3
            assert events[0] == 1 and events[1] == 2
            assert not skipped(True)
            return len(events)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_conditional_nested_lambdas_receive_contextual_signatures(optimize):
    LLVM().assert_matches_python('''
        from typing import Callable
        from pyjs import int8

        def make(offset: int8) -> Callable[[bool], Callable[[int8], int8]]:
            return lambda flag: (lambda extra: offset + extra) if flag else (lambda extra: offset - extra)

        def choose(flag: bool) -> Callable[[int8], int8]:
            return (lambda value: value + int8(1)) if flag else (lambda value: value - int8(1))

        def shadow() -> Callable[[str], Callable[[int8], Callable[[], int8]]]:
            return lambda value: lambda value: lambda: value + int8(1)

        def main() -> int:
            first = make(int8(127))
            assert first(True)(int8(1)) == int8(-128)
            assert first(False)(int8(1)) == int8(126)
            assert choose(True)(int8(127)) == int8(-128)
            assert choose(False)(int8(-128)) == int8(127)
            return int(shadow()("ignored")(int8(127))())
    ''', optimize=optimize)
