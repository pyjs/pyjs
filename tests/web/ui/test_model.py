from datetime import date

import pytest
from pydantic import BaseModel, Field

from pyjs import js
from pyjs.server import OperationError, OperationIssue, Page
from pyjs.web.crypto import crypto
from pyjs.web.dom import Element, document
from pyjs.web.domx import input, tag
from pyjs.web.html import HTMLInputElement
from pyjs.web.ssr import render_html
from pyjs.web.ui.model import (
    BooleanModelColumn,
    DataTable,
    DateModelField,
    FloatModelField,
    IntegerModelField,
    ModelField,
    ModelForm,
    TextModelColumn,
    TextModelField,
)
from tests.web.ui.browser import mount


class Task(BaseModel):
    id: int | None = None
    title: str
    completed: bool = False
    internal: str = "private"


class TaskForm(ModelForm[Task]):
    title = TextModelField(label="Task")

    class Meta:
        fields = ("completed",)


class TaskTable(DataTable[Task]):
    title = TextModelColumn(label="Task")
    completed = BooleanModelColumn(label="Completed")


@js
class BrowserTask(BaseModel):
    id: int | None = None
    title: str
    completed: bool = False


@js
class BrowserTaskForm(ModelForm[BrowserTask]):
    title = TextModelField(label="Title")

    class Meta:
        fields = ("completed",)


@js
class BrowserTaskTable(DataTable[BrowserTask]):
    title = TextModelColumn(label="Task")


class Release(BaseModel):
    id: int
    name: str = Field(max_length=20, title="Release name")
    downloads: int
    stable: bool = False
    score: float
    due_date: date
    metadata: list[str] = []


class ReleaseForm(ModelForm[Release]):
    class Meta:
        fields = "__all__"
        exclude = ("metadata",)


def test_model_form_renders_and_reconstructs_a_typed_draft():
    form = TaskForm(Task(id=7, title="Review the form", completed=True))

    assert render_html(form.element) == (
        '<form class="grid gap-4" data-slot="model-form"><input '
        'data-model-control="" name="id" type="hidden" value="7" '
        'data-model-field="id"/><label class="grid gap-2 text-sm font-medium '
        'text-slate-900" data-model-field="title"><span>Task</span><input '
        'class="h-9 rounded-md border '
        'border-slate-300 bg-white px-3 text-sm outline-none focus:border-slate-500 '
        'focus:ring-2 focus:ring-slate-200 aria-invalid:border-red-500 '
        'aria-invalid:ring-red-100" data-model-control="" name="title" '
        'type="text" required="" value="Review the form"/></label><label '
        'class="flex items-center gap-2 text-sm font-medium text-slate-900" '
        'data-model-field="completed"><input class="size-4 rounded border '
        'border-slate-300 accent-slate-950" data-model-control="" '
        'name="completed" type="checkbox" checked=""/><span>completed</span>'
        "</label>"
        "</form>"
    )
    assert form.read_model() == Task(
        id=7,
        title="Review the form",
        completed=True,
    )


def test_model_form_reads_only_selected_values_from_field_owned_dom():
    form = TaskForm(Task(id=7, title="Review the form", completed=True))
    title = form.get_control("title")
    title.value = "Updated"

    assert form.values() == {
        "id": 7,
        "title": "Updated",
        "completed": True,
    }
    assert form.element.getAttribute("data-model") is None


def test_model_form_public_field_access_reports_unknown_names():
    form = TaskForm(Task(title="Review the form"))

    with pytest.raises(ValueError, match="^Unknown model form field: missing$"):
        form.get_field("missing")
    with pytest.raises(ValueError, match="^Unknown model form field: missing$"):
        form.get_field_element("missing")


