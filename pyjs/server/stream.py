import asyncio
import threading
from collections import deque
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field

from pyjs import js
from pyjs.server.protocol import StreamEventPayload


@js
class StreamSnapshot[Value](BaseModel):
    """Pair a durable snapshot with the stream watermark used to resume it.

    Capture the watermark before loading ``value``. Replaying after that
    sequence prevents missed events, while stable value identities suppress
    at-least-once duplicates that overlap the snapshot.
    """

    value: Value
    sequence: int = Field(ge=0)


@dataclass(frozen=True)
class StreamEvent[E]:
    """One value in a scope-local ordered stream."""

    scope: str
    sequence: int
    value: E

    def payload(self) -> StreamEventPayload[E]:
        return {
            "scope": self.scope,
            "sequence": self.sequence,
            "type": "event",
            "value": self.value,
        }


class StreamResyncRequired(RuntimeError):
    """A requested sequence is no longer available for replay."""

    def __init__(
        self,
        scope: str,
        after: int,
        oldest: int,
        latest: int,
    ):
        self.scope = scope
        self.after = after
        self.oldest = oldest
        self.latest = latest
        super().__init__(
            f"Stream {scope!r} cannot resume after sequence {after}; "
            f"available range is {oldest} through {latest}."
        )


class StreamSubscription[E](Protocol):
    """Receive ordered events until the subscription closes or loses data."""

    @property
    def sequence(self) -> int: ...

    async def receive(self) -> StreamEvent[E]: ...

    def __aiter__(self) -> StreamSubscription[E]: ...

    async def __anext__(self) -> StreamEvent[E]: ...

    def close(self) -> None: ...


class StreamBackend[E](Protocol):
    """Publish and replay events ordered within an explicit scope.

    Async framework integrations run the synchronous read methods in worker
    threads. Implementations must therefore make reads and publication safe to
    call concurrently.
    """

    def watermark(self, scope: str) -> int: ...

    def replay(
        self,
        scope: str,
        after: int,
    ) -> tuple[StreamEvent[E], ...] | None: ...

    def subscribe(
        self,
        scope: str,
        *,
        after: int | None = None,
        buffer_limit: int = 256,
    ) -> StreamSubscription[E]: ...

    def publish(self, scope: str, value: E) -> StreamEvent[E]: ...


class StreamCursor:
    """Reject gaps and ignore duplicate at-least-once event deliveries."""

    def __init__(self, scope: str, after: int = 0):
        if after < 0:
            raise ValueError("A stream cursor cannot be negative.")
        self.scope = scope
        self.sequence = after

    def accept(self, event: StreamEvent[object]) -> bool:
        if event.scope != self.scope:
            raise ValueError(
                f"Expected stream scope {self.scope!r}, got {event.scope!r}."
            )
        if event.sequence <= self.sequence:
            return False
        expected = self.sequence + 1
        if event.sequence != expected:
            raise StreamResyncRequired(
                self.scope,
                self.sequence,
                event.sequence,
                event.sequence,
            )
        self.sequence = event.sequence
        return True


class _InMemoryStreamSubscription[E]:
    def __init__(
        self,
        hub: StreamHub[E],
        scope: str,
        events: tuple[StreamEvent[E], ...],
        buffer_limit: int,
        after: int,
    ):
        self._hub = hub
        self.scope = scope
        self._buffer_limit = buffer_limit
        self._after = after
        self._lock = threading.Lock()
        self._events = deque(events)
        self._waiters: deque[
            tuple[asyncio.AbstractEventLoop, asyncio.Future[StreamEvent[E]]]
        ] = deque()
        self._gap: StreamResyncRequired | None = None
        self._closed = False

    @property
    def sequence(self) -> int:
        return self._after

    async def receive(self) -> StreamEvent[E]:
        loop = asyncio.get_running_loop()
        with self._lock:
            self._raise_if_unavailable()
            if self._events:
                event = self._events.popleft()
                self._after = event.sequence
                return event
            waiter = loop.create_future()
            entry = (loop, waiter)
            self._waiters.append(entry)
        try:
            event = await waiter
            self._after = event.sequence
            return event
        finally:
            with self._lock:
                if entry in self._waiters:
                    self._waiters.remove(entry)

    def __aiter__(self) -> StreamSubscription[E]:
        return self

    async def __anext__(self) -> StreamEvent[E]:
        try:
            return await self.receive()
        except RuntimeError as error:
            if self._closed:
                raise StopAsyncIteration from error
            raise

    def receive_nowait(self) -> StreamEvent[E]:
        with self._lock:
            self._raise_if_unavailable()
            if not self._events:
                raise asyncio.QueueEmpty
            event = self._events.popleft()
            self._after = event.sequence
            return event

    def empty(self) -> bool:
        with self._lock:
            return not self._events

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._events.clear()
            waiters = list(self._waiters)
            self._waiters.clear()
        self._hub._unsubscribe(self)
        for loop, waiter in waiters:
            loop.call_soon_threadsafe(self._reject_closed, waiter)

    def _raise_if_unavailable(self) -> None:
        if self._closed:
            raise RuntimeError("The stream subscription is closed.")
        if self._gap is not None:
            raise self._gap

    def _deliver(self, event: StreamEvent[E]) -> None:
        with self._lock:
            if self._closed or self._gap is not None:
                return
            while self._waiters:
                loop, waiter = self._waiters.popleft()
                if not waiter.cancelled() and not loop.is_closed():
                    loop.call_soon_threadsafe(self._resolve, waiter, event)
                    return
            if len(self._events) < self._buffer_limit:
                self._events.append(event)
                return
            self._events.clear()
            self._gap = StreamResyncRequired(
                self.scope,
                self._after,
                event.sequence,
                event.sequence,
            )

    @staticmethod
    def _resolve(
        waiter: asyncio.Future[StreamEvent[E]],
        event: StreamEvent[E],
    ) -> None:
        if not waiter.done():
            waiter.set_result(event)

    @staticmethod
    def _reject_closed(waiter: asyncio.Future[StreamEvent[E]]) -> None:
        if not waiter.done():
            waiter.set_exception(RuntimeError("The stream subscription is closed."))


