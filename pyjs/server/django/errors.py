import logging

from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse

from pyjs.server.errors import OperationError, OperationIssue

logger = logging.getLogger("pyjs.server")


def error_response(error: OperationError) -> JsonResponse:
    return JsonResponse(error.payload(), status=error.status())


def _response(
    detail: str,
    status: int,
    title: str,
    code: str,
) -> JsonResponse:
    return error_response(
        OperationError([OperationIssue(detail, [], status, title, code)])
    )


def exception_response(error: Exception) -> JsonResponse:
    if isinstance(error, OperationError):
        return error_response(error)
    if isinstance(error, PermissionDenied):
        return _response(
            "You do not have permission to perform this operation.",
            403,
            "Permission denied",
            "permission_denied",
        )
    if isinstance(error, Http404):
        return _response(
            "The requested resource was not found.",
            404,
            "Not found",
            "not_found",
        )
    logger.exception("PyJS operation failed", exc_info=error)
    return _response(
        "The server could not complete the operation.",
        500,
        "Server error",
        "server_error",
    )
