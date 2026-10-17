from typing import cast

import pytest

from examples.components.catalog import CatalogApp, CatalogPagination
from pyjs import js
from pyjs.web.dom import document
from pyjs.web.domx import require_element
from pyjs.web.events import Event
from tests.web.ui.browser import mount, selector_count

pytestmark = pytest.mark.pyjs_web


@js
def test_catalog_dialog_edits_profile_and_reports_saved_value():
    app = CatalogApp()
    mount(app)

    app.dialog.open()
    assert app.dialog.is_open
    assert document.activeElement is app.name_input

    app.name_input.value = "Grace Hopper"
    app.save_button.dispatchEvent(Event("click"))

    assert not app.dialog.is_open
    assert app.status.textContent == "Saved profile for Grace Hopper."
    assert document.activeElement is app.dialog.trigger.element


@js
def test_catalog_includes_the_foundation_component_batch():
    app = CatalogApp()
    mount(app)

    expected_slots = {
        "accordion": 1,
        "alert": 2,
        "alert-dialog": 1,
        "aspect-ratio": 1,
        "avatar-group": 1,
        "breadcrumb": 1,
        "button-group": 1,
        "card": 1,
        "collapsible": 1,
        "empty": 1,
        "hover-card": 1,
        "kbd-group": 1,
        "popover": 1,
        "progress": 1,
        "questionnaire": 1,
        "radio-group": 1,
        "separator": 2,
        "sheet": 1,
        "skeleton": 3,
        "spinner": 1,
        "table": 1,
        "tabs": 1,
        "toggle-group": 1,
        "tooltip": 1,
    }
    for slot, expected_count in expected_slots.items():
        assert selector_count(app, "[data-slot=" + slot + "]") == expected_count, slot

    badge_showcase = require_element(app, "#badge")
    assert selector_count(badge_showcase, "[data-slot=badge]") == 6
    assert selector_count(app, "[data-testid=catalog-form]") == 1


@js
def test_catalog_menu_matches_component_section_order():
    app = CatalogApp()
    mount(app)

    menu_order = ""
    for link in app.querySelectorAll('aside a[href^="#"]'):
        href = link.getAttribute("href")
        if href is not None:
            if href != "#examples":
                menu_order += href + " "

    section_order = ""
    for section in app.querySelectorAll("[data-catalog-component]"):
        component_id = section.getAttribute("data-catalog-component")
        if component_id is not None:
            section_order += "#" + component_id + " "

    assert menu_order == section_order


@js
def test_catalog_examples_are_independent_and_pagination_stays_in_place():
    app = CatalogApp()
    mount(app)

    component_count = selector_count(app, "[data-catalog-component]")
    assert selector_count(app, "[data-catalog-source]") == component_count
    assert selector_count(app, "[data-catalog-copy]") == component_count

    pagination = cast(
        CatalogPagination,
        require_element(app, "catalog-pagination"),
    )
    page_click = Event("click", bubbles=True, cancelable=True)
    pagination.page_two.dispatchEvent(page_click)

    assert page_click.defaultPrevented
    assert pagination.getAttribute("data-page") == "2"
    assert pagination.page_two.getAttribute("aria-current") == "page"
    assert pagination.page_one.getAttribute("aria-current") is None
