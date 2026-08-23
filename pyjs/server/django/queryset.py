import hashlib
import json
import types
from collections.abc import Sequence
from typing import Union, cast, get_args, get_origin

from asgiref.sync import sync_to_async
from django.core import signing
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q, QuerySet
from pydantic import TypeAdapter

from pyjs.server.pagination import CursorPageRequest, Page


class CursorPaginationError(ValueError):
    pass


class QuerySetResult:
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

    async def materialize_operation_result(self, result_type: object):
        return await sync_to_async(
            materialize_queryset_result,
            thread_sensitive=True,
        )(self, result_type)


class QuerySetPageResult:
    def __init__(
        self,
        queryset: QuerySet,
        request: CursorPageRequest,
        order_by: Sequence[str] = (),
        include_total: bool = False,
    ):
        if not isinstance(queryset, QuerySet):
            raise TypeError("queryset_page() requires a Django QuerySet.")
        if not isinstance(request, CursorPageRequest):
            raise TypeError("queryset_page() requires a CursorPageRequest.")
        if isinstance(order_by, str):
            raise TypeError("order_by must be a sequence, not a string.")
        self.queryset = queryset
        self.request = request
        self.order_by = tuple(order_by)
        self.include_total = include_total

    async def materialize_operation_result(self, result_type: object):
        return await sync_to_async(
            materialize_queryset_page,
            thread_sensitive=True,
        )(self, result_type)


class _CursorSerializer:
    @staticmethod
    def dumps(value) -> bytes:
        return json.dumps(
            value,
            cls=DjangoJSONEncoder,
            separators=(",", ":"),
        ).encode()

    @staticmethod
    def loads(value: bytes):
        return json.loads(value.decode())


def _normalized_ordering(result: QuerySetPageResult) -> tuple[str, ...]:
    ordering = result.order_by or tuple(result.queryset.query.order_by)
    if not ordering:
        ordering = tuple(result.queryset.model._meta.ordering or ())
    if not ordering:
        ordering = ("pk",)
    if any(not isinstance(value, str) for value in ordering):
        raise TypeError("Cursor ordering must use Django field names.")
    if any(value == "?" or "__" in value for value in ordering):
        raise TypeError(
            "Cursor ordering supports direct Django model fields only."
        )

    model = result.queryset.model
    pk = model._meta.pk
    names = []
    has_pk = False
    for value in ordering:
        descending = value.startswith("-")
        name = value[1:] if descending else value
        field = pk if name == "pk" else model._meta.get_field(name)
        if field.is_relation or field.null:
            raise TypeError(
                f"Cursor ordering field {model.__name__}.{name} must be a "
                "non-null scalar field."
            )
        has_pk = has_pk or field is pk
        names.append(("-" if descending else "") + field.attname)
    if not has_pk:
        prefix = "-" if names[-1].startswith("-") else ""
        names.append(prefix + pk.attname)
    return tuple(names)


