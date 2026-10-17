from datetime import date
from typing import Literal, cast

import pytest
from pydantic import BaseModel, Field

from pyjs import js
from tests.lib.pydantic_models import ExternalLabel


@js
class Task(BaseModel):
    title: str
    completed: bool = False
    tags: list[str] = Field(default_factory=list)


@js
class Label(BaseModel):
    name: str


@js
class Identified(BaseModel):
    id: int | None = None


@js
class Note(Identified):
    title: str
    label: Label | None = None
    history: list[Label] = Field(default_factory=list)
    metadata: dict[str, int] = Field(default_factory=dict)


@js
class Tree(BaseModel):
    name: str
    children: list[Tree] = Field(default_factory=list)


@js
class ImportedNote(BaseModel):
    label: ExternalLabel


@js
class Containers(BaseModel):
    labels: set[str]
    point: tuple[int, int]
    counts: dict[str, int]


@js
class Release(BaseModel):
    due_date: date


@js
class Workflow(BaseModel):
    state: Literal["open", "closed"]
    previous_state: Literal["open", "closed"] | None = None


@js
class Preferences(BaseModel):
    compact: bool = False
    theme: Literal["light", "dark"] = "light"


@js
class LabelEnvelope(BaseModel):
    label: Label


def test_pydantic_models_keep_the_real_server_behavior():
    task = Task(title="Ship")
    restored = Task.model_validate(task.model_dump())

    assert restored == task
    assert restored.model_dump() == {
        "title": "Ship",
        "completed": False,
        "tags": [],
    }


@pytest.mark.pyjs_web
@js
def test_pydantic_models_with_only_defaults_construct_without_arguments():
    preferences = Preferences()

    assert preferences.compact is False
    assert preferences.theme == "light"


@pytest.mark.pyjs_web
@js
def test_nested_models_construct_without_preserving_model_validate():
    envelope = LabelEnvelope(label={"name": "from JSON"})

    assert envelope.label.name == "from JSON"


@pytest.mark.pyjs_web
@js
def test_pydantic_models_construct_dump_and_validate_in_the_browser():
    task = Task(title="Ship")
    task.tags.append("release")
    restored = Task.model_validate(task.model_dump())

    assert task.title == "Ship"
    assert task.completed is False
    assert restored.title == "Ship"
    assert restored.tags[0] == "release"


@pytest.mark.pyjs_web
@js
def test_pydantic_mutable_defaults_are_not_shared_in_the_browser():
    first = Task(title="First")
    second = Task(title="Second")

    first.tags.append("changed")

    first_note = Note(title="First")
    second_note = Note(title="Second")
    first_note.metadata["changed"] = 1

    assert len(first.tags) == 1
    assert len(second.tags) == 0
    assert len(first_note.metadata) == 1
    assert len(second_note.metadata) == 0


@pytest.mark.pyjs_web
@js
def test_pydantic_required_fields_are_checked_in_the_browser():
    message = ""
    try:
        Task(completed=True)
    except TypeError as error:
        message = str(error)

    assert message == "Missing required field: title"


@pytest.mark.pyjs_web
@js
def test_pydantic_nested_models_and_containers_validate_in_the_browser():
    note = Note.model_validate(
        {
            "title": "Release",
            "id": "7",
            "label": {"name": "important"},
            "history": [{"name": "created"}],
            "metadata": {"priority": 3},
        }
    )

    label_value = note.label
    if label_value is None:
        raise AssertionError("label was not reconstructed")
    assert label_value.name == "important"
    assert note.id == 7
    assert note.history[0].name == "created"
    assert note.metadata["priority"] == 3

    restored = Note.model_validate(note.model_dump())
    assert restored.history[0].name == "created"
    assert restored.metadata["priority"] == 3


@pytest.mark.pyjs_web
@js
def test_pydantic_recursive_and_imported_models_validate_in_the_browser():
    tree = Tree.model_validate(
        {"name": "root", "children": [{"name": "leaf"}]}
    )
    note = ImportedNote.model_validate({"label": {"name": "external"}})

    assert tree.children[0].name == "leaf"
    assert note.label.name == "external"


@pytest.mark.pyjs_web
@js
def test_pydantic_container_and_date_fields_validate_in_the_browser():
    values = Containers.model_validate(
        {
            "labels": ["ready", "ready"],
            "point": [3, 4],
            "counts": {"open": 2},
        }
    )
    release = Release.model_validate({"due_date": "2026-08-16"})

    assert len(values.labels) == 1
    assert values.point[1] == 4
    assert values.counts["open"] == 2
    assert release.due_date.getFullYear() == 2026
    assert release.due_date.getMonth() == 7
    assert release.due_date.getDate() == 16


@pytest.mark.pyjs_web
@js
def test_pydantic_container_and_date_errors_are_clear_in_the_browser():
    tuple_message = ""
    date_message = ""
    input_message = ""
    try:
        Containers.model_validate(
            {"labels": [], "point": [3], "counts": {}}
        )
    except TypeError as error:
        tuple_message = str(error)
    try:
        Release.model_validate({"due_date": "not-a-date"})
    except TypeError as error:
        date_message = str(error)
    try:
        Release.model_validate(cast(dict[str, object], None))
    except TypeError as error:
        input_message = str(error)

    assert tuple_message == "point must be tuple of length 2"
    assert date_message == "due_date must be date"
    assert input_message == "Model input must be a dict or model"


@pytest.mark.pyjs_web
@js
def test_pydantic_literal_fields_validate_in_the_browser():
    workflow = Workflow.model_validate({"state": "open"})
    message = ""
    try:
        Workflow.model_validate({"state": "missing"})
    except TypeError as error:
        message = str(error)

    assert workflow.state == "open"
    assert workflow.previous_state is None
    assert message == "state must be one of open, closed"


@pytest.mark.pyjs_web
@js
def test_pydantic_invalid_scalar_values_fail_in_the_browser():
    message = ""
    id_message = ""
    try:
        Note.model_validate({"title": 3})
    except TypeError as error:
        message = str(error)
    try:
        Note.model_validate({"title": "Invalid ID", "id": "7x"})
    except TypeError as error:
        id_message = str(error)

    assert message == "title must be str"
    assert id_message == "id must be a valid union member"
