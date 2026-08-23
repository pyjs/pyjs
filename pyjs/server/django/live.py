import asyncio
import inspect
import json
import secrets
import threading

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import (
    HttpResponse,
    HttpResponseNotAllowed,
    JsonResponse,
    StreamingHttpResponse,
)
from django.urls import path

from pyjs.server import operation_error, resource_graph
from pyjs.server.django.errors import exception_response
from pyjs.server.live import (
    Invalidation,
    InvalidationBackend,
    InvalidationPayload,
    InvalidationSubscription,
    api_topic,
)

SSE_HEARTBEAT_SECONDS = 15.0
SSE_RETRY_MILLISECONDS = 3000
LONG_POLL_SECONDS = 25.0
MAX_LIVE_REFRESH_QUERIES = 100
MAX_LIVE_SUBSCRIPTIONS = 1024


class _LiveQueryRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._queries: dict[str, tuple[dict, ...]] = {}

    def register(self, queries: list[dict], subscription: str | None) -> str:
        with self._lock:
            if subscription and subscription in self._queries:
                del self._queries[subscription]
            else:
                subscription = secrets.token_urlsafe(24)
                if len(self._queries) >= MAX_LIVE_SUBSCRIPTIONS:
                    del self._queries[next(iter(self._queries))]
            self._queries[subscription] = tuple(queries)
            return subscription

    def queries(self, subscription: str | None) -> tuple[dict, ...] | None:
        if not subscription:
            return None
        with self._lock:
            queries = self._queries.pop(subscription, None)
            if queries is not None:
                self._queries[subscription] = queries
            return queries


def publish_after_commit(
    backend: InvalidationBackend,
    topics: tuple[str, ...],
    *,
    using: str | None = None,
):
    unique_topics = tuple(dict.fromkeys(topics))
    if unique_topics:
        transaction.on_commit(
            lambda: backend.publish(*unique_topics),
            using=using,
        )


def _cursor(request) -> int | None:
    value = request.headers.get("Last-Event-ID") or request.GET.get("after")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return -1


def _initial_payload(
    backend: InvalidationBackend,
    cursor: int | None,
    topic: str,
) -> InvalidationPayload | None:
    sequence = backend.sequence
    if cursor is None or cursor == sequence:
        return None
    replay = getattr(backend, "replay", None)
    if replay is not None:
        invalidations = replay(cursor, topic)
        if invalidations is not None:
            if not invalidations:
                return None
            topics = tuple(
                dict.fromkeys(
                    changed_topic
                    for invalidation in invalidations
                    for changed_topic in invalidation.topics
                )
            )
            return _public_payload(
                topic,
                Invalidation(invalidations[-1].sequence, topics),
            )
    return {
        "sequence": sequence,
        "topics": ["*"],
        "type": "resync",
    }


def _public_payload(topic: str, invalidation: Invalidation) -> InvalidationPayload:
    payload = invalidation.payload()
    payload["topics"] = [
        "*" if value == topic else value.removeprefix(topic + ":")
        for value in invalidation.topics
        if value == topic or value.startswith(topic + ":")
    ]
    return payload


def _sse_message(payload: InvalidationPayload) -> str:
    return (
        f"id: {payload['sequence']}\n"
        f"event: {payload['type']}\n"
        f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
    )


async def _event_stream(
    subscription: InvalidationSubscription,
    topic: str,
    resync: InvalidationPayload | None,
    heartbeat: float = SSE_HEARTBEAT_SECONDS,
    result_payload=None,
    live_access=None,
):
    try:
        yield f"retry: {SSE_RETRY_MILLISECONDS}\n\n"
        if resync is not None:
            if live_access is not None:
                try:
                    if not await live_access():
                        return
                except Exception:
                    return
            if result_payload is not None:
                resync = await result_payload(resync)
            yield _sse_message(resync)
        while True:
            try:
                invalidation = await asyncio.wait_for(
                    subscription.receive(),
                    heartbeat,
                )
            except TimeoutError:
                invalidation = None
            if live_access is not None:
                try:
                    if not await live_access():
                        return
                except Exception:
                    return
            if invalidation is None:
                yield ": keepalive\n\n"
                continue
            payload = _public_payload(topic, invalidation)
            if result_payload is not None:
                payload = await result_payload(payload)
            yield _sse_message(payload)
    finally:
        subscription.close()


