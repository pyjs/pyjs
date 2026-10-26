from collections.abc import Callable

from pyjs import js
from pyjs.electron import (
    Debugger,
    IpcEvent,
    Response,
    handle,
    on_debug_detach,
    on_debug_message,
)
from pyjs.node import ChildProcess, on_close, on_stderr, on_stdout_size, read_stdin, sleep


@js.inline("Object.assign(new (require('node:events').EventEmitter)(), {{stderr: new (require('node:events').EventEmitter)(), stdout: new (require('node:events').EventEmitter)()}})")
def emitter() -> ChildProcess: ...


@js.inline("{child}.emit('close', 3)")
def emit_close(child: ChildProcess) -> None: ...


@js.inline("{child}.stderr.emit('data', Buffer.from('hello'))")
def emit_stderr(child: ChildProcess) -> None: ...


@js.inline("{child}.stdout.emit('data', Buffer.from('hello'))")
def emit_stdout(child: ChildProcess) -> None: ...


@js.inline("new (require('node:events').EventEmitter)()")
def debugger() -> Debugger: ...


@js.inline("{target}.emit('message', null, 'paused', {{}})")
def emit_message(target: Debugger) -> None: ...


@js.inline("{target}.emit('detach', null, 'closed')")
def emit_detach(target: Debugger) -> None: ...


@js.inline("globalThis.testHandler(null, '/example', {{}})")
async def request() -> Response: ...


@js
class Collector:
    def __init__(self, name: str):
        self.name = name
        self.count = 0
        print("made", name)

    def text(self, value: str) -> None:
        self.count += 1
        print(self.name, self.count, value.strip())

    def number(self, value: int) -> None:
        self.text(str(value))

    def message(self, method: str, params: str) -> None:
        self.text(method + params)

    async def request(self, event: IpcEvent, url: str, options: str) -> Response:
        self.text(url + options)
        return Response(200, "ok")


@js
def finished() -> None:
    print("end")


@js
def register(data: Callable[[str], None]) -> None:
    # The argument name must not be captured by the adapter's arrow parameter.
    read_stdin(data, finished)


@js
async def main() -> None:
    child = emitter()
    collector = Collector("first")
    on_close(child, collector.number)
    collector = Collector("second")
    on_stderr(child, Collector("stderr").text)
    on_stdout_size(child, Collector("stdout").number)
    register(Collector("stdin").text)
    print("registered")
    emit_close(child)
    emit_stderr(child)
    emit_stderr(child)
    emit_stdout(child)
    emit_stdout(child)
    # Also exercise a caller variable that shares the Promise executor's name.
    resolve = 1
    await sleep(resolve)


@js
async def electron() -> None:
    target = debugger()
    collector = Collector("message")
    on_debug_message(target, collector.message)
    collector = Collector("reassigned")
    on_debug_detach(target, Collector("detach").text)
    handle("example", Collector("ipc").request)
    print("registered")
    emit_message(target)
    emit_message(target)
    emit_detach(target)
    emit_detach(target)
    await request()
    await request()
