import asyncio
import hashlib
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol, Self

from pyjs.server.stream import (
    StreamEvent,
    StreamResyncRequired,
    StreamSubscription,
)

__all__ = [
    "AsyncValkeyStreamClient",
    "ValkeyStreamBackend",
    "ValkeyStreamClient",
]

type EncodedStreamValue = str | bytes
type StreamEncoder[Value] = Callable[[Value], EncodedStreamValue]
type StreamDecoder[Value] = Callable[[EncodedStreamValue], Value]
type StreamFields = Mapping[object, object] | Sequence[object]
type StreamEntry = tuple[object, StreamFields]


class ValkeyStreamClient(Protocol):
    """Synchronous commands required by `ValkeyStreamBackend`."""

    def eval(self, script: str, numkeys: int, *values: object) -> object: ...

    def get(self, key: str) -> object: ...

    def xrange(
        self,
        key: str,
        minimum: str,
        maximum: str,
        *,
        count: int | None = None,
    ) -> Sequence[StreamEntry]: ...


class AsyncValkeyStreamClient(Protocol):
    """Asynchronous blocking command required by stream subscriptions."""

    async def xread(
        self,
        streams: Mapping[str, str],
        *,
        count: int | None = None,
        block: int | None = None,
    ) -> object: ...


PUBLISH_SCRIPT = """
local sequence = redis.call('INCR', KEYS[1])
redis.call(
    'XADD', KEYS[2], 'MAXLEN', '=', ARGV[1],
    tostring(sequence) .. '-0', 'value', ARGV[2]
)
return sequence
""".strip()


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _stream_value(fields: StreamFields) -> EncodedStreamValue:
    if isinstance(fields, Mapping):
        value = fields.get("value")
        if value is None:
            value = fields.get(b"value")
    else:
        value = next(
            (
                fields[index + 1]
                for index in range(0, len(fields) - 1, 2)
                if _text(fields[index]) == "value"
            ),
            None,
        )
    if not isinstance(value, str | bytes):
        raise ValueError("A Valkey stream entry is missing its encoded value.")
    return value


def _sequence(entry_id: object) -> int:
    value = _text(entry_id)
    try:
        sequence, suffix = value.split("-", 1)
        if suffix != "0":
            raise ValueError
        return int(sequence)
    except ValueError as error:
        raise ValueError(f"Invalid PyJS stream entry ID: {value!r}.") from error


def _response_entries(response: object) -> Sequence[StreamEntry]:
    if response is None:
        return ()
    groups = response.items() if isinstance(response, Mapping) else response
    entries = []
    for _key, values in groups:
        entries.extend(values.items() if isinstance(values, Mapping) else values)
    return entries


class _ValkeyStreamSubscription[Value]:
    def __init__(
        self,
        backend: ValkeyStreamBackend[Value],
        scope: str,
        events: tuple[StreamEvent[Value], ...],
        buffer_limit: int,
        after: int,
    ):
        self._backend = backend
        self.scope = scope
        self._events = deque(events)
        self._buffer_limit = buffer_limit
        self._after = after
        self._closed = False

    @property
    def sequence(self) -> int:
        return self._after

    async def receive(self) -> StreamEvent[Value]:
        while True:
            if self._closed:
                raise RuntimeError("The stream subscription is closed.")
            if self._events:
                event = self._events.popleft()
                self._after = event.sequence
                return event
            response = await self._backend.async_client.xread(
                {self._backend._stream_key(self.scope): f"{self._after}-0"},
                count=self._buffer_limit + 1,
                block=self._backend.read_block_milliseconds,
            )
            entries = _response_entries(response)
            if not entries:
                continue
            try:
                events = self._backend._decode_entries(self.scope, entries)
            except Exception as error:
                latest = await asyncio.to_thread(
                    self._backend.watermark,
                    self.scope,
                )
                raise StreamResyncRequired(
                    self.scope,
                    self._after,
                    self._after + 1,
                    latest,
                ) from error
            if (
                len(events) > self._buffer_limit
                or any(
                    event.sequence != self._after + index
                    for index, event in enumerate(events, 1)
                )
            ):
                raise StreamResyncRequired(
                    self.scope,
                    self._after,
                    events[0].sequence,
                    events[-1].sequence,
                )
            self._events.extend(events)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> StreamEvent[Value]:
        try:
            return await self.receive()
        except RuntimeError as error:
            if self._closed:
                raise StopAsyncIteration from error
            raise

    def close(self) -> None:
        self._closed = True
        self._events.clear()