def _sse_view(
    root_type,
    backend: InvalidationBackend,
    operation_result,
    registrations: _LiveQueryRegistry,
    live_authorize,
):
    graph = resource_graph(root_type)

    async def view(request):
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET"])
        try:
            await _require_live_access(live_authorize, request)
        except Exception as error:
            return exception_response(error)
        topic = api_topic(root_type)
        subscription = backend.subscribe(topic)
        subscription_id = request.GET.get("subscription")

        async def result_payload(payload):
            queries = registrations.queries(subscription_id)
            if queries is None:
                return payload
            try:
                results = []
                for query in queries:
                    if not _topics_match(query["topics"], payload["topics"]):
                        continue
                    operation = graph.operations_by_identity[query["operation"]]
                    value = await operation_result(
                        root_type,
                        operation,
                        query["arguments"],
                        request,
                    )
                    results.append(
                        {
                            "generation": query["generation"],
                            "id": query["id"],
                            "value": value,
                        }
                    )
                return {
                    "results": results,
                    "sequence": payload["sequence"],
                    "topics": payload["topics"],
                    "type": "result",
                }
            except Exception:
                return payload

        response = StreamingHttpResponse(
            _event_stream(
                subscription,
                topic,
                _initial_payload(backend, _cursor(request), topic),
                result_payload=result_payload,
                live_access=(
                    None
                    if live_authorize is None
                    else lambda: _live_access(live_authorize, request)
                ),
            ),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache, no-store, no-transform"
        response["X-Accel-Buffering"] = "no"
        response["Vary"] = "Cookie"
        return response

    return view


def _topics_match(watched: list[str], changed: list[str]) -> bool:
    return "*" in watched or "*" in changed or bool(set(watched) & set(changed))


def _long_poll_view(root_type, backend: InvalidationBackend, live_authorize):
    async def view(request):
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET"])
        try:
            await _require_live_access(live_authorize, request)
        except Exception as error:
            return exception_response(error)
        topic = api_topic(root_type)
        subscription = backend.subscribe(topic)
        try:
            initial = _initial_payload(backend, _cursor(request), topic)
            if initial is not None:
                response = JsonResponse(initial)
                response["Cache-Control"] = "no-cache, no-store"
                response["Vary"] = "Cookie"
                return response
            try:
                invalidation = await asyncio.wait_for(
                    subscription.receive(),
                    LONG_POLL_SECONDS,
                )
            except TimeoutError:
                response = HttpResponse(status=204)
            else:
                await _require_live_access(live_authorize, request)
                response = JsonResponse(_public_payload(topic, invalidation))
            response["Cache-Control"] = "no-cache, no-store"
            response["Vary"] = "Cookie"
            return response
        except Exception as error:
            response = exception_response(error)
            response["Cache-Control"] = "no-cache, no-store"
            response["Vary"] = "Cookie"
            return response
        finally:
            subscription.close()

    return view


def _live_queries(
    root_type,
    payload,
    *,
    request_name: str,
    require_topics: bool,
) -> list[dict]:
    graph = resource_graph(root_type)
    if not isinstance(payload, dict):
        raise TypeError(f"The live {request_name} body must be an object.")
    queries = payload.get("queries")
    if not isinstance(queries, list):
        raise TypeError(f"Live {request_name} queries must be a list.")
    if len(queries) > MAX_LIVE_REFRESH_QUERIES:
        raise TypeError(
            f"A live {request_name} can contain at most "
            f"{MAX_LIVE_REFRESH_QUERIES} queries."
        )
    normalized = []
    for query in queries:
        if not isinstance(query, dict):
            raise TypeError(f"Each live {request_name} query must be an object.")
        operation = graph.operations_by_identity.get(query.get("operation"))
        if operation is None or operation.kind != "query":
            raise TypeError(
                f"Live {request_name} requires a known query operation."
            )
        identifier = query.get("id")
        generation = query.get("generation")
        arguments = query.get("arguments")
        if not isinstance(identifier, int) or not isinstance(generation, int):
            raise TypeError(f"Live {request_name} identifiers must be integers.")
        if not isinstance(arguments, dict):
            raise TypeError(f"Live {request_name} arguments must be an object.")
        normalized_query = {
            "arguments": arguments,
            "generation": generation,
            "id": identifier,
            "operation": operation.identity,
        }
        if require_topics:
            topics = query.get("topics")
            if (
                not isinstance(topics, list)
                or not topics
                or not all(isinstance(topic, str) for topic in topics)
            ):
                raise TypeError("Live subscription topics must be strings.")
            normalized_query["topics"] = list(dict.fromkeys(topics))
        normalized.append(normalized_query)
    return normalized


def _live_request(
    root_type,
    request,
    *,
    request_name: str,
    require_topics: bool,
) -> tuple[dict, list[dict]]:
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise operation_error(
            f"The live {request_name} body is not valid JSON.",
            status=400,
            title="Invalid request",
        ) from None
    try:
        queries = _live_queries(
            root_type,
            payload,
            request_name=request_name,
            require_topics=require_topics,
        )
    except (TypeError, ValueError) as error:
        raise operation_error(
            str(error),
            status=400,
            title="Invalid request",
        ) from error
    return payload, queries


def _refresh_view(root_type, operation_result, live_authorize):
    graph = resource_graph(root_type)

    async def view(request):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        try:
            await _require_live_access(live_authorize, request)
            _, queries = _live_request(
                root_type,
                request,
                request_name="refresh",
                require_topics=False,
            )
            results = []
            for query in queries:
                operation = graph.operations_by_identity[query["operation"]]
                value = await operation_result(
                    root_type,
                    operation,
                    query["arguments"],
                    request,
                )
                results.append(
                    {
                        "generation": query["generation"],
                        "id": query["id"],
                        "value": value,
                    }
                )
            response = JsonResponse({"results": results})
        except Exception as error:
            response = exception_response(error)
        response["Cache-Control"] = "no-cache, no-store"
        response["Vary"] = "Cookie"
        return response

    return view


def _subscribe_view(root_type, registrations: _LiveQueryRegistry, live_authorize):
    async def view(request):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        try:
            await _require_live_access(live_authorize, request)
            payload, queries = _live_request(
                root_type,
                request,
                request_name="subscription",
                require_topics=True,
            )
            subscription = payload.get("subscription")
            if not isinstance(subscription, str):
                subscription = None
            token = registrations.register(queries, subscription)
            response = JsonResponse({"subscription": token})
        except Exception as error:
            response = exception_response(error)
        response["Cache-Control"] = "no-cache, no-store"
        response["Vary"] = "Cookie"
        return response

    return view


async def _live_access(live_authorize, request) -> bool:
    if live_authorize is None:
        return True
    result = live_authorize(request)
    if inspect.isawaitable(result):
        result = await result
    return bool(result)


async def _require_live_access(live_authorize, request):
    if not await _live_access(live_authorize, request):
        raise PermissionDenied


def live_urls_for(
    root_type,
    backend: InvalidationBackend,
    operation_result,
    live_authorize=None,
):
    registrations = _LiveQueryRegistry()
    return [
        path(
            "_live/events",
            _sse_view(
                root_type,
                backend,
                operation_result,
                registrations,
                live_authorize,
            ),
            name="pyjs_live_events",
        ),
        path(
            "_live/poll",
            _long_poll_view(root_type, backend, live_authorize),
            name="pyjs_live_poll",
        ),
        path(
            "_live/refresh",
            _refresh_view(root_type, operation_result, live_authorize),
            name="pyjs_live_refresh",
        ),
        path(
            "_live/subscribe",
            _subscribe_view(root_type, registrations, live_authorize),
            name="pyjs_live_subscribe",
        ),
    ]
