import json
from collections.abc import Awaitable, Callable

from asgiref.sync import async_to_sync, sync_to_async
from django.db import transaction
from django.http import JsonResponse
from django.urls import path
from pydantic import TypeAdapter

from pyjs.server import (
    API,
    OperationError,
    OperationIssue,
    Stream,
    dispatch_operation,
    operation_error,
)
from pyjs.server.django.errors import error_response, exception_response
from pyjs.server.django.jsonapi import encode_jsonapi_queryset
from pyjs.server.django.live import live_urls_for, publish_after_commit
from pyjs.server.django.queryset import (
    CursorPaginationError,
    QuerySetPageResult,
    QuerySetResult,
    encode_queryset_page,
)
from pyjs.server.django.stream import stream_response
from pyjs.server.jsonapi import encode_jsonapi_values
from pyjs.server.live import (
    InvalidationBackend,
    api_topic,
    default_invalidation_backend,
    resource_topic,
)


def _request_error(detail: str, status: int = 400) -> JsonResponse:
    return error_response(
        operation_error(
            detail,
            status=status,
            title="Invalid request",
        )
    )


def _request_payload(request) -> dict:
    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        raise operation_error(
            "The request body is not valid JSON.",
            status=400,
            title="Invalid request",
        ) from None
    if not isinstance(payload, dict):
        raise operation_error(
            "The request body must be a JSON object.",
            status=400,
            title="Invalid request",
        )
    return payload


def _stream_request_payload(request) -> dict:
    source = request.GET.get("arguments", "{}")
    try:
        payload = json.loads(source)
    except json.JSONDecodeError:
        raise operation_error(
            "The stream arguments are not valid JSON.",
            status=400,
            title="Invalid request",
        ) from None
    if not isinstance(payload, dict):
        raise operation_error(
            "Stream arguments must be a JSON object.",
            status=400,
            title="Invalid request",
        )
    return payload


def csrf_failure(request, reason: str = "") -> JsonResponse:
    """Return a structured operation error for Django CSRF rejection."""
    return error_response(
        operation_error(
            "The request could not be verified. Reload the page and try again.",
            status=403,
            title="CSRF verification failed",
            code="csrf_failed",
        )
    )


def _operation_view(root_type, operation, backend: InvalidationBackend):
    async def view(request):
        try:
            if request.method != "POST":
                return _request_error("RPC operations require POST.", 405)
            payload = _request_payload(request)
            data = await _operation_result(root_type, operation, payload, request)
            if operation.kind != "query":
                await sync_to_async(
                    publish_after_commit,
                    thread_sensitive=True,
                )(
                    backend,
                    (
                        api_topic(root_type),
                        resource_topic(root_type, operation.owner.path),
                    ),
                )
            if operation.operation.jsonapi:
                response = JsonResponse(
                    data,
                    content_type="application/vnd.api+json",
                )
            else:
                response = JsonResponse(data, safe=False)
            return response
        except Exception as error:
            return exception_response(error)

    view.__name__ = operation.identity.replace(".", "_")
    return view


def _stream_operation_view(root_type, operation):
    async def view(request):
        try:
            if request.method != "GET":
                return _request_error("Stream operations require GET.", 405)
            binding = await dispatch_operation(
                root_type,
                operation.identity,
                _stream_request_payload(request),
                request,
                serialize=False,
            )
            if not isinstance(binding, Stream):
                raise TypeError("A stream operation returned an invalid binding.")
            adapter = TypeAdapter(operation.operation.stream_value_type)

            def serialize(value):
                value = adapter.validate_python(value)
                return adapter.dump_python(value, mode="json")

            return await stream_response(
                binding.backend,
                binding.scope,
                request,
                access=binding.authorize,
                serialize=serialize,
                heartbeat=binding.heartbeat,
                buffer_limit=binding.buffer_limit,
            )
        except Exception as error:
            return exception_response(error)

    view.__name__ = operation.identity.replace(".", "_")
    return view


def _atomic_issue(error: OperationError, index: int) -> OperationError:
    return OperationError(
        [
            OperationIssue(
                issue.detail,
                ["operations", str(index), "arguments", *issue.location],
                issue.status,
                issue.title,
                issue.code,
            )
            for issue in error.issues
        ]
    )