class ValkeyStreamBackend[Value]:
    """Ordered, replayable fan-out backed by Valkey-compatible clients.

    The clients are structural protocols; PyJS does not import a particular
    Valkey or Redis package. The synchronous client handles publication and
    replay, while the asynchronous client performs blocking `XREAD` calls.
    Values are encoded before the atomic sequence-and-append operation, so an
    encoder failure cannot retain a poison event.
    """

    def __init__(
        self,
        client: ValkeyStreamClient,
        async_client: AsyncValkeyStreamClient,
        *,
        encode: StreamEncoder[Value],
        decode: StreamDecoder[Value],
        key_prefix: str = "pyjs:stream",
        replay_limit: int = 256,
        read_block_milliseconds: int = 1000,
    ):
        key_prefix = key_prefix.rstrip(":")
        if not key_prefix:
            raise ValueError("A Valkey stream key prefix cannot be empty.")
        if replay_limit <= 0:
            raise ValueError("A Valkey stream replay limit must be positive.")
        if read_block_milliseconds <= 0:
            raise ValueError("A Valkey stream read block must be positive.")
        self.client = client
        self.async_client = async_client
        self.encode = encode
        self.decode = decode
        self.key_prefix = key_prefix
        self.replay_limit = replay_limit
        self.read_block_milliseconds = read_block_milliseconds

    def watermark(self, scope: str) -> int:
        self._validate_scope(scope)
        value = self.client.get(self._sequence_key(scope))
        return 0 if value is None else int(value)

    def replay(
        self,
        scope: str,
        after: int,
    ) -> tuple[StreamEvent[Value], ...] | None:
        self._validate_scope(scope)
        latest = self.watermark(scope)
        if after < 0 or after > latest:
            return None
        if after == latest:
            return ()
        entries = self.client.xrange(
            self._stream_key(scope),
            f"({after}-0",
            f"{latest}-0",
            count=self.replay_limit + 1,
        )
        try:
            events = self._decode_entries(scope, entries)
        except Exception:
            return None
        if (
            not events
            or events[0].sequence != after + 1
            or events[-1].sequence != latest
            or any(
                event.sequence != after + index
                for index, event in enumerate(events, 1)
            )
        ):
            return None
        return events

    def subscribe(
        self,
        scope: str,
        *,
        after: int | None = None,
        buffer_limit: int = 256,
    ) -> StreamSubscription[Value]:
        self._validate_scope(scope)
        if buffer_limit <= 0:
            raise ValueError("The stream subscription buffer must be positive.")
        start = self.watermark(scope) if after is None else after
        replay = () if after is None else self.replay(scope, after)
        if replay is None or len(replay) > buffer_limit:
            raise self._resync_required(scope, start)
        return _ValkeyStreamSubscription(
            self,
            scope,
            replay,
            buffer_limit,
            start,
        )

    def publish(self, scope: str, value: Value) -> StreamEvent[Value]:
        self._validate_scope(scope)
        encoded = self.encode(value)
        if not isinstance(encoded, str | bytes):
            raise TypeError("A stream encoder must return str or bytes.")
        sequence = int(
            self.client.eval(
                PUBLISH_SCRIPT,
                2,
                self._sequence_key(scope),
                self._stream_key(scope),
                self.replay_limit,
                encoded,
            )
        )
        return StreamEvent(scope, sequence, value)

    def _decode_entries(
        self,
        scope: str,
        entries: Sequence[StreamEntry],
    ) -> tuple[StreamEvent[Value], ...]:
        return tuple(
            StreamEvent(
                scope,
                _sequence(entry_id),
                self.decode(_stream_value(fields)),
            )
            for entry_id, fields in entries
        )

    def _sequence_key(self, scope: str) -> str:
        digest = hashlib.sha256(scope.encode()).hexdigest()
        return f"{self.key_prefix}:{{{digest}}}:sequence"

    def _stream_key(self, scope: str) -> str:
        digest = hashlib.sha256(scope.encode()).hexdigest()
        return f"{self.key_prefix}:{{{digest}}}:events"

    def _resync_required(self, scope: str, after: int) -> StreamResyncRequired:
        latest = self.watermark(scope)
        entries = self.client.xrange(
            self._stream_key(scope),
            "-",
            "+",
            count=1,
        )
        oldest = _sequence(entries[0][0]) if entries else latest + 1
        return StreamResyncRequired(scope, after, oldest, latest)

    @staticmethod
    def _validate_scope(scope: str) -> None:
        if not scope:
            raise ValueError("An ordered stream requires a scope.")
