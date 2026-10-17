import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseNotAllowed, StreamingHttpResponse

from pyjs.server.django.errors import exception_response
from pyjs.server.protocol import StreamResyncPayload
from pyjs.server.stream import (
    StreamBackend,
    StreamEvent,
    StreamResyncRequired,
    StreamSubscription,
)
from pyjs.server.stream_binding import StreamFeed

STREAM_HEARTBEAT_SECONDS = 15.0
STREAM_RETRY_MILLISECONDS = 3000

logger = logging.getLogger(__name__)

type ScopeResolver = str | Callable[..., str | Awaitable[str]]
type StreamAuthorizer = Callable[[object, str], bool | Awaitable[bool]]
type StreamSerializer[Value] = Callable[[Value], object]
type StreamAccess = Callable[[], bool | Awaitable[bool]]


def publish_stream_after_commit[Value, Request, Result](
    feed: StreamFeed[Value, Request, Result],
    value: Value,
    *,
    using: str | None = None,
):
    """Publish an ordered event after the current transaction commits."""
    transaction.on_commit(
        lambda: feed.publish(value),
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


async def _scope(scope: ScopeResolver, request, values: dict[str, object]) -> str:
    if isinstance(scope, str):
        return scope
    result = scope(request, **values)
    if inspect.isawaitable(result):
        result = await result
    return result


async def _require_access(
    authorize: StreamAuthorizer | None,
    request,
    scope: str,
) -> None:
    if authorize is None:
        return
    result = authorize(request, scope)
    if inspect.isawaitable(result):
        result = await result
    if not result:
        raise PermissionDenied


async def _require_stream_access(access: StreamAccess | None) -> None:
    if access is None:
        return
    result = access()
    if inspect.isawaitable(result):
        result = await result
    if not result:
        raise PermissionDenied


def _message(payload: object, sequence: int, event_type: str) -> str:
    return (
        f"id: {sequence}\n"
        f"event: {event_type}\n"
        f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
    )


def _event_payload[Value](
    event: StreamEvent[Value],
    serialize: StreamSerializer[Value] | None,
) -> dict[str, object]:
    payload = event.payload()
    if serialize is not None:
        payload["value"] = serialize(event.value)
    return payload


async def _event_stream[Value](
    backend: StreamBackend[Value],
    subscription: StreamSubscription[Value],
    scope: str,
    access: StreamAccess | None,
    serialize: StreamSerializer[Value] | None,
    resync: StreamResyncPayload | None,
    heartbeat: float,
):
    try:
        yield f"retry: {STREAM_RETRY_MILLISECONDS}\n\n"
        if resync is not None:
            try:
                await _require_stream_access(access)
            except Exception:
                return
            yield _message(resync, resync["sequence"], "resync")
        while True:
            try:
                event = await asyncio.wait_for(
                    subscription.receive(),
                    heartbeat,
                )
            except TimeoutError:
                try:
                    await _require_stream_access(access)
                except Exception:
                    return
                yield ": keepalive\n\n"
                continue
            except StreamResyncRequired:
                try:
                    await _require_stream_access(access)
                except Exception:
                    return
                sequence = await asyncio.to_thread(backend.watermark, scope)
                payload = StreamResyncPayload(
                    scope=scope,
                    sequence=sequence,
                    type="resync",
                    value=None,
                )
                yield _message(payload, sequence, "resync")
                return
            try:
                await _require_stream_access(access)
            except Exception:
                return
            try:
                message = _message(
                    _event_payload(event, serialize),
                    event.sequence,
                    "event",
                )
            except Exception:
                logger.exception(
                    "Could not serialize stream %r sequence %d; "
                    "requiring resynchronization.",
                    scope,
                    event.sequence,
                )
                payload = StreamResyncPayload(
                    scope=scope,
                    sequence=event.sequence,
                    type="resync",
                    value=None,
                )
                yield _message(payload, event.sequence, "resync")
                return
            yield message
    finally:
        subscription.close()


async def stream_response[Value](
    backend: StreamBackend[Value],
    scope: str,
    request,
    *,
    access: StreamAccess | None = None,
    serialize: StreamSerializer[Value] | None = None,
    heartbeat: float = STREAM_HEARTBEAT_SECONDS,
    buffer_limit: int = 256,
):
    """Create one authorized SSE response for an already resolved stream."""
    await _require_stream_access(access)
    cursor = _cursor(request)
    resync = None
    try:
        subscription = await asyncio.to_thread(
            backend.subscribe,
            scope,
            after=cursor,
            buffer_limit=buffer_limit,
        )
    except StreamResyncRequired:
        subscription = await asyncio.to_thread(
            backend.subscribe,
            scope,
            buffer_limit=buffer_limit,
        )
        resync = StreamResyncPayload(
            scope=scope,
            sequence=subscription.sequence,
            type="resync",
            value=None,
        )

    response = StreamingHttpResponse(
        _event_stream(
            backend,
            subscription,
            scope,
            access,
            serialize,
            resync,
            heartbeat,
        ),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache, no-store, no-transform"
    response["X-Accel-Buffering"] = "no"
    response["Vary"] = "Cookie"
    return response


def stream_view[Value](
    backend: StreamBackend[Value],
    scope: ScopeResolver,
    *,
    authorize: StreamAuthorizer | None = None,
    serialize: StreamSerializer[Value] | None = None,
    heartbeat: float = STREAM_HEARTBEAT_SECONDS,
    buffer_limit: int = 256,
):
    """Build a Django SSE view over an ordered stream backend.

    The scope may be a fixed string or a resolver accepting the request and
    Django path parameters. Authorization is checked before subscribing and
    again before every delivery or heartbeat.
    """
    if heartbeat <= 0:
        raise ValueError("The stream heartbeat must be positive.")
    if buffer_limit <= 0:
        raise ValueError("The stream buffer limit must be positive.")

    async def view(request, **values):
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET"])
        try:
            resolved_scope = await _scope(scope, request, values)

            async def access():
                await _require_access(authorize, request, resolved_scope)
                return True

            return await stream_response(
                backend,
                resolved_scope,
                request,
                access=access,
                serialize=serialize,
                heartbeat=heartbeat,
                buffer_limit=buffer_limit,
            )
        except Exception as error:
            return exception_response(error)

    view.__name__ = "pyjs_stream"
    return view