def test_model_form_maps_operation_issues_to_accessible_field_errors(monkeypatch):
    identifiers = iter(("title", "form"))
    monkeypatch.setattr(crypto, "randomUUID", lambda: next(identifiers))
    form = TaskForm(Task(title="No"))
    title = form.get_control("title")
    title.setAttribute("aria-describedby", "title-help")

    form.set_errors(
        OperationError(
            [
                OperationIssue(
                    "Use at least three characters.",
                    ["draft", "title"],
                ),
                OperationIssue(
                    "Choose a more descriptive title.",
                    ["draft", "title"],
                ),
                OperationIssue("The issue could not be saved.", []),
            ]
        ),
        "draft",
    )

    assert render_html(form.element) == (
        '<form class="grid gap-4" data-slot="model-form"><input '
        'data-model-control="" name="id" type="hidden" value="" '
        'data-model-field="id"/><label class="grid gap-2 text-sm font-medium '
        'text-slate-900" data-model-field="title"><span>Task</span><input '
        'class="h-9 rounded-md border border-slate-300 bg-white px-3 text-sm '
        'outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200 '
        'aria-invalid:border-red-500 aria-invalid:ring-red-100" '
        'data-model-control="" name="title" type="text" required="" value="No" '
        'aria-describedby="title-help model-error-title" aria-invalid="true"/>'
        '<div class="text-sm font-normal text-red-600" data-slot="field-error" '
        'role="alert" data-model-error="title" id="model-error-title">Use at '
        'least three characters. Choose a more descriptive title.</div></label>'
        '<label class="flex items-center gap-2 text-sm font-medium '
        'text-slate-900" data-model-field="completed"><input class="size-4 '
        'rounded border border-slate-300 accent-slate-950" '
        'data-model-control="" name="completed" type="checkbox"/><span>'
        'completed</span></label><div class="text-sm font-normal text-red-600" '
        'data-slot="field-error" role="alert" data-model-error="" '
        'id="model-error-form">The issue could not be saved.</div></form>'
    )

    form.clear_errors()

    assert title.getAttribute("aria-invalid") is None
    assert title.getAttribute("aria-describedby") == "title-help"
    assert "data-model-error" not in render_html(form.element)


def test_model_form_round_trips_an_empty_optional_primary_key():
    form = TaskForm(Task(title="Unsaved"))

    assert render_html(form.element).startswith(
        '<form class="grid gap-4" data-slot="model-form"><input '
        'data-model-control="" name="id" type="hidden" value="" '
        'data-model-field="id"/>'
    )
    assert form.values()["id"] is None


def test_explicit_model_field_can_own_multiple_dom_controls():
    class Point(BaseModel):
        coordinates: list[int]

    class CoordinateModelField(ModelField):
        def create(self, model: BaseModel) -> Element:
            element = tag(
                "div",
                input({"name": self.name + ".x", "type": "number"}),
                input({"name": self.name + ".y", "type": "number"}),
            )
            self.update(element, model)
            return element

        def read(self, element: Element) -> object:
            x, y = element.children
            if not isinstance(x, HTMLInputElement) or not isinstance(
                y, HTMLInputElement
            ):
                raise TypeError("Coordinate field requires two inputs.")
            return [int(x.value), int(y.value)]

        def update(self, element: Element, model: BaseModel):
            x, y = element.children
            if not isinstance(x, HTMLInputElement) or not isinstance(
                y, HTMLInputElement
            ):
                raise TypeError("Coordinate field requires two inputs.")
            coordinates = getattr(model, self.name)
            x.value = str(coordinates[0])
            y.value = str(coordinates[1])

    class PointForm(ModelForm[Point]):
        coordinates = CoordinateModelField()

    form = PointForm(Point(coordinates=[4, 9]))
    field = form.get_field_element("coordinates")
    x, y = field.children
    if not isinstance(x, HTMLInputElement) or not isinstance(y, HTMLInputElement):
        raise TypeError("Coordinate field requires two inputs.")
    x.value = "5"
    y.value = "12"

    assert form.read_model() == Point(coordinates=[5, 12])
    assert render_html(form.element) == (
        '<form class="grid gap-4" data-slot="model-form"><div '
        'data-model-field="coordinates"><input name="coordinates.x" '
        'type="number"/><input name="coordinates.y" type="number"/></div>'
        "</form>"
    )