def _query_fingerprint(queryset: QuerySet, ordering: tuple[str, ...]) -> str:
    sql, parameters = queryset.order_by().query.sql_with_params()
    source = json.dumps(
        (sql, parameters, ordering),
        cls=DjangoJSONEncoder,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(source).hexdigest()


def _cursor_values(instance, ordering: tuple[str, ...]) -> list[object]:
    return [
        getattr(instance, name[1:] if name.startswith("-") else name)
        for name in ordering
    ]


def _encode_cursor(
    instance,
    ordering: tuple[str, ...],
    fingerprint: str,
) -> str:
    return signing.dumps(
        {
            "ordering": ordering,
            "query": fingerprint,
            "values": _cursor_values(instance, ordering),
        },
        salt="pyjs.cursor-page",
        serializer=_CursorSerializer,
        compress=True,
    )


def _decode_cursor(
    value: str,
    ordering: tuple[str, ...],
    fingerprint: str,
) -> list[object]:
    try:
        payload = signing.loads(
            value,
            salt="pyjs.cursor-page",
            serializer=_CursorSerializer,
        )
    except signing.BadSignature as error:
        raise CursorPaginationError("Invalid pagination cursor.") from error
    if (
        not isinstance(payload, dict)
        or tuple(payload.get("ordering", ())) != ordering
        or payload.get("query") != fingerprint
        or not isinstance(payload.get("values"), list)
        or len(payload["values"]) != len(ordering)
    ):
        raise CursorPaginationError("Pagination cursor does not match this query.")
    return payload["values"]


def _cursor_filter(
    ordering: tuple[str, ...],
    values: list[object],
    *,
    after: bool,
) -> Q:
    result = None
    equal = Q()
    for ordering_value, value in zip(ordering, values, strict=True):
        descending = ordering_value.startswith("-")
        name = ordering_value[1:] if descending else ordering_value
        greater = after != descending
        comparison = "gt" if greater else "lt"
        branch = equal & Q(**{f"{name}__{comparison}": value})
        result = branch if result is None else result | branch
        equal &= Q(**{name: value})
    assert result is not None
    return result


def _reverse_ordering(ordering: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        value[1:] if value.startswith("-") else "-" + value
        for value in ordering
    )


def _page_values(result: QuerySetPageResult) -> dict[str, object]:
    request = result.request
    if request.after is not None and request.before is not None:
        raise CursorPaginationError(
            "Use either an after or before cursor, not both."
        )
    if request.size < 1 or request.size > 100:
        raise CursorPaginationError(
            "Cursor page size must be between 1 and 100."
        )

    ordering = _normalized_ordering(result)
    fingerprint = _query_fingerprint(result.queryset, ordering)
    queryset = result.queryset
    cursor = request.after if request.after is not None else request.before
    if cursor is not None:
        queryset = queryset.filter(
            _cursor_filter(
                ordering,
                _decode_cursor(cursor, ordering, fingerprint),
                after=request.after is not None,
            )
        )
    backwards = request.before is not None
    queryset = queryset.order_by(
        *(_reverse_ordering(ordering) if backwards else ordering)
    )
    rows = list(queryset[: request.size + 1])
    has_more = len(rows) > request.size
    rows = rows[: request.size]
    if backwards:
        rows.reverse()

    has_previous = request.after is not None or (backwards and has_more)
    has_next = request.before is not None or (not backwards and has_more)
    return {
        "items": rows,
        "next": (
            _encode_cursor(rows[-1], ordering, fingerprint)
            if rows and has_next
            else None
        ),
        "previous": (
            _encode_cursor(rows[0], ordering, fingerprint)
            if rows and has_previous
            else None
        ),
        "total": result.queryset.count() if result.include_total else None,
    }


def encode_queryset_page(
    result: QuerySetPageResult,
    page_type: type,
) -> dict[str, object]:
    return materialize_queryset_page(result, page_type).model_dump(mode="json")


def materialize_queryset_page(
    result: QuerySetPageResult,
    page_type: type,
) -> Page:
    metadata = getattr(page_type, "__pydantic_generic_metadata__", {})
    if metadata.get("origin") is not Page or len(metadata.get("args", ())) != 1:
        raise TypeError("queryset_page() requires an operation returning Page[T].")
    item_type = metadata["args"][0]
    values = _page_values(result)
    adapter = TypeAdapter(item_type)
    values["items"] = [
        adapter.validate_python(item, from_attributes=True)
        for item in values["items"]
    ]
    return page_type.model_validate(values)


def materialize_queryset_result(
    result: QuerySetResult,
    result_type: object,
):
    value_type = result_type
    nullable = False
    origin = get_origin(value_type)
    if origin in {types.UnionType, Union}:
        members = list(get_args(value_type))
        if type(None) in members:
            nullable = True
            members.remove(type(None))
        if len(members) != 1:
            raise TypeError(
                "queryset_result() requires one model type or list of one model "
                "type."
            )
        value_type = members[0]
        origin = get_origin(value_type)

    rows = list(result.queryset if origin is list else result.queryset[:2])
    if origin is list:
        value = rows
    elif not rows and nullable:
        value = None
    elif len(rows) == 1:
        value = rows[0]
    else:
        value = rows
    return TypeAdapter(result_type).validate_python(value, from_attributes=True)


def queryset_result[Result](
    queryset: QuerySet,
    *,
    include_paths: Sequence[str] = (),
) -> Result:
    return cast(Result, QuerySetResult(queryset, include_paths))


def queryset_page[Item](
    queryset: QuerySet,
    request: CursorPageRequest,
    *,
    order_by: Sequence[str] = (),
    include_total: bool = False,
) -> Page[Item]:
    return cast(
        Page[Item],
        QuerySetPageResult(queryset, request, order_by, include_total),
    )


def paginate_queryset(
    queryset: QuerySet,
    request: CursorPageRequest,
    page_type: type,
    *,
    order_by: Sequence[str] = (),
    include_total: bool = False,
) -> Page:
    result = QuerySetPageResult(queryset, request, order_by, include_total)
    return materialize_queryset_page(result, page_type)
