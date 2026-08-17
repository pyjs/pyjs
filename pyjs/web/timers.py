from pyjs import js


@js.native
def setTimeout(callback: callable, milliseconds: int = 0, *arguments: object) -> int: ...


@js.native
def clearTimeout(timer: int | None = None) -> None: ...


@js.native
def setInterval(callback: callable, milliseconds: int = 0, *arguments: object) -> int: ...


@js.native
def clearInterval(timer: int | None = None) -> None: ...


@js.native
def queueMicrotask(callback: callable) -> None: ...


@js.native
def requestAnimationFrame(callback: callable) -> int: ...


@js.native
def cancelAnimationFrame(request_id: int) -> None: ...
