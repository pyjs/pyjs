from pyjs import js


@js(builtin=True)
class ReadableStream:
    def __init__(self, source: object | None = None, strategy: object | None = None):
        self.locked: bool = False

    async def cancel(self, reason: object | None = None) -> None: ...

    def getReader(self, options: object | None = None) -> object: ...

    def pipeThrough(self, transform: object, options: object | None = None) -> ReadableStream: ...

    async def pipeTo(self, destination: object, options: object | None = None) -> None: ...

    def tee(self) -> list[ReadableStream]: ...
