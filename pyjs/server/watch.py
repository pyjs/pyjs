import asyncio
import json
from collections.abc import Awaitable
from typing import Self, TypedDict

from pyjs import js
from pyjs.javascript import _stringify_unchecked, encodeURIComponent
from pyjs.web.events import Event, MessageEvent
from pyjs.web.html import EventSource
from pyjs.web.network import fetch


class LiveQueryRequest(TypedDict):
    arguments: object
    generation: int
    id: int
    operation: str


class LiveSubscriptionQuery(TypedDict):
    arguments: object
    generation: int
    id: int
    operation: str
    topics: list[str]


class LiveQueryResult(TypedDict):
    generation: int
    id: int
    value: object


class LiveMessage(TypedDict):
    results: list[LiveQueryResult]
    sequence: int
    topics: list[str]
    type: str


class LiveRefreshRequest(TypedDict):
    queries: list[LiveQueryRequest]


class LiveRefreshResponse(TypedDict):
    results: list[LiveQueryResult]


class LiveSubscribeRequest(TypedDict):
    queries: list[LiveSubscriptionQuery]
    subscription: str


class LiveSubscribeResponse(TypedDict):
    subscription: str


@js.inline("JSON.parse({source})")
def _parse_live_message(source: str) -> LiveMessage:
    return json.loads(source)


@js.inline("JSON.parse({source})")
def _parse_live_refresh(source: str) -> LiveRefreshResponse:
    return json.loads(source)


@js.inline("JSON.parse({source})")
def _parse_live_subscribe(source: str) -> LiveSubscribeResponse:
    return json.loads(source)


@js.inline("{loader}.$operation ?? null")
def _operation_path(loader: callable) -> str | None:
    function = getattr(loader, "__func__", loader)
    operation = getattr(function, "__pyjs_operation__", None)
    receiver = getattr(loader, "__self__", None)
    if operation is None or receiver is None:
        return None
    return receiver._path + "/" + function.__name__


@js.inline("{loader}.$arguments ?? []")
def _operation_arguments(loader: callable) -> list[str]:
    function = getattr(loader, "__func__", loader)
    operation = getattr(function, "__pyjs_operation__", None)
    if operation is None:
        return []
    return [
        parameter.name
        for parameter in operation.signature.parameters.values()
        if parameter.name != "self"
    ]


@js.inline(
    "Object.fromEntries({names}.map((name, index) => "
    "[name, {values}[index]]))"
)
def _named_arguments(names: list[str], values: list[object]) -> object:
    return dict(zip(names, values, strict=False))


@js.inline(
    "{path}.slice({root}.length + 1).replaceAll('/', '.')"
)
def _relative_operation(path: str, root: str) -> str:
    return path[len(root) + 1 :].replace("/", ".")


@js.inline(
    "{loader}.$decode ? {loader}.$decode({value}) : {value}"
)
def _decode_result(loader: callable, value: object) -> object:
    return value


@js.inline(
    "{session}._subscriptions_changed.bind({session})"
)
def _subscription_callback(session: object) -> callable:
    return session._subscriptions_changed


@js.inline("{request}({identifier}, {path})")
def _live_request(
    request: callable,
    identifier: int,
    path: str,
) -> LiveQueryRequest | None:
    return request(identifier, path)


@js.inline(
    "{accept}({generation}, {value})"
)
def _accept_result(
    accept: callable,
    generation: int,
    value: object,
) -> bool:
    return accept(generation, value)


@js.inline(
    "new Promise((resolve) => setTimeout(resolve, {milliseconds}))"
)
async def _delay(milliseconds: int) -> None:
    await asyncio.sleep(milliseconds / 1000)


@js.inline("{loader}(...{args})")
def _start_query(
    loader: callable,
    args: list[object],
) -> Awaitable[object]:
    return asyncio.create_task(loader(*args))


@js.inline("{loader}().catch(() => {{}})")
def _start_live_refresh(loader: callable) -> None:
    task = asyncio.create_task(loader())
    task.add_done_callback(_consume_task)


def _consume_task(completed: asyncio.Task):
    if not completed.cancelled():
        completed.exception()


@js.inline("{pending}")
async def _await_query(pending: object) -> object:
    return await pending


