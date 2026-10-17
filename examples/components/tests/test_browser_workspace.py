from typing import cast

import pytest
from pyjs import js
from pyjs.testing.web import bubbling_click, mount
from pyjs.web.domx import require_element
from pyjs.web.html import HTMLButtonElement
from pyjs_examples.components.workspace import WorkspaceApp

pytestmark = pytest.mark.pyjs_web


@js
def mounted_workspace() -> WorkspaceApp:
    app = WorkspaceApp()
    mount(app)
    return app


@js
def test_workspace_renders_navigation_metrics_and_tasks():
    app = mounted_workspace()

    assert app.task_count == 5
    assert len(app.task_table_body.children) == 5
    assert len(app.querySelectorAll("[data-slot=card]")) >= 7
    assert len(app.querySelectorAll("[data-slot=chart-bar]")) == 6
    assert app.tabs.current_value() == "overview"
    assert app.layout.is_open()


@js
def test_new_task_dialog_validates_and_adds_a_task():
    app = mounted_workspace()
    app.new_task_dialog.open()

    cast(HTMLButtonElement, app.create_task_button.element).click()
    assert app.new_task_dialog.is_open
    assert app.task_title.getAttribute("aria-invalid") == "true"
    assert len(app.toaster.querySelectorAll("[data-slot=toast]")) == 1

    app.task_title.set_value("Prepare support handoff")
    cast(HTMLButtonElement, app.create_task_button.element).click()

    assert not app.new_task_dialog.is_open
    assert app.task_count == 6
    assert len(app.task_table_body.children) == 6
    assert app.task_count_label.textContent == "6 tasks"
    assert "Prepare support handoff" in app.task_table_body.children[5].textContent
    assert len(app.toaster.querySelectorAll("[data-slot=toast]")) == 2


@js
def test_workspace_navigation_date_picker_and_settings_are_interactive():
    app = mounted_workspace()

    toggle = require_element(app, "[data-sidebar-toggle]")
    bubbling_click(toggle)
    assert not app.layout.is_open()
    bubbling_click(toggle)
    assert app.layout.is_open()

    app.tabs.select("tasks")
    assert app.tabs.current_value() == "tasks"
    task_panel = require_element(app, "[data-slot=tabs-content][data-value=tasks]")
    assert task_panel.getAttribute("style") == "display: block"

    app.new_task_dialog.open()
    app.due_date.open()
    day = require_element(app.due_date.calendar, "[data-day='30']")
    bubbling_click(day)
    assert app.due_date.selected_day() == "30"
    assert not app.due_date.is_open
    app.new_task_dialog.close()

    app.settings_sheet.open()
    app.capacity_slider.set_value(88)
    cast(HTMLButtonElement, app.save_settings_button.element).click()
    assert not app.settings_sheet.is_open
    toast = require_element(app.toaster, "[data-slot=toast]:last-child")
    assert "88%" in toast.textContent


@js
def test_workspace_complex_widgets_cover_their_primary_interactions():
    app = mounted_workspace()

    accordion_items = app.querySelectorAll("[data-slot=accordion-item]")
    assert accordion_items[0].getAttribute("data-state") == "open"
    bubbling_click(require_element(accordion_items[1], "[data-slot=accordion-trigger]"))
    assert accordion_items[0].getAttribute("data-state") == "closed"
    assert accordion_items[1].getAttribute("data-state") == "open"

    carousel = require_element(app, "[data-slot=carousel]")
    assert carousel.getAttribute("data-index") == "0"
    bubbling_click(require_element(carousel, "[data-slot=carousel-next]"))
    assert carousel.getAttribute("data-index") == "1"

    app.tabs.select("collaboration")
    assert len(app.querySelectorAll("[data-slot=message]")) == 3
    assert len(app.querySelectorAll("[data-slot=attachment]")) == 1


@js
def test_workspace_visual_showcase():
    app = mounted_workspace()
    bounds = app.getBoundingClientRect()

    assert bounds.width >= 900
    assert bounds.height >= 700
    assert len(app.querySelectorAll("[data-slot=sidebar]")) == 1
    assert len(app.querySelectorAll("[data-slot=progress]")) == 1
    assert len(app.querySelectorAll("[data-slot=avatar]")) >= 3
