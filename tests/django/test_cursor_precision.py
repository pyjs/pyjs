"""Keyset boundaries and query identities preserve database temporal precision."""

from datetime import UTC, datetime, time

import pytest
from django.db import connection
from pydantic import BaseModel

from pyjs.server import CursorPageRequest, Page
from pyjs.server.django import queryset_page
from pyjs.server.django.queryset import CursorPaginationError, encode_queryset_page
from tests.django.models import EventRecord


class Event(BaseModel):
    id: int


@pytest.fixture
def events():
    with connection.schema_editor() as editor:
        editor.create_model(EventRecord)
    try:
        for identifier, microsecond in enumerate((100, 200, 200), 1):
            EventRecord.objects.create(
                id=identifier,
                occurred_at=datetime(2026, 1, 1, microsecond=microsecond, tzinfo=UTC),
                clock=time(microsecond=microsecond),
            )
        yield EventRecord.objects.all()
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(EventRecord)


@pytest.mark.parametrize("field", ("occurred_at", "clock"))
@pytest.mark.parametrize("descending", (False, True))
def test_temporal_cursors_round_trip_without_skips_duplicates_or_lost_ties(events, field, descending):
    ordering = (("-" if descending else "") + field,)

    def page(**cursor):
        return encode_queryset_page(
            queryset_page(events, CursorPageRequest(size=1, **cursor), order_by=ordering), Page[Event],
        )

    first = page()
    second = page(after=first["next"])
    third = page(after=second["next"])
    expected = [3, 2, 1] if descending else [1, 2, 3]
    assert [result["items"][0]["id"] for result in (first, second, third)] == expected
    assert third["next"] is None
    assert page(before=third["previous"])["items"] == second["items"]
    assert page(before=second["previous"])["items"] == first["items"]


@pytest.mark.parametrize("field", ("occurred_at", "clock"))
def test_temporal_filter_precision_is_part_of_cursor_query_identity(events, field):
    value = getattr(events.get(id=1), field)
    original = events.filter(**{field + "__gte": value})
    changed = events.filter(**{field + "__gte": value.replace(microsecond=101)})
    first = encode_queryset_page(
        queryset_page(original, CursorPageRequest(size=1)), Page[Event],
    )
    with pytest.raises(CursorPaginationError, match="does not match this query"):
        encode_queryset_page(
            queryset_page(changed, CursorPageRequest(size=1, after=first["next"])), Page[Event],
        )
