import pytest
from pyjs import js
from pyjs.javascript import JSON
from pyjs.testing.web import mount
from pyjs.web.dom import document, localStorage, location, window
from pyjs.web.events import Event, KeyboardEvent
from pyjs_examples.todomvc.todomvc import TodoApp, TodoItem, TodoRecord

pytestmark = pytest.mark.pyjs_web


@js
def mounted_app() -> TodoApp:
    localStorage.removeItem(TodoApp.storage_key)
    location.hash = "#/"
    app = TodoApp()
    mount(app)
    return app


@js
def enter_todo(app: TodoApp, title: str):
    app.new_todo.value = title
    app.new_todo.dispatchEvent(KeyboardEvent("keydown", key="Enter"))


@js
def todo_item(app: TodoApp, index: int) -> TodoItem:
    item = app.todo_list.children[index]
    assert isinstance(item, TodoItem)
    return item


@js
def test_add_toggle_filter_clear_and_counts():
    app = mounted_app()
    assert document.activeElement is app.new_todo

    enter_todo(app, "  write tests  ")
    enter_todo(app, "ship example")
    first = todo_item(app, 0)
    second = todo_item(app, 1)

    assert first.title == "write tests"
    assert second.title == "ship example"
    assert app.count_number.textContent == "2"
    assert app.main.style.display == "block"
    assert app.footer.style.display == "block"

    app.toggle_all_label.dispatchEvent(Event("click"))
    assert first.completed
    assert second.completed
    app.toggle_all_label.dispatchEvent(Event("click"))
    assert not first.completed
    assert not second.completed

    first.toggle.checked = True
    first.toggle.dispatchEvent(Event("change"))
    assert first.item.classList.contains("completed")
    assert app.count_number.textContent == "1"
    assert app.clear_completed_button.style.display == "block"

    location.hash = "#/active"
    window.dispatchEvent(Event("hashchange"))
    assert first.style.display == "none"
    assert second.style.display == "block"
    assert app.active_filter.classList.contains("selected")

    location.hash = "#/completed"
    window.dispatchEvent(Event("hashchange"))
    assert first.style.display == "block"
    assert second.style.display == "none"

    app.clear_completed_button.dispatchEvent(Event("click"))
    assert len(app.todo_list.children) == 1
    remaining = todo_item(app, 0)
    assert remaining.title == "ship example"
    assert app.clear_completed_button.style.display == "none"


@js
def test_editing_saves_cancels_and_deletes_empty_titles():
    app = mounted_app()
    enter_todo(app, "original title")
    item = todo_item(app, 0)

    item.label.dispatchEvent(Event("dblclick"))
    assert item.editing
    assert document.activeElement is item.edit_input
    item.edit_input.value = "  edited title  "
    item.edit_input.dispatchEvent(Event("blur"))
    assert item.title == "edited title"

    item.label.dispatchEvent(Event("dblclick"))
    item.edit_input.value = "discard this"
    item.edit_input.dispatchEvent(KeyboardEvent("keydown", key="Escape"))
    assert not item.editing
    assert item.title == "edited title"

    item.label.dispatchEvent(Event("dblclick"))
    item.edit_input.value = "   "
    item.edit_input.dispatchEvent(Event("blur"))
    assert len(app.todo_list.children) == 0
    assert app.main.style.display == "none"
    assert app.footer.style.display == "none"


@js
def test_todos_and_active_route_survive_a_reload_equivalent():
    app = mounted_app()
    enter_todo(app, "persist me")
    enter_todo(app, "keep active")
    completed = todo_item(app, 0)
    completed.toggle.checked = True
    completed.toggle.dispatchEvent(Event("change"))
    location.hash = "#/active"

    stored = localStorage.getItem(TodoApp.storage_key)
    if stored is None:
        raise AssertionError
    records: list[TodoRecord] = JSON.parse(stored)
    assert len(records) == 2
    assert records[0]["title"] == "persist me"
    assert records[0]["completed"]

    document.body.replaceChildren()
    restored = TodoApp()
    document.body.append(restored)

    assert restored.filter == "active"
    assert len(restored.todo_list.children) == 2
    restored_completed = todo_item(restored, 0)
    restored_active = todo_item(restored, 1)
    assert restored_completed.completed
    assert restored_completed.item.classList.contains("completed")
    assert restored_completed.style.display == "none"
    assert restored_active.style.display == "block"
    assert restored.count_number.textContent == "1"


@js
def test_visual_showcase_matches_the_canonical_todomvc_states():
    app = mounted_app()
    enter_todo(app, "Taste JavaScript")
    enter_todo(app, "Build with pyjs")
    enter_todo(app, "Submit TodoMVC example")
    completed = todo_item(app, 0)
    completed.toggle.checked = True
    completed.toggle.dispatchEvent(Event("change"))

    assert len(app.querySelectorAll(".todo-list li")) == 3
    assert app.count_number.textContent == "2"
    assert app.clear_completed_button.style.display == "block"