@js
class WatchedQuery[Value]:
    def __init__(self, loader: callable, *args: object):
        self.current: Value | None = None
        self.loaded = False
        self.loading = False
        self.error: Exception | None = None
        self.stale = True
        self._loader = loader
        self.operation_path = _operation_path(loader)
        self.argument_names = _operation_arguments(loader)
        self.arguments: list[object] = []
        for argument in args:
            self.arguments.append(argument)
        self._update: callable | None = None
        self._pending: Awaitable[object] | None = None
        self._generation = 0
        self._subscription_changed: callable | None = None

    @js.inline("{value}")
    def _result(self, value: object) -> Value:
        return value

    async def refresh(self) -> Value:
        if self._pending is not None:
            return self._result(await _await_query(self._pending))

        self.loading = True
        self.error = None
        generation = self._generation
        self._pending = _start_query(self._loader, self.arguments)
        try:
            value = self._result(await _await_query(self._pending))
            self.current = value
            self.loaded = True
            self.stale = generation != self._generation
            if not self.stale and self._update is not None:
                self._update(value)
            return value
        except Exception as error:
            self.error = error
            raise error
        finally:
            self.loading = False
            self._pending = None

    async def get(self) -> Value:
        if not self.stale and self.loaded:
            return self._result(self.current)
        return await self.refresh()

    async def reload(self) -> Value:
        self.invalidate()
        value = await self.refresh()
        while self.stale:
            value = await self.refresh()
        return value

    def invalidate(self):
        self._generation += 1
        self.stale = True

    def set_args(self, *args: object) -> Self:
        self.arguments.clear()
        for argument in args:
            self.arguments.append(argument)
        self.invalidate()
        if self._subscription_changed is not None:
            self._subscription_changed()
        return self

    def on_update(self, callback: callable) -> Self:
        self._update = callback
        return self

    async def _refresh_current(self):
        try:
            while self.stale:
                await self.refresh()
        except Exception:
            pass

    def _refresh_live(self):
        _start_live_refresh(self._refresh_current)

    def _live_request(
        self,
        identifier: int,
        session_path: str,
    ) -> LiveQueryRequest | None:
        if self.operation_path is None:
            return None
        prefix = session_path + "/"
        if not self.operation_path.startswith(prefix):
            return None
        operation = _relative_operation(self.operation_path, session_path)
        return LiveQueryRequest(
            arguments=_named_arguments(self.argument_names, self.arguments),
            generation=self._generation,
            id=identifier,
            operation=operation,
        )

    def _accept_live(self, generation: int, value: object):
        if generation != self._generation or self._pending is not None:
            return False
        self.current = self._result(_decode_result(self._loader, value))
        self.loaded = True
        self.loading = False
        self.error = None
        self.stale = False
        if self._update is not None:
            self._update(self.current)
        return True

    def watch(self, session: LiveSession, *topics: str) -> Self:
        selected: list[str] = []
        for topic in topics:
            selected.append(topic)
        if not selected:
            selected.append("*")
        self._subscription_changed = _subscription_callback(session)
        session._add(
            self.invalidate,
            self._refresh_live,
            self._live_request,
            self._accept_live,
            selected,
        )
        return self


@js
class _LiveWatch:
    def __init__(
        self,
        invalidate: callable,
        refresh: callable,
        request: callable,
        accept: callable,
        topics: list[str],
    ):
        self.id = 0
        self._invalidate = invalidate
        self._refresh = refresh
        self._request = request
        self._accept = accept
        self.topics = topics

    def matches(self, topics: list[str]) -> bool:
        if "*" in topics or "*" in self.topics:
            return True
        for topic in topics:
            if topic in self.topics:
                return True
        return False

    def invalidate(self):
        self._invalidate()
        self._refresh()

    def mark_stale(self):
        self._invalidate()

    def request(self, session_path: str) -> LiveQueryRequest | None:
        return _live_request(
            self._request,
            self.id,
            session_path,
        )

    def subscription_request(
        self,
        session_path: str,
    ) -> LiveSubscriptionQuery | None:
        request = self.request(session_path)
        if request is None:
            return None
        return LiveSubscriptionQuery(
            arguments=request["arguments"],
            generation=request["generation"],
            id=request["id"],
            operation=request["operation"],
            topics=self.topics,
        )

    def refresh(self):
        self._refresh()

    def accept(self, result: LiveQueryResult) -> bool:
        return _accept_result(
            self._accept,
            result["generation"],
            result["value"],
        )


