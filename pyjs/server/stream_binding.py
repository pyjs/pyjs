import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol, Self

from pyjs import js
from pyjs.server.stream import StreamBackend, StreamEvent, StreamSnapshot
from pyjs.server.stream_client import StreamSession

__all__ = ["Stream", "StreamFeed", "StreamHistory"]

type StreamAuthorizer = Callable[[], bool | Awaitable[bool]]


class StreamHistory[Request, Result](Protocol):
    """Load authoritative history for one ordered stream scope.

    Implementations own their query and pagination semantics. Values published
    to the live tail must first be committed to this durable source.
    """

    async def load(self, scope: str, request: Request) -> Result: ...


@js
class Stream[Value](StreamSession):
    """Bind an ordered server stream to its typed browser session.

    A synchronous ``@stream`` operation returns this binding. The generated
    browser method instead constructs the inherited ``StreamSession`` API.

    Args:
        backend: Ordered publish and replay implementation.
        scope: Stable ordering and authorization boundary.
        authorize: Request-scoped callback rechecked during delivery.
        heartbeat: Seconds between authorization-checked keepalives.
        buffer_limit: Maximum queued events before requiring resync.
    """

    @js
    def __init__(
        self,
        backend: StreamBackend[Value],
        scope: str,
        *,
        authorize: StreamAuthorizer | None = None,
        heartbeat: float = 15.0,
        buffer_limit: int = 256,
    ):
        if not scope:
            raise ValueError("A stream requires a scope.")
        if heartbeat <= 0:
            raise ValueError("The stream heartbeat must be positive.")
        if buffer_limit <= 0:
            raise ValueError("The stream buffer limit must be positive.")
        self.backend = backend
        self.scope = scope
        self.authorize = authorize
        self.heartbeat = heartbeat
        self.buffer_limit = buffer_limit

    @__init__.client
    def __init__(
        self,
        path: str,
        decode: Callable[[object], Value],
    ):
        super().__init__(path, decode)

    @js.inline("{self}.on_event({callback})")
    def on_event(self, callback: Callable[[Value], None]) -> Self:
        return super().on_event(callback)


class StreamFeed[Value, Request, Result]:
    """Pair durable history with a short replayable live tail.

    History remains application-defined: it may query Django, ClickHouse, or
    another store and may use any typed request and result shape. The live
    backend independently supplies ordering, bounded replay, and delivery.
    """

    def __init__(
        self,
        backend: StreamBackend[Value],
        history: StreamHistory[Request, Result],
        scope: str,
    ):
        if not scope:
            raise ValueError("A stream feed requires a scope.")
        self.backend = backend
        self.history = history
        self.scope = scope

    async def load(self, request: Request) -> Result:
        return await self.history.load(self.scope, request)

    async def snapshot(self, request: Request) -> StreamSnapshot[Result]:
        sequence = await asyncio.to_thread(
            self.backend.watermark,
            self.scope,
        )
        value = await self.load(request)
        return StreamSnapshot(value=value, sequence=sequence)

    def events(
        self,
        *,
        authorize: StreamAuthorizer | None = None,
        heartbeat: float = 15.0,
        buffer_limit: int = 256,
    ) -> Stream[Value]:
        return Stream(
            self.backend,
            self.scope,
            authorize=authorize,
            heartbeat=heartbeat,
            buffer_limit=buffer_limit,
        )

    def publish(self, value: Value) -> StreamEvent[Value]:
        """Publish a value after its durable write has committed."""
        return self.backend.publish(self.scope, value)