class StreamHub[E]:
    """Thread-safe in-memory ordered streams with bounded scope-local replay."""

    def __init__(self, replay_limit: int = 256):
        if replay_limit < 0:
            raise ValueError("The stream replay limit cannot be negative.")
        self._replay_limit = replay_limit
        self._lock = threading.Lock()
        self._sequences: dict[str, int] = {}
        self._history: dict[str, deque[StreamEvent[E]]] = {}
        self._subscriptions: dict[
            str,
            set[_InMemoryStreamSubscription[E]],
        ] = {}

    def watermark(self, scope: str) -> int:
        self._validate_scope(scope)
        with self._lock:
            return self._sequences.get(scope, 0)

    def replay(
        self,
        scope: str,
        after: int,
    ) -> tuple[StreamEvent[E], ...] | None:
        self._validate_scope(scope)
        with self._lock:
            return self._replay_locked(scope, after)

    def subscribe(
        self,
        scope: str,
        *,
        after: int | None = None,
        buffer_limit: int = 256,
    ) -> StreamSubscription[E]:
        self._validate_scope(scope)
        if buffer_limit <= 0:
            raise ValueError("The stream subscription buffer must be positive.")
        with self._lock:
            latest = self._sequences.get(scope, 0)
            start = latest if after is None else after
            replay = () if after is None else self._replay_locked(scope, after)
            if replay is None or len(replay) > buffer_limit:
                raise self._resync_required(scope, start)
            subscription = _InMemoryStreamSubscription(
                self,
                scope,
                replay,
                buffer_limit,
                start,
            )
            self._subscriptions.setdefault(scope, set()).add(subscription)
            return subscription

    def publish(self, scope: str, value: E) -> StreamEvent[E]:
        self._validate_scope(scope)
        with self._lock:
            sequence = self._sequences.get(scope, 0) + 1
            self._sequences[scope] = sequence
            event = StreamEvent(scope, sequence, value)
            history = self._history.setdefault(
                scope,
                deque(maxlen=self._replay_limit),
            )
            history.append(event)
            for subscription in self._subscriptions.get(scope, ()):
                subscription._deliver(event)
            return event

    def _replay_locked(
        self,
        scope: str,
        after: int,
    ) -> tuple[StreamEvent[E], ...] | None:
        latest = self._sequences.get(scope, 0)
        if after < 0 or after > latest:
            return None
        if after == latest:
            return ()
        history = self._history.get(scope)
        if not history or after < history[0].sequence - 1:
            return None
        return tuple(event for event in history if event.sequence > after)

    def _resync_required(self, scope: str, after: int) -> StreamResyncRequired:
        latest = self._sequences.get(scope, 0)
        history = self._history.get(scope)
        oldest = history[0].sequence if history else latest + 1
        return StreamResyncRequired(scope, after, oldest, latest)

    def _unsubscribe(self, subscription: _InMemoryStreamSubscription[E]) -> None:
        with self._lock:
            subscriptions = self._subscriptions.get(subscription.scope)
            if subscriptions is None:
                return
            subscriptions.discard(subscription)
            if not subscriptions:
                del self._subscriptions[subscription.scope]

    @staticmethod
    def _validate_scope(scope: str) -> None:
        if not scope:
            raise ValueError("An ordered stream requires a scope.")