@js
class LiveSession:
    def __init__(self, path: str = "/api", *, autostart: bool = True):
        self.path = path
        if path.endswith("/"):
            self.path = path[:-1]
        self.autostart = autostart
        self.transport = "stopped"
        self.sequence = 0
        self._source: EventSource | None = None
        self._watches: list[_LiveWatch] = []
        self._next_watch_id = 1
        self._result_queries: list[LiveQueryRequest] = []
        self._result_refreshing = False
        self._subscription = ""
        self._subscription_version = 0
        self._subscription_syncing = False
        self._closed = False

    def _add(
        self,
        invalidate: callable,
        refresh: callable,
        request: callable,
        accept: callable,
        topics: list[str],
    ) -> None:
        watch = _LiveWatch(invalidate, refresh, request, accept, topics)
        watch.id = self._next_watch_id
        self._next_watch_id += 1
        self._watches.append(watch)
        if not self.autostart:
            return
        if watch.subscription_request(self.path) is not None:
            self._subscriptions_changed()
        elif self.transport == "stopped":
            self.start()

    def start(self):
        if self.transport != "stopped":
            return
        self._closed = False
        if self._subscription_queries():
            self._start_subscription_sync()
            return
        self._open_source("")

    def _open_source(self, subscription: str):
        path = self.path + "/_live/events"
        if subscription:
            path += "?subscription=" + encodeURIComponent(subscription)
        source = EventSource(path)
        source.addEventListener("invalidate", self._receive_event)
        source.addEventListener("result", self._receive_event)
        source.addEventListener("resync", self._receive_event)
        source.addEventListener("error", self._sse_failed)
        self._source = source
        self.transport = "sse"

    def close(self):
        self._closed = True
        if self._source is not None:
            self._source.close()
            self._source = None
        self.transport = "stopped"

    def _subscription_queries(self) -> list[LiveSubscriptionQuery]:
        queries: list[LiveSubscriptionQuery] = []
        for watch in self._watches:
            request = watch.subscription_request(self.path)
            if request is not None:
                queries.append(request)
        return queries

    # This method is retained because _subscription_callback binds it through
    # opaque inline JavaScript that the tree shaker cannot inspect.
    @js.keep
    def _subscriptions_changed(self):
        self._subscription_version += 1
        if self.autostart:
            self._start_subscription_sync()

    def _start_subscription_sync(self):
        if self._subscription_syncing:
            return
        self._subscription_syncing = True
        _start_live_refresh(self._sync_subscriptions)

    async def _sync_subscriptions(self):
        try:
            await _delay(0)
            while not self._closed:
                version = self._subscription_version
                queries = self._subscription_queries()
                if not queries:
                    if self.transport == "stopped":
                        self._open_source("")
                    return
                request = LiveSubscribeRequest(
                    queries=queries,
                    subscription=self._subscription,
                )
                try:
                    response = await fetch(
                        self.path + "/_live/subscribe",
                        {
                            "method": "POST",
                            "headers": {"Content-Type": "application/json"},
                            "body": _stringify_unchecked(request),
                        },
                    )
                    if not response.ok:
                        raise ValueError("Live subscription failed.")
                    message = _parse_live_subscribe(await response.text())
                    subscription = message["subscription"]
                except Exception:
                    if self.transport == "stopped":
                        self._open_source("")
                    return
                if version != self._subscription_version:
                    continue
                changed = subscription != self._subscription
                self._subscription = subscription
                if changed and self._source is not None:
                    self._source.close()
                    self._source = None
                    self.transport = "stopped"
                if self.transport == "stopped":
                    self._open_source(subscription)
                return
        finally:
            self._subscription_syncing = False

    def _receive_event(self, event: Event):
        if not isinstance(event, MessageEvent):
            return
        data = event.data
        if not isinstance(data, str):
            return
        self._receive(_parse_live_message(data))

    def _receive(self, message: LiveMessage):
        sequence = message["sequence"]
        if message["type"] != "resync" and sequence <= self.sequence:
            return
        self.sequence = sequence
        topics = message["topics"]
        results: list[LiveQueryResult] = []
        if message["type"] == "result":
            results = message["results"]
        for watch in self._watches:
            if not watch.matches(topics):
                continue
            accepted = False
            for result in results:
                if result["id"] == watch.id:
                    accepted = watch.accept(result)
                    break
            if accepted:
                continue
            watch.mark_stale()
            request = watch.request(self.path)
            if request is None:
                watch.refresh()
            else:
                self._queue_result(request)
        self._start_results()

    def _queue_result(self, query: LiveQueryRequest):
        index = 0
        while index < len(self._result_queries):
            pending = self._result_queries[index]
            if pending["id"] == query["id"]:
                self._result_queries[index] = query
                return
            index += 1
        self._result_queries.append(query)

    def _start_results(self):
        if self._result_refreshing or not self._result_queries:
            return
        self._result_refreshing = True
        _start_live_refresh(self._drain_results)

    async def _drain_results(self):
        try:
            while len(self._result_queries) > 0:
                queries = self._result_queries
                self._result_queries = []
                await self._refresh_results(queries)
        finally:
            self._result_refreshing = False

    def _watch(self, identifier: int) -> _LiveWatch | None:
        for watch in self._watches:
            if watch.id == identifier:
                return watch
        return None

    def _fallback(self, queries: list[LiveQueryRequest]):
        for query in queries:
            watch = self._watch(query["id"])
            if watch is not None:
                watch.refresh()

    async def _refresh_results(self, queries: list[LiveQueryRequest]):
        request = LiveRefreshRequest(queries=queries)
        try:
            response = await fetch(
                self.path + "/_live/refresh",
                {
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body": _stringify_unchecked(request),
                },
            )
            if not response.ok:
                self._fallback(queries)
                return
            message = _parse_live_refresh(await response.text())
            for result in message["results"]:
                watch = self._watch(result["id"])
                if watch is not None:
                    if not watch.accept(result):
                        watch.refresh()
        except Exception:
            self._fallback(queries)

    async def _sse_failed(self, event: Event):
        if self.transport != "sse":
            return
        if self._source is not None:
            self._source.close()
            self._source = None
        self.transport = "poll"
        await self._poll()

    async def _poll(self):
        while not self._closed and self.transport == "poll":
            try:
                response = await fetch(
                    self.path + "/_live/poll?after=" + str(self.sequence)
                )
                if response.status == 204:
                    continue
                if not response.ok:
                    await _delay(1000)
                    continue
                self._receive(_parse_live_message(await response.text()))
            except Exception:
                await _delay(1000)