def test_model_form_generates_typed_widgets_from_meta_fields():
    model = Release(
        id=3,
        name="0.0.3",
        downloads=42,
        stable=True,
        score=9.5,
        due_date=date(2026, 8, 30),
    )
    form = ReleaseForm(model)

    assert [field.name for field in ReleaseForm.__pyjs_fields__] == [
        "id",
        "name",
        "downloads",
        "stable",
        "score",
        "due_date",
    ]
    assert isinstance(ReleaseForm.__pyjs_fields_by_name__["id"], IntegerModelField)
    assert ReleaseForm.__pyjs_fields_by_name__["id"].hidden
    assert isinstance(
        ReleaseForm.__pyjs_fields_by_name__["downloads"],
        IntegerModelField,
    )
    assert isinstance(
        ReleaseForm.__pyjs_fields_by_name__["score"],
        FloatModelField,
    )
    assert isinstance(
        ReleaseForm.__pyjs_fields_by_name__["due_date"],
        DateModelField,
    )
    assert ReleaseForm.__pyjs_fields_by_name__["name"].label == "Release name"
    assert ReleaseForm.__pyjs_fields_by_name__["name"].max_length == 20
    assert render_html(form.element) == (
        '<form class="grid gap-4" data-slot="model-form"><input '
        'data-model-control="" name="id" type="hidden" required="" value="3" '
        'data-model-field="id"/><label class="grid gap-2 text-sm font-medium '
        'text-slate-900" data-model-field="name"><span>Release name</span><input '
        'class="h-9 rounded-md border border-slate-300 bg-white px-3 text-sm '
        'outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200 '
        'aria-invalid:border-red-500 aria-invalid:ring-red-100" '
        'data-model-control="" name="name" type="text" required="" '
        'maxlength="20" value="0.0.3"/></label><label class="grid gap-2 text-sm '
        'font-medium text-slate-900" data-model-field="downloads"><span>'
        'downloads</span><input class="h-9 rounded-md border border-slate-300 '
        'bg-white px-3 text-sm outline-none focus:border-slate-500 focus:ring-2 '
        'focus:ring-slate-200 aria-invalid:border-red-500 '
        'aria-invalid:ring-red-100" data-model-control="" name="downloads" '
        'type="number" required="" value="42"/></label><label class="flex '
        'items-center gap-2 text-sm font-medium text-slate-900" '
        'data-model-field="stable"><input class="size-4 rounded border '
        'border-slate-300 accent-slate-950" data-model-control="" name="stable" '
        'type="checkbox" checked=""/><span>stable</span></label><label '
        'class="grid gap-2 text-sm font-medium text-slate-900" '
        'data-model-field="score"><span>score</span><input class="h-9 rounded-md '
        'border border-slate-300 bg-white px-3 text-sm outline-none '
        'focus:border-slate-500 focus:ring-2 focus:ring-slate-200 '
        'aria-invalid:border-red-500 aria-invalid:ring-red-100" '
        'data-model-control="" name="score" step="any" type="number" '
        'required="" value="9.5"/></label><label class="grid gap-2 text-sm '
        'font-medium text-slate-900" data-model-field="due_date"><span>due date'
        '</span><input class="h-9 rounded-md border border-slate-300 bg-white px-3 '
        'text-sm outline-none focus:border-slate-500 focus:ring-2 '
        'focus:ring-slate-200 aria-invalid:border-red-500 '
        'aria-invalid:ring-red-100" data-model-control="" name="due_date" type="date" '
        'required="" value="2026-08-30"/></label></form>'
    )
    assert form.read_model() == model


def test_model_form_requires_explicit_widgets_for_structured_fields():
    with pytest.raises(
        TypeError,
        match=(
            r"^StructuredForm cannot choose a widget for metadata: list\[str\]; "
            r"declare a ModelField explicitly\.$"
        ),
    ):

        class StructuredForm(ModelForm[Release]):
            class Meta:
                fields = ("metadata",)


def test_model_form_rejects_unknown_and_conflicting_meta_fields():
    with pytest.raises(TypeError, match=r"^Unknown Release field\(s\): missing\.$"):

        class UnknownForm(ModelForm[Release]):
            class Meta:
                fields = ("missing",)

    with pytest.raises(
        TypeError,
        match=r"^ConflictingForm explicitly declares excluded field\(s\): name\.$",
    ):

        class ConflictingForm(ModelForm[Release]):
            name = TextModelField()

            class Meta:
                fields = "__all__"
                exclude = ("name",)

    with pytest.raises(
        TypeError,
        match=r"^MissingOptionsForm.Meta must define fields or exclude\.$",
    ):

        class MissingOptionsForm(ModelForm[Release]):
            class Meta:
                pass


