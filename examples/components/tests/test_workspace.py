import pytest
from pyjs_examples.components.workspace import WorkspaceApp, main


@pytest.mark.pyjs_python
def test_workspace_renders_the_complete_launch_view_on_the_server():
    app = main()

    assert isinstance(app, WorkspaceApp)
    assert app.task_count == 5
    assert app.getAttribute("task-count") == "5"
    assert len(app.task_table_body.children) == 5
    assert app.tabs.current_value() == "overview"
    task_panel = app.querySelector("#tasks")
    assert task_panel is not None
    assert app.layout.is_open()
    assert app.new_task_dialog.content.dialog_element.getAttribute("aria-label") == "Create a task"
    assert app.settings_sheet.content.dialog_element.getAttribute("data-side") == "right"


@pytest.mark.pyjs_python
def test_workspace_form_defaults_are_stored_on_the_components():
    app = WorkspaceApp()

    assert app.task_priority.selected_value == "medium"
    assert app.task_type.current_value() == "feature"
    assert app.due_date.selected_day() == "28"
    assert app.notification_switch.is_checked()
    assert app.capacity_slider.getAttribute("value") == "72"
