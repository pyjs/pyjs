import json
from collections.abc import Awaitable, Callable
from typing import Literal, Self, TypedDict

from pyjs import js
from pyjs.javascript import encodeURIComponent
from pyjs.web.events import Event, MessageEvent
from pyjs.web.html import EventSource

__all__ = ["StreamSession"]


class StreamMessage(TypedDict):
    scope: str
    sequence: int
    type: Literal["event", "resync"]
    value: object | None


@js.inline("JSON.parse({source})")
def _parse_stream_message(source: str) -> StreamMessage:
    return json.loads(source)


@js
class StreamSession:
    """Receive a typed ordered stream through the browser's EventSource API.

    Args:
        path: SSE endpoint URL.
        decode: Convert each JSON value into the application's value type.
        after: Last accepted sequence when explicitly resuming a session.
        autostart: Open the EventSource immediately.
    """

    def __init__(
        self,
        path: str,
        decode: Callable[[object], object],
        *,
        after: int | None = None,
        autostart: bool = False,
    ):
        if after is not None and after < 0:
            raise ValueError("A stream session cursor cannot be negative.")
        self.path = path
        self.sequence = 0 if after is None else after
        self.scope = ""
        self.status = "stopped"
        self._has_cursor = after is not None
        self._decode = decode
        self._source: EventSource | None = None
        self._event_callback: Callable[[object], None] | None = None
        self._resync_callback: Callable[[int], Awaitable[None]] | None = None
        self._error_callback: Callable[[Event], None] | None = None
        if autostart:
            self.start()

    # Stream[T] narrows this callback while runtime sessions own the method.
    @js.keep
    def on_event(self, callback: Callable[[object], None]) -> Self:
        """Set the callback receiving decoded values in sequence order."""
        self._event_callback = callback
        return self

    def on_resync(
        self,
        callback: Callable[[int], Awaitable[None]],
    ) -> Self:
        """Set the callback that loads a new snapshot and restarts the stream."""
        self._resync_callback = callback
        return self

    def on_error(self, callback: Callable[[Event], None]) -> Self:
        """Set the callback invoked when EventSource begins reconnecting."""
        self._error_callback = callback
        return self

    def resume_after(self, sequence: int) -> Self:
        """Resume after an explicit snapshot watermark, including zero."""
        if sequence < 0:
            raise ValueError("A stream session cursor cannot be negative.")
        if self._source is not None:
            raise RuntimeError("Close the stream before changing its cursor.")
        self.sequence = sequence
        self._has_cursor = True
        return self

    def start(self):
        """Open the stream, resuming after the last accepted sequence."""
        if self._source is not None:
            return
        path = self.path
        if self._has_cursor:
            separator = "&" if "?" in path else "?"
            path += separator + "after=" + encodeURIComponent(str(self.sequence))
        source = EventSource(path)
        source.addEventListener("open", self._opened)
        source.addEventListener("event", self._received)
        source.addEventListener("resync", self._received)
        source.addEventListener("error", self._failed)
        self._source = source
        self.status = "connecting"

    def close(self):
        """Close the stream and disable automatic EventSource reconnection."""
        if self._source is not None:
            self._source.close()
            self._source = None
        self.status = "stopped"

    def _opened(self, event: Event):
        self.status = "connected"

    async def _received(self, event: Event):
        if not isinstance(event, MessageEvent):
            return
        data = event.data
        if not isinstance(data, str):
            return
        await self._receive(_parse_stream_message(data))

    async def _receive(self, message: StreamMessage):
        scope = message["scope"]
        sequence = message["sequence"]
        if self.scope and scope != self.scope:
            await self._resync(sequence)
            return
        self.scope = scope
        if message["type"] == "resync":
            await self._resync(sequence)
            return
        if sequence <= self.sequence:
            return
        if self._has_cursor and sequence != self.sequence + 1:
            await self._resync(sequence)
            return
        self.sequence = sequence
        self._has_cursor = True
        if self._event_callback is not None:
            self._event_callback(self._decode(message["value"]))

    async def _resync(self, sequence: int):
        self.close()
        self.sequence = sequence
        self._has_cursor = True
        self.status = "resync"
        if self._resync_callback is not None:
            await self._resync_callback(sequence)

    def _failed(self, event: Event):
        if self._source is None:
            return
        self.status = "connecting"
        if self._error_callback is not None:
            self._error_callback(event)