def _atomic_results(root_type, operations, request):
    if not isinstance(operations, list) or not operations:
        raise operation_error(
            "Atomic requests require at least one operation.",
            "operations",
            code="empty_atomic_request",
        )
    graph = root_type().resource_graph
    results = []
    changed_paths = []
    with transaction.atomic():
        for index, descriptor in enumerate(operations):
            if not isinstance(descriptor, dict):
                raise operation_error(
                    "Each atomic operation must be an object.",
                    "operations",
                    str(index),
                    code="invalid_atomic_operation",
                )
            identity = descriptor.get("operation")
            values = descriptor.get("arguments")
            operation = graph.operations_by_identity.get(identity)
            if operation is None:
                raise operation_error(
                    "Unknown atomic operation: " + str(identity) + ".",
                    "operations",
                    str(index),
                    "operation",
                    code="unknown_atomic_operation",
                )
            if operation.kind != "mutation":
                raise operation_error(
                    "Atomic batches only accept mutations.",
                    "operations",
                    str(index),
                    "operation",
                    code="invalid_atomic_operation_kind",
                )
            try:
                result = async_to_sync(_operation_result)(
                    root_type,
                    operation,
                    values,
                    request,
                )
            except OperationError as error:
                raise _atomic_issue(error, index) from error
            results.append(result)
            changed_paths.append(operation.owner.path)
    return results, changed_paths


def _atomic_view(root_type, backend: InvalidationBackend):
    async def view(request):
        try:
            if request.method != "POST":
                return _request_error("RPC operations require POST.", 405)
            payload = _request_payload(request)
            results, changed_paths = await sync_to_async(
                _atomic_results,
                thread_sensitive=True,
            )(root_type, payload.get("operations"), request)
            await sync_to_async(
                publish_after_commit,
                thread_sensitive=True,
            )(
                backend,
                (
                    api_topic(root_type),
                    *(
                        resource_topic(root_type, path)
                        for path in changed_paths
                    ),
                ),
            )
            return JsonResponse(results, safe=False)
        except Exception as error:
            return exception_response(error)

    view.__name__ = "atomic"
    return view


async def _operation_result(root_type, operation, payload, request):
    data = await dispatch_operation(
        root_type,
        operation.identity,
        payload,
        request,
        serialize=not operation.operation.jsonapi,
        defer_result=True,
    )
    if not operation.operation.jsonapi:
        if isinstance(data, QuerySetPageResult):
            try:
                return await sync_to_async(encode_queryset_page)(
                    data,
                    operation.operation.signature.return_annotation,
                )
            except CursorPaginationError as error:
                raise operation_error(
                    str(error),
                    status=422,
                    code="invalid_cursor",
                ) from error
        if isinstance(data, QuerySetResult):
            raise TypeError(
                "queryset_result() requires an operation returning its "
                "resource model."
            )
        return data
    if isinstance(data, QuerySetResult):
        return await sync_to_async(encode_jsonapi_queryset)(
            root_type,
            operation.owner.resource_type,
            data.queryset,
            data.include_paths,
            many=operation.operation.jsonapi_many,
        )
    return encode_jsonapi_values(
        root_type,
        operation.owner.resource_type,
        data,
        many=operation.operation.jsonapi_many,
    )


def urls_for(
    api: API,
    invalidation_backend: InvalidationBackend | None = None,
    *,
    live_authorize: Callable[[object], bool | Awaitable[bool]] | None = None,
) -> list[object]:
    """Create Django URL patterns for a typed API hierarchy.

    Args:
        api: Root API instance to expose.
        invalidation_backend: Live invalidation backend, or the process-local
            default when omitted.
        live_authorize: Optional request authorization callback for live data.

    Returns:
        Django URL patterns for operations, atomic batches, SSE, and polling.
    """
    if invalidation_backend is None:
        invalidation_backend = default_invalidation_backend
    patterns = []
    patterns.append(path("atomic", _atomic_view(type(api), invalidation_backend)))
    for operation in api.resource_graph.operations:
        route = "/".join((*operation.owner.path, operation.name))
        if operation.kind == "stream":
            view = _stream_operation_view(type(api), operation)
        else:
            view = _operation_view(type(api), operation, invalidation_backend)
        patterns.append(
            path(
                route,
                view,
            )
        )
    patterns.extend(
        live_urls_for(
            type(api),
            invalidation_backend,
            _operation_result,
            live_authorize,
        )
    )
    return patterns
