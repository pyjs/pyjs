import pytest
from pyjs import js
from pyjs.web.dom import document
from pyjs_examples.todomvc.todomvc import TodoApp, TodoItem, main


@pytest.mark.pyjs_python
def test_app_can_be_rendered_on_the_server():
    app = main()

    assert isinstance(app, TodoApp)
    assert app.todo_list.getAttribute("id") is not None


@js
def test_todo_item_owns_its_serializable_state_in_the_dom():
    item = TodoItem("7", "Learn pyjs")
    document.body.replaceChildren(item)

    assert item.todo_id == "7"
    assert item.title == "Learn pyjs"
    assert not item.completed

    item.title = "Build an app"
    item.completed = True

    assert item.getAttribute("title") == "Build an app"
    assert item.hasAttribute("completed")
    assert item.label.textContent == "Build an app"
    assert item.toggle.checked


@js
def test_app_trims_new_todos_and_tracks_counts_from_dom_children():
    app = TodoApp()

    assert app.add_todo("   ") is None
    app.add_todo("  first task  ")
    app.add_todo("second task")
    first: TodoItem = app.todo_list.children[0]
    second: TodoItem = app.todo_list.children[1]

    assert first.title == "first task"
    assert second.title == "second task"
    assert len(app.todo_list.children) == 2
    assert app.active_count() == 2
    assert app.count_number.textContent == "2"
    assert app.main.style.display == "block"


@js
def test_toggle_all_updates_each_todo_and_the_counter():
    app = TodoApp()
    app.add_todo("one")
    app.add_todo("two")

    app.set_all_completed(True)

    assert app.active_count() == 0
    assert app.completed_count() == 2
    assert app.toggle_all.checked
    assert app.clear_completed_button.style.display == "block"


@js
def test_filtering_uses_completed_dom_attributes():
    app = TodoApp()
    app.add_todo("active")
    app.add_todo("completed")
    active: TodoItem = app.todo_list.children[0]
    completed: TodoItem = app.todo_list.children[1]
    completed.completed = True

    app.filter = "active"
    app.apply_filter()

    assert active.style.display == "block"
    assert completed.style.display == "none"

    app.filter = "completed"
    app.apply_filter()

    assert active.style.display == "none"
    assert completed.style.display == "block"
