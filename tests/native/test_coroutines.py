"""Native coroutine frames preserve Python's lazy execution and await results."""

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm, transpile_llvm_module
from pyjs.tooling.llvm import LLVM, LLVMLibrary


@pytest.mark.parametrize("optimize", [0, 2])
def test_coroutine_factory_is_lazy_and_completion_is_not_reusable(optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
async def answer(events: list[str], value: int) -> int:
    events.append('started')
    try:
        return value + 1
    finally:
        events.append('finished')
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    coroutine = answer(events, 41)
    assert events == []
    first = coroutine.__await__()
    second = coroutine.__await__()
    assert first is not second
    gc_collect()
    try:
        next(first)
    except StopIteration as error:
        events.append(str(error.value))
    for cursor in (first, second):
        try:
            next(cursor)
        except RuntimeError as error:
            events.append(str(error))
    return repr(events)
''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_await_keeps_results_and_expression_order(optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
async def child(value: int, events: list[int]) -> int:
    events.append(value)
    gc_collect()
    return value + 1
async def answer(events: list[int]) -> int:
    value = await child(40, events)
    return value + await child(0, events)
def main() -> str:
    gc_set_threshold(1)
    events: list[int] = []
    cursor = answer(events).__await__()
    try:
        next(cursor)
    except StopIteration as error:
        return str(error.value) + repr(events)
    return 'failed'
''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "42[40, 0]"
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_unstarted_close_skips_body_and_async_errors_run_on_resume(optimize):
    result = LLVM().assert_matches_python('''
async def failed(events: list[str]) -> None:
    try:
        events.append('started')
        raise ValueError('failure')
    finally:
        events.append('cleanup')
def main() -> str:
    events: list[str] = []
    cursor = failed(events).__await__()
    assert cursor.close() is None
    assert events == []
    cursor = failed(events).__await__()
    try:
        next(cursor)
    except ValueError as error:
        events.append(str(error))
    return repr(events)
''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_custom_awaitable_suspends_nested_frames_and_forwards_send_throw_close(optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator
from pyjs.native import gc_collect, gc_set_threshold
class Signal:
    def __await__(self) -> Generator[object, object, int]:
        received = yield 'waiting'
        if isinstance(received, int):
            return received
        return 0
async def child(events: list[str]) -> int:
    try:
        value = await Signal()
        return value + 1
    except ValueError as error:
        events.append(str(error))
        return 9
    finally:
        events.append('child cleanup')
async def parent(events: list[str]) -> int:
    try:
        return 2 * await child(events)
    finally:
        events.append('parent cleanup')
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    first = parent(events).__await__()
    assert next(first) == 'waiting'
    assert events == []
    gc_collect()
    try:
        first.send(20)
    except StopIteration as error:
        events.append(str(error.value))
    second = parent(events).__await__()
    assert next(second) == 'waiting'
    try:
        second.throw(ValueError('rejected'))
    except StopIteration as error:
        events.append(str(error.value))
    third = parent(events).__await__()
    assert next(third) == 'waiting'
    gc_collect()
    assert third.close() is None
    return repr(events)
''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_async_bound_callbacks_virtual_methods_and_defaults(optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Awaitable, Callable
class Worker:
    async def work(self, value: int = 3) -> int:
        return value + 1
class Derived(Worker):
    async def work(self, value: int = 3) -> int:
        return value + 2
async def invoke(callback: Callable[[int], Awaitable[int]], value: int) -> int:
    return await callback(value)
async def run(worker: Worker) -> int:
    callback = worker.work
    return await worker.work() + await invoke(callback, 10)
def main() -> str:
    cursor = run(Derived()).__await__()
    try:
        next(cursor)
    except StopIteration as error:
        return str(error.value)
    return 'failed'
''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "17"
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_completion_keeps_narrowed_bool_and_int_payloads(optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator
def values(value: object) -> Generator[None, None, int]:
    yield None
    if isinstance(value, int):
        return value
    return 0
def main() -> str:
    results: list[str] = []
    inputs: list[object] = [True, 42]
    for value in inputs:
        cursor = values(value)
        next(cursor)
        try:
            next(cursor)
        except StopIteration as error:
            results.append(repr(error.value))
    return repr(results)
''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "['True', '42']"
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_overlapping_await_and_control_errors_preserve_the_live_frame(optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Awaitable, Generator
class Signal:
    def __await__(self) -> Generator[object, object, int]:
        yield 'waiting'
        return 7
async def child() -> int:
    return await Signal()
async def parent(source: Awaitable[int]) -> int:
    return await source
def main() -> str:
    source = child()
    first = parent(source).__await__()
    second = parent(source).__await__()
    errors: list[str] = []
    try:
        first.send(1)
    except TypeError as error:
        errors.append(str(error))
    assert next(first) == 'waiting'
    try:
        next(second)
    except RuntimeError as error:
        errors.append(str(error))
    try:
        first.send(None)
    except StopIteration as error:
        errors.append(str(error.value))
    try:
        first.send(None)
    except RuntimeError as error:
        errors.append(str(error))
    try:
        first.throw(ValueError('ignored'))
    except RuntimeError as error:
        errors.append(str(error))
    return repr(errors)
''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_coroutine_close_returns_suppressed_exit_result_and_wraps_stop_iteration(optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator
class Signal:
    def __await__(self) -> Generator[object, object, None]:
        yield 'waiting'
async def suppressed(events: list[str]) -> int:
    try:
        await Signal()
    except GeneratorExit:
        return 99
    finally:
        events.append('cleanup')
    return 0
async def invalid() -> int:
    raise StopIteration('escaped')
def main() -> str:
    events: list[str] = []
    cursor = suppressed(events).__await__()
    assert next(cursor) == 'waiting'
    assert cursor.close() == 99
    cursor = invalid().__await__()
    try:
        next(cursor)
    except RuntimeError as error:
        events.append(str(error))
    return repr(events)
''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_await_preserves_source_objects_none_and_portable_scalar_results(optimize):
    result = LLVM().assert_matches_python('''
from pyjs import int8, float32
from pyjs.native import gc_collect, gc_set_threshold
class Box:
    def __init__(self, value: str):
        self.value = value
async def echo(box: Box) -> Box:
    gc_collect()
    return box
async def nothing() -> None:
    return None
async def integer() -> int8:
    return int8(130)
async def floating() -> float32:
    return float32(1.25)
async def work(box: Box) -> str:
    assert await nothing() is None
    result = await echo(box)
    assert result is box
    small = await integer()
    fraction = await floating()
    return result.value + str(int(small)) + ':' + str(float(fraction))
def main() -> str:
    gc_set_threshold(1)
    cursor = work(Box('result:')).__await__()
    try:
        next(cursor)
    except StopIteration as error:
        return str(error.value)
    return 'failed'
''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "result:-126:1.25"
    assert not result.native.stderr


def test_async_entry_point_requires_an_explicit_driver():
    with pytest.raises(LLVMUnsupported, match="entry points must be synchronous"):
        transpile_llvm('async def main() -> str: return "value"')


@pytest.mark.parametrize("inherited", [False, True])
@pytest.mark.parametrize("expression", [
    "drive(Signal())",
    "drive(parent(Signal()))",
    "drive(from_callback(make))",
    "drive(concrete(Signal()))",
    "drive(stored()[0])",
])
def test_awaitable_subclasses_are_rejected_before_coroutine_layout_access(expression, inherited):
    source = '''
from collections.abc import Awaitable, Callable, Generator
class Signal(Awaitable[int]):
    def __init__(self):
        self.marker = 12345
    def __await__(self) -> Generator[object, object, int]:
        yield 'waiting'
        return 7
def drive(source: Awaitable[int]) -> str:
    cursor = source.__await__()
    token = str(next(cursor))
    try:
        next(cursor)
    except StopIteration as error:
        return token + ':' + str(error.value)
    return 'failed'
async def parent(source: Awaitable[int]) -> int:
    return await source
async def concrete(source: Signal) -> int:
    return await source
def make() -> Awaitable[int]:
    return Signal()
async def from_callback(callback: Callable[[], Awaitable[int]]) -> int:
    return await callback()
def stored() -> list[Awaitable[int]]:
    return [Signal()]
def main() -> str:
    return EXPRESSION
'''.replace("EXPRESSION", expression)
    if inherited:
        source = source.replace("class Signal(Awaitable[int]):", "class Base(Awaitable[int]):")
        source = source.replace("def drive(", "class Signal(Base):\n    pass\ndef drive(")
    namespace = {"__name__": "awaitable_subclass_probe"}
    exec(source, namespace)
    assert namespace["main"]() == "waiting:7"
    with pytest.raises(LLVMUnsupported, match="Awaitable subclasses are not supported") as raised:
        transpile_llvm(source, filename="awaitable_source.py")
    assert any("awaitable_source.py:" in note for note in raised.value.__notes__)


def test_async_generators_have_an_explicit_diagnostic():
    with pytest.raises(CompilationError, match="async generators are not implemented"):
        transpile_llvm('''
async def values():
    yield 1
def main() -> None:
    values()
''')


def test_await_rejects_non_iterator_protocol_results():
    with pytest.raises(CompilationError, match="__await__ must return an iterator"):
        transpile_llvm('''
class Invalid:
    def __await__(self) -> list[int]:
        return [1]
async def consume() -> object:
    return await Invalid()
def main() -> None:
    consume().__await__().close()
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_await_inside_handler_retains_exception_and_cleanup_can_reject_close(optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator
from pyjs.native import gc_collect
class Signal:
    def __await__(self) -> Generator[object, object, None]:
        yield 'waiting'
async def handled(events: list[str]) -> None:
    try:
        raise ValueError('retained')
    except ValueError as error:
        await Signal()
        gc_collect()
        events.append(str(error))
async def cleanup() -> None:
    try:
        await Signal()
    finally:
        await Signal()
def main() -> str:
    events: list[str] = []
    cursor = handled(events).__await__()
    assert next(cursor) == 'waiting'
    gc_collect()
    try:
        next(cursor)
    except StopIteration:
        pass
    closing = cleanup().__await__()
    assert next(closing) == 'waiting'
    try:
        closing.close()
    except RuntimeError as error:
        events.append(str(error))
    closing.close()
    return repr(events)
''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_await_iterators_with_none_or_scalar_send_contracts(optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator
class Notification:
    def __await__(self) -> Generator[str, None, int]:
        yield 'notify'
        return 10
class Request:
    def __await__(self) -> Generator[str, int, int]:
        value: int = yield 'request'
        return value
async def task() -> int:
    first = await Notification()
    return first + await Request()
def main() -> str:
    cursor = task().__await__()
    assert next(cursor) == 'notify'
    assert next(cursor) == 'request'
    try:
        cursor.send(32)
    except StopIteration as error:
        return str(error.value)
    return 'failed'
''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "42"
    assert not result.native.stderr


def test_coroutine_factory_retains_parameters_without_erasing_its_completion_type():
    with analyze_source('''
async def task(values: list[int]) -> int:
    return len(values)
def main() -> None:
    task([1, 2]).__await__().close()
''', environment=NATIVE_ENVIRONMENT, wrap=False) as analysis:
        task = analysis.entry_point.container.search("task")
        assert task.is_async
        assert task.return_type.generic_name == "int"
        assert task.ir.lifetime.returned_parameters == frozenset({"values"})


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_iterator_delegation_still_closes_and_throws_into_coroutines(optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Generator, Iterator
class Signal:
    def __await__(self) -> Generator[object, None, None]:
        yield 'waiting'
async def task(events: list[str]) -> int:
    try:
        await Signal()
    except ValueError:
        return 9
    finally:
        events.append('cleanup')
    return 0
def forward(source: Iterator[object]) -> Generator[object, None, object]:
    return (yield from source)
def main() -> str:
    events: list[str] = []
    first = forward(task(events).__await__())
    assert next(first) == 'waiting'
    first.close()
    second = forward(task(events).__await__())
    assert next(second) == 'waiting'
    try:
        second.throw(ValueError('reject'))
    except StopIteration as error:
        events.append(str(error.value))
    return repr(events)
''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "['cleanup', 'cleanup', '9']"
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("expression", ["range(3)", "range(5, -1, -2)"])
def test_suspended_range_cursor_survives_separate_host_dispatch_arenas(tmp_path, optimize, asynchronous, expression):
    source = '''
from collections.abc import Generator
from pyjs import llvm
from pyjs.native import gc_collect, gc_pin, gc_unpin
class Signal:
    def __await__(self) -> Generator[object, object, None]:
        yield 1
async def child() -> None:
    await Signal()
async def consume(events: list[int]) -> None:
    for value in range(3):
        events.append(value)
        await child()
class State:
    def __init__(self):
        self.events: list[int] = []
        self.cursor = consume(self.events).__await__()
_state: State | None = None
@llvm.inline("call ptr @test.get()")
def get_state() -> State | None:
    return _state
@llvm.inline("call void @test.set(ptr {value})")
def set_state(value: State | None) -> None:
    global _state
    _state = value
def main(start: bool) -> str:
    if start:
        fresh = State()
        gc_pin(fresh)
        set_state(fresh)
    state = get_state()
    if state is None:
        return 'empty'
    gc_collect()
    try:
        state.cursor.send(None)
    except StopIteration:
        set_state(None)
        gc_unpin(state)
        return repr(state.events) + ' done'
    return repr(state.events)
'''
    source = source.replace("range(3)", expression)
    if not asynchronous:
        source = source.replace("async def consume(events: list[int]) -> None:",
                                "def consume(events: list[int]) -> Generator[object, object, None]:")
        source = source.replace("        await child()", "        yield 1")
        source = source.replace("consume(self.events).__await__()", "consume(self.events)")
    namespace = {"__name__": "suspended_range_probe"}
    exec(source, namespace)
    calls = (True, False, False, False, False)
    expected = [namespace["main"](start) for start in calls]
    module = transpile_llvm_module(source, target="library")
    ir = module.llvm_ir + """
@test.state = private global ptr null
define ptr @test.get() { %p = load ptr, ptr @test.state ret ptr %p }
define void @test.set(ptr %p) { store ptr %p, ptr @test.state ret void }
"""
    path = LLVM().compile(ir, tmp_path, shared=True, optimize=optimize)
    library = LLVMLibrary(path, ir, module.parameters, module.direct, module.managed,
                          module.exceptions, module.type_definitions)
    try:
        # render() frees its arena after every call while retaining the heap.
        # A cursor in the suspended frame must not point into that old arena.
        assert [library.render(start) for start in calls] == expected
    finally:
        library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_callback_may_return_an_awaitable_or_none(optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Awaitable, Callable, Generator
from pyjs.native import gc_collect
class Wait:
    def __await__(self) -> Generator[object, object, None]:
        yield 'waiting'
class Listener:
    def __init__(self, callback: Callable[[list[str]], Awaitable[None] | None]):
        self.callback = callback
    async def deliver(self, events: list[str]) -> None:
        result = self.callback(events)
        if result is not None:
            await result
class Handlers:
    def sync(self, events: list[str]) -> None:
        events.append('sync')
    async def async_handler(self, events: list[str]) -> None:
        events.append('start')
        try:
            await Wait()
        finally:
            events.append('end')
def main() -> str:
    events: list[str] = []
    handlers = Handlers()
    listeners = [Listener(handlers.sync), Listener(handlers.async_handler)]
    for listener in listeners:
        cursor = listener.deliver(events).__await__()
        try:
            events.append(str(next(cursor)))
            gc_collect()
            next(cursor)
        except StopIteration:
            events.append('done')
    return repr(events)
''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "['sync', 'done', 'start', 'waiting', 'end', 'done']"
    assert not result.native.stderr


@pytest.mark.parametrize("prefix", ["", "async "])
def test_optional_awaitable_callback_rejects_incompatible_result(prefix):
    with pytest.raises(CompilationError, match="returns.*expected"):
        transpile_llvm(f'''
from collections.abc import Awaitable, Callable
{prefix}def wrong() -> str:
    return 'wrong'
def accept(callback: Callable[[], Awaitable[None] | None]) -> int:
    return 0
def main() -> int:
    return accept(wrong)
''')
