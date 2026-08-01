from pyjs import js


@js(builtin=True)
def setTimeout(callback: callable, milliseconds: int = 0, *arguments: object) -> int: ...


@js(builtin=True)
def clearTimeout(timer: int | None = None) -> None: ...


@js(builtin=True)
def setInterval(callback: callable, milliseconds: int = 0, *arguments: object) -> int: ...


@js(builtin=True)
def clearInterval(timer: int | None = None) -> None: ...


@js(builtin=True)
def queueMicrotask(callback: callable) -> None: ...


@js(builtin=True)
def requestAnimationFrame(callback: callable) -> int: ...


@js(builtin=True)
def cancelAnimationFrame(request_id: int) -> None: ...
