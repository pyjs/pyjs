"""Client JSON methods round-trip typed models without a server request."""
import pytest
from pydantic import BaseModel

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
    for document in ["null", "[]", "{}", '{"title":42}', '{"title":"ok"}trailing']:
        rejected = False
        try:
            Entry.model_validate_json(document)
        except Exception:
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


def test_json_contract_on_python():
    test_client_json_round_trip_preserves_unicode_and_fields()
    test_client_json_uses_declared_nested_model_fields()
    test_client_json_rejects_invalid_documents()
    test_client_json_selects_matching_container_union_schema()
