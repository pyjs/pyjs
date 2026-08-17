import json

from asgiref.sync import sync_to_async
from django.http import JsonResponse
from django.urls import path
from pydantic import ValidationError

from pyjs.server import (
    OperationError,
    OperationIssue,
    dispatch_operation,
    operation_error,
)
from pyjs.server.django.jsonapi import encode_jsonapi_queryset
from pyjs.server.django.live import live_urls_for, publish_after_commit
from pyjs.server.django.queryset import QuerySetResult
from pyjs.server.jsonapi import encode_jsonapi_values
from pyjs.server.live import (
    InvalidationHub,
    api_topic,
    default_invalidation_hub,
    resource_topic,
)


def _error_response(error: Exception, status: int = 400) -> JsonResponse:
    if isinstance(error, OperationError):
        return JsonResponse(error.payload(), status=error.status())
    if isinstance(error, ValidationError):
        issues = []
        for issue in error.errors(include_url=False):
            issues.append(
                OperationIssue(
                    issue["msg"],
                    [str(part) for part in issue["loc"]],
                    422,
                    "Validation error",
                    issue["type"],
                )
            )
        return _error_response(OperationError(issues))
    return _error_response(
        operation_error(
            str(error),
            status=status,
            title="Invalid request",
        )
    )


def _operation_view(root_type, operation, invalidation_hub: InvalidationHub):
    async def view(request):
        try:
            if request.method != "POST":
                return _error_response(
                    TypeError("RPC operations require POST."),
                    status=405,
                )
            payload = json.loads(request.body or b"{}")
            if not isinstance(payload, dict):
                raise TypeError("The request body must be a JSON object.")

            data = await _operation_result(root_type, operation, payload, request)
            if operation.kind != "query":
                await sync_to_async(
                    publish_after_commit,
                    thread_sensitive=True,
                )(
                    invalidation_hub,
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
        except (OperationError, ValidationError, TypeError, ValueError) as error:
            return _error_response(error)

    view.__name__ = operation.identity.replace(".", "_")
    return view


async def _operation_result(root_type, operation, payload, request):
    data = await dispatch_operation(
        root_type,
        operation.identity,
        payload,
        request,
        serialize=not operation.operation.jsonapi,
    )
    if not operation.operation.jsonapi:
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


def urls_for(api, invalidation_hub: InvalidationHub | None = None):
    if invalidation_hub is None:
        invalidation_hub = default_invalidation_hub
    patterns = []
    for operation in api.resource_graph.operations:
        route = "/".join((*operation.owner.path, operation.name))
        patterns.append(
            path(
                route,
                _operation_view(type(api), operation, invalidation_hub),
            )
        )
    patterns.extend(
        live_urls_for(type(api), invalidation_hub, _operation_result)
    )
    return patterns
