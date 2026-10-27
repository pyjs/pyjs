"""Client JSON methods round-trip typed models without a server request."""
from datetime import date

import pytest
from pydantic import BaseModel, ConfigDict

from pyjs import js


@js
class Entry(BaseModel):
    title: str
    count: int = 0


@js
class Detailed(Entry):
    private_detail: str = "not a parent field"


@js
class Envelope(BaseModel):
    entry: Entry
    entries: list[Entry]
    mapping: dict[str, Entry]
    optional: Entry | None = None


@js
class Other(BaseModel):
    label: str


@js
class Choice(BaseModel):
    items: list[Entry] | list[Other]


@js
class InheritedChoice(BaseModel):
    items: list[Entry] | list[Detailed]
    mapping: dict[str, Entry] | dict[str, Detailed]


@js
class DateEnvelope(BaseModel):
    items: list[date]


@js
class Numbers(BaseModel):
    value: float


@js
class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    count: int = 0


@js
class ClosedChild(ClosedModel):
    name: str = "child"


@js
class OpenChild(ClosedModel):
    model_config = ConfigDict(extra="ignore", strict=False)


@js
class EmptyClosed(BaseModel):
    model_config = ConfigDict(extra="forbid")


@js
class ClosedEnvelope(BaseModel):
    child: ClosedChild
    empty: EmptyClosed


@js
class StrictMapping(BaseModel):
    model_config = ConfigDict(strict=True)
    items: dict[int, int]


@pytest.mark.pyjs_web
@js
def test_client_json_honors_extra_and_strict_model_config():
    for source in ['{"count":1,"future":true}', '{"count":"1"}',
                   '{"count":true}', '{"count":[]}']:
        rejected = False
        try:
            ClosedChild.model_validate_json(source)
        except ValueError:
            rejected = True
        assert rejected
    assert ClosedChild.model_validate_json('{}').name == "child"
    assert ClosedChild.model_validate_json('{"count":2}').count == 2
    assert OpenChild.model_validate_json('{"count":"3","future":true}').count == 3
    assert Entry.model_validate_json('{"title":"ok","ignored":true}').title == "ok"
    assert StrictMapping.model_validate_json('{"items":{"1":2}}').items[1] == 2


@pytest.mark.pyjs_web
@js
def test_client_json_rejects_nested_and_empty_model_extras():
    for source in ['{"child":{"future":1},"empty":{}}',
                   '{"child":{},"empty":{"future":1}}',
                   '{"child":{"count":"1"},"empty":{}}']:
        rejected = False
        try:
            ClosedEnvelope.model_validate_json(source)
        except ValueError:
            rejected = True
        assert rejected
    result = ClosedEnvelope.model_validate_json('{"child":{},"empty":{}}')
    assert result.child.count == 0
    assert result.empty.model_dump_json() == "{}"


@pytest.mark.pyjs_web
@js
def test_client_json_rejects_ambiguous_dates_instead_of_shifting_timezone():
    value = DateEnvelope.model_validate_json('{"items":["2024-01-01"]}')
    rejected = False
    try:
        value.model_dump_json()
    except ValueError as error:
        rejected = "date/datetime" in str(error)
    assert rejected


@pytest.mark.pyjs_web
@js
def test_client_json_rejects_nonfinite_numbers_with_value_error():
    for value in [float("nan"), float("inf"), float("-inf")]:
        rejected = False
        try:
            Numbers(value=value).model_dump_json()
        except ValueError:
            rejected = True
        assert rejected


@pytest.mark.pyjs_web
@js
def test_client_json_rejects_numeric_overflow_during_decode():
    for document in ['{"value":1e400}', '{"value":-1e400}']:
        rejected = False
        try:
            Numbers.model_validate_json(document)
        except ValueError:
            rejected = True
        assert rejected


@pytest.mark.pyjs_web
@js
def test_client_json_round_trip_preserves_unicode_and_fields():
    entry = Entry.model_validate_json('{"title":"snow 雪😀"}')
    assert entry.title == "snow 雪😀"
    assert entry.count == 0
    restored = Entry.model_validate_json(entry.model_dump_json())
    assert restored.title == entry.title
    assert restored.count == 0


@pytest.mark.pyjs_web
@js
def test_client_json_uses_declared_nested_model_fields():
    child = Detailed(title="nested")
    root = Detailed.model_validate_json(child.model_dump_json())
    assert root.private_detail == child.private_detail
    envelope = Envelope(entry=child, entries=[child], mapping={"key": child}, optional=child)
    encoded = envelope.model_dump_json()
    assert "private_detail" not in encoded
    restored = Envelope.model_validate_json(encoded)
    assert restored.entry.title == "nested"
    assert restored.entries[0].title == "nested"
    assert restored.mapping["key"].title == "nested"
    optional = restored.optional
    assert optional is not None
    if optional is not None:
        assert optional.title == "nested"


@pytest.mark.pyjs_web
@js
def test_client_json_rejects_invalid_documents():
    for document in ["{", "null", "[]", "{}", '{"title":42}',
                     '{"title":"ok","count":1.5}', '{"title":"ok"}trailing']:
        rejected = False
        try:
            Entry.model_validate_json(document)
        except ValueError:
            rejected = True
        assert rejected


@pytest.mark.pyjs_web
@js
def test_client_json_selects_matching_container_union_schema():
    choice = Choice(items=[Other(label="different shape")])
    encoded = choice.model_dump_json()
    assert '"label":"different shape"' in encoded
    assert '"title"' not in encoded
    assert Choice.model_validate_json(encoded).model_dump_json() == encoded


@pytest.mark.pyjs_web
@js
def test_client_json_union_round_trip_keeps_supplied_subclass_fields():
    child = Detailed(title="nested", private_detail="preserved")
    value = InheritedChoice(items=[child], mapping={"key": child})
    encoded = value.model_dump_json()
    assert '"private_detail":"preserved"' in encoded
    assert InheritedChoice.model_validate_json(encoded).model_dump_json() == encoded


def test_json_contract_on_python():
    test_client_json_honors_extra_and_strict_model_config()
    test_client_json_rejects_nested_and_empty_model_extras()
    test_client_json_round_trip_preserves_unicode_and_fields()
    test_client_json_uses_declared_nested_model_fields()
    test_client_json_rejects_invalid_documents()
    test_client_json_selects_matching_container_union_schema()
    test_client_json_union_round_trip_keeps_supplied_subclass_fields()
