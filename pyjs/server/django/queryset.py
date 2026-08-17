from collections.abc import Sequence
from typing import Any

from django.db.models import QuerySet


class QuerySetResult:
    __pyjs_deferred_operation_result__ = True

    def __init__(
        self,
        queryset: QuerySet,
        include_paths: Sequence[str] = (),
    ):
        if not isinstance(queryset, QuerySet):
            raise TypeError("queryset_result() requires a Django QuerySet.")
        if isinstance(include_paths, str):
            raise TypeError("include_paths must be a sequence, not a string.")
        self.queryset = queryset
        self.include_paths = tuple(include_paths)


# The operation's annotation remains the client-facing Pydantic result type.
def queryset_result(
    queryset: QuerySet,
    *,
    include_paths: Sequence[str] = (),
) -> Any:
    return QuerySetResult(queryset, include_paths)