@pytest.mark.pyjs_web
@js
def test_model_form_uses_generated_fields_and_dom_values_in_the_browser():
    form = BrowserTaskForm(BrowserTask(title="Original", completed=True))
    assert form.get_field("title").label == "Title"
    assert (
        form.get_field_element("title").getAttribute("data-model-field")
        == "title"
    )
    title = form.get_control("title")
    title.value = "Updated"

    model = form.read_model()
    assert model.id is None
    assert model.title == "Updated"
    assert model.completed


@pytest.mark.pyjs_web
@js
def test_model_form_focuses_invalid_fields_and_clears_error_state_in_the_browser():
    form = BrowserTaskForm(BrowserTask(title="No"))
    mount(form.element)

    form.set_errors(
        OperationError(
            [
                OperationIssue("The identifier is stale.", ["draft", "id"]),
                OperationIssue(
                    "Use at least three characters.",
                    ["draft", "title"],
                ),
            ]
        ),
        "draft",
    )

    title = form.get_control("title")
    error = form.element.querySelector('[data-model-error="title"]')
    if error is None:
        raise ValueError("Missing title error.")
    assert title.getAttribute("aria-invalid") == "true"
    assert title.getAttribute("aria-describedby") == error.getAttribute("id")
    assert document.activeElement is title
    identifier = form.get_control("id")
    assert identifier.getAttribute("aria-invalid") is None

    form.clear_errors()

    assert title.getAttribute("aria-invalid") is None
    assert title.getAttribute("aria-describedby") is None
    assert form.element.querySelector("[data-model-error]") is None


@pytest.mark.pyjs_web
@js
def test_data_table_consumes_typed_cursor_pages_in_the_browser():
    table = BrowserTaskTable().set_page(
        Page[BrowserTask](
            items=[BrowserTask(title="First task")],
            next="next-page",
            total=3,
        )
    )
    mount(table.element)

    assert table.next_cursor() == "next-page"
    assert table.previous_cursor() is None
    assert table.element.textContent == "TaskFirst taskShowing 1 of 3 items"

    table.set_page(Page[BrowserTask](items=[]))

    assert table.next_cursor() is None
    assert table.element.textContent == "TaskShowing 0 items"


def test_data_table_renders_typed_columns_and_page_metadata():
    table = TaskTable().set_page(
        Page[Task](
            items=[
                Task(title="First task"),
                Task(title="Second task", completed=True),
            ],
            next="next-page",
            previous="previous-page",
            total=5,
        )
    )

    assert table.next_cursor() == "next-page"
    assert table.previous_cursor() == "previous-page"
    assert render_html(table.element) == (
        '<div class="grid gap-3 overflow-x-auto" data-slot="data-table" '
        'data-page-next="next-page" data-page-previous="previous-page"><table '
        'class="w-full border-collapse rounded-md border border-slate-200 bg-white">'
        '<thead><tr><th class="px-3 py-2 text-left text-xs font-semibold '
        'text-slate-600" scope="col">Task</th><th class="px-3 py-2 text-left '
        'text-xs font-semibold text-slate-600" scope="col">Completed</th></tr>'
        '</thead><tbody><tr><td class="border-t border-slate-200 px-3 py-2 text-sm '
        'text-slate-800">First task</td><td class="border-t border-slate-200 px-3 '
        'py-2 text-sm text-slate-800">No</td></tr><tr><td class="border-t '
        'border-slate-200 px-3 py-2 text-sm text-slate-800">Second task</td><td '
        'class="border-t border-slate-200 px-3 py-2 text-sm text-slate-800">Yes'
        '</td></tr></tbody></table><p class="text-sm text-slate-500">Showing '
        "2 of 5 items</p></div>"
    )


def test_model_adapters_reject_fields_that_are_not_on_the_model():
    with pytest.raises(
        TypeError,
        match=r"Unknown Task field\(s\): missing\.",
    ):

        class InvalidTaskForm(ModelForm[Task]):
            missing = TextModelField(label="Missing")
