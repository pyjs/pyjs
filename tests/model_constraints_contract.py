from pydantic import BaseModel, ConfigDict, Field

from pyjs import js


@js
class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=2)
    count: int = Field(ge=0, le=10)
    ratio: float = Field(gt=-1.5, lt=2.5)
    optional: int | None = Field(default=None, ge=1)
    caption: str | None = Field(default=None, min_length=1, max_length=2)
    unchecked_default: int = Field(default=-1, ge=0)


@js
class Page(BaseModel):
    entries: list[Entry] = Field(min_length=1, max_length=2)
    lookup: dict[str, str] = Field(min_length=1, max_length=2)


@js
class Child(Entry):
    title: str = Field(min_length=2, max_length=3)


@js
class Constrained(BaseModel):
    value: int = Field(ge=0)


@js
class Unconstrained(Constrained):
    value: int


@js
class MixedBounds(BaseModel):
    fraction: float = Field(ge=0, le=2)
    count: int = Field(gt=1.0, lt=4.0)


@js
def check_constraints() -> str:
    entry = '{"title":"😀é","count":0,"ratio":0.0}'
    page = '{"entries":[' + entry + '],"lookup":{"first":"one"}}'
    restored = Page.model_validate_json(page)
    assert restored.entries[0].title == "😀é"
    assert restored.entries[0].count == 0
    assert restored.entries[0].unchecked_default == -1
    assert restored.entries[0].optional is None
    assert restored.entries[0].caption is None
    assert restored.lookup["first"] == "one"
    assert Entry.model_validate_json(entry.replace('"count":0', '"count":10')).count == 10
    assert Entry.model_validate_json(entry.replace('"ratio":0.0', '"ratio":2.4')).ratio == 2.4
    nullable = entry.replace('"ratio":0.0', '"ratio":0.0,"optional":null')
    assert Entry.model_validate_json(nullable).optional is None
    assert Child.model_validate_json(entry.replace('😀é', 'abc')).title == "abc"
    assert Unconstrained.model_validate_json('{"value":-1}').value == -1
    invalid = [
        page.replace('😀é', ''), page.replace('😀é', '😀é😀'),
        page.replace('"count":0', '"count":-1'),
        page.replace('"count":0', '"count":11'),
        page.replace('"ratio":0.0', '"ratio":-1.5'),
        page.replace('"ratio":0.0', '"ratio":2.5'),
        page.replace('"ratio":0.0', '"ratio":0.0,"optional":0'),
        page.replace('"ratio":0.0', '"ratio":0.0,"caption":""'),
        page.replace('"ratio":0.0', '"ratio":0.0,"caption":"😀é😀"'),
        page.replace('"ratio":0.0', '"ratio":0.0,"unchecked_default":-1'),
        '{"entries":[],"lookup":{"first":"one"}}',
        '{"entries":[' + entry + ',' + entry + ',' + entry + '],"lookup":{"first":"one"}}',
        page.replace('"lookup":{"first":"one"}', '"lookup":{}'),
        page.replace('"lookup":{"first":"one"}', '"lookup":{"a":"one","b":"two","c":"three"}'),
    ]
    for document in invalid:
        try:
            Page.model_validate_json(document)
        except ValueError:
            continue
        return "accepted invalid input: " + document
    assert MixedBounds.model_validate_json('{"fraction":0.0,"count":2}').count == 2
    for document in ['{"fraction":-0.1,"count":2}', '{"fraction":2.1,"count":2}',
                     '{"fraction":1.0,"count":1}', '{"fraction":1.0,"count":4}']:
        try:
            MixedBounds.model_validate_json(document)
        except ValueError:
            continue
        return "accepted mixed numeric bound: " + document
    try:
        Child.model_validate_json(entry.replace('😀é', 'a'))
    except ValueError:
        return "validated"
    return "ignored inherited override"
