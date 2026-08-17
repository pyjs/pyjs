import asyncio
import threading
from collections import deque
from dataclasses import dataclass

from pyjs.server.protocol import InvalidationPayload


@dataclass(frozen=True)
class Invalidation:
    sequence: int
    topics: tuple[str, ...]

    def payload(self) -> InvalidationPayload:
        return {
            "sequence": self.sequence,
            "topics": list(self.topics),
            "type": "invalidate",
        }


class InvalidationSubscription:
    def __init__(self, hub: InvalidationHub, topics: tuple[str, ...]):
        self._hub = hub
        self.topics = topics
        self._lock = threading.Lock()
        self._events: deque[Invalidation] = deque()
        self._waiters: deque[
            tuple[asyncio.AbstractEventLoop, asyncio.Future[Invalidation]]
        ] = deque()
        self._closed = False

    async def receive(self) -> Invalidation:
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._closed:
                raise RuntimeError("The invalidation subscription is closed.")
            if self._events:
                return self._events.popleft()
            waiter = loop.create_future()
            entry = (loop, waiter)
            self._waiters.append(entry)
        try:
            return await waiter
        finally:
            with self._lock:
                if entry in self._waiters:
                    self._waiters.remove(entry)

    def receive_nowait(self) -> Invalidation:
        with self._lock:
            if self._closed:
                raise RuntimeError("The invalidation subscription is closed.")
            if not self._events:
                raise asyncio.QueueEmpty
            return self._events.popleft()

    def empty(self) -> bool:
        with self._lock:
            return not self._events

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._events.clear()
            waiters = list(self._waiters)
            self._waiters.clear()
        self._hub._unsubscribe(self)
        for loop, waiter in waiters:
            loop.call_soon_threadsafe(self._reject, waiter)

    def _deliver(self, invalidation: Invalidation):
        with self._lock:
            if self._closed:
                return
            while self._waiters:
                loop, waiter = self._waiters.popleft()
                if not waiter.cancelled() and not loop.is_closed():
                    loop.call_soon_threadsafe(
                        self._resolve,
                        waiter,
                        invalidation,
                    )
                    return
            if not self._events:
                self._events.append(invalidation)
                return
            previous = self._events.popleft()
            topics = tuple(dict.fromkeys((*previous.topics, *invalidation.topics)))
            self._events.append(Invalidation(invalidation.sequence, topics))

    @staticmethod
    def _resolve(
        waiter: asyncio.Future[Invalidation],
        invalidation: Invalidation,
    ):
        if not waiter.done():
            waiter.set_result(invalidation)

    @staticmethod
    def _reject(waiter: asyncio.Future[Invalidation]):
        if not waiter.done():
            waiter.set_exception(
                RuntimeError("The invalidation subscription is closed.")
            )


class InvalidationHub:
    def __init__(self):
        self._lock = threading.Lock()
        self._subscriptions: dict[str, set[InvalidationSubscription]] = {}
        self._sequence = 0

    @property
    def sequence(self) -> int:
        with self._lock:
            return self._sequence

    def subscribe(self, *topics: str) -> InvalidationSubscription:
        unique_topics = tuple(dict.fromkeys(topics))
        if not unique_topics:
            raise ValueError("An invalidation subscription requires a topic.")
        subscription = InvalidationSubscription(self, unique_topics)
        with self._lock:
            for topic in unique_topics:
                self._subscriptions.setdefault(topic, set()).add(subscription)
        return subscription

    def publish(self, *topics: str) -> Invalidation:
        unique_topics = tuple(dict.fromkeys(topics))
        if not unique_topics:
            raise ValueError("An invalidation requires a topic.")
        with self._lock:
            self._sequence += 1
            invalidation = Invalidation(self._sequence, unique_topics)
            subscriptions = {
                subscription
                for topic in unique_topics
                for subscription in self._subscriptions.get(topic, ())
            }
        for subscription in subscriptions:
            subscription._deliver(invalidation)
        return invalidation

    def _unsubscribe(self, subscription: InvalidationSubscription):
        with self._lock:
            for topic in subscription.topics:
                subscriptions = self._subscriptions.get(topic)
                if subscriptions is None:
                    continue
                subscriptions.discard(subscription)
                if not subscriptions:
                    del self._subscriptions[topic]


def api_topic(root: type | object) -> str:
    root_type = root if isinstance(root, type) else type(root)
    return f"{root_type.__module__}.{root_type.__qualname__}"


def resource_topic(root: type | object, path: tuple[str, ...]) -> str:
    return api_topic(root) + ":" + ".".join(path)


default_invalidation_hub = InvalidationHub()
