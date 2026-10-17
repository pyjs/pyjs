import pytest

from pyjs import js
from pyjs.docs.ui import DocsApp
from pyjs.web.dom import document, localStorage, sessionStorage, window
from pyjs.web.domx import tag
from pyjs.web.events import Event, KeyboardEvent
from pyjs.web.html import HTMLElement
from tests.web.ui.browser import mount

pytestmark = pytest.mark.pyjs_web


@js
def mounted_docs() -> DocsApp:
    localStorage.setItem("pyjs-docs-theme", "dark")
    search_data = (
        '[{"title":"State and effects","section":"Guide",'
        '"text":"Typed reactive attributes","url":"/guide/state/"}]'
    )
    navigation = tag("div", {"style": "height: 3000px"}, "Navigation")
    app = DocsApp("PyJS", "/", navigation, "Article", "Outline", search_data)
    mount(app)
    return app


@js
def test_docs_theme_uses_saved_preference_and_toggles():
    app = mounted_docs()
    root = document.documentElement
    if root is None:
        raise ValueError("Expected an HTML document root")

    assert root.getAttribute("data-theme") == "dark"
    assert app.theme_button.textContent == "Light"

    app.theme_button.click()

    assert root.getAttribute("data-theme") == "light"
    assert localStorage.getItem("pyjs-docs-theme") == "light"
    assert app.theme_button.textContent == "Dark"


@js
def test_docs_search_opens_from_button_and_filters_records():
    app = mounted_docs()

    app.search_button.click()
    assert app.search_dialog.open
    assert document.activeElement is app.search_input

    app.search_input.value = "reactive"
    app.search_input.dispatchEvent(Event("input"))

    results = app.search_results.querySelectorAll(".search-result")
    assert len(results) == 1
    assert results[0].getAttribute("href") == "/guide/state/"
    result_text = results[0].textContent
    if result_text is None:
        raise ValueError("Expected search result text")
    assert "State and effects" in result_text

    app.search_input.value = "missing"
    app.search_input.dispatchEvent(Event("input"))
    empty_text = app.search_results.textContent
    if empty_text is None:
        raise ValueError("Expected empty-search text")
    assert "No results" in empty_text


@js
def test_docs_keyboard_shortcut_and_mobile_menu():
    app = mounted_docs()

    shortcut = KeyboardEvent("keydown", key="k", ctrlKey=True)
    window.dispatchEvent(shortcut)
    assert app.search_dialog.open

    app.close_search()
    app.menu_button.click()
    assert app.hasAttribute("data-menu-open")
    assert app.menu_button.getAttribute("aria-expanded") == "true"

    app.menu_button.click()
    assert not app.hasAttribute("data-menu-open")


@js
def test_docs_adds_copy_controls_to_code_blocks():
    app = mounted_docs()
    block = tag("div", {"class": "highlight"}, tag("code", "print('hello')"))
    app.append(block)

    app.add_code_copy_buttons()

    copy_button = block.querySelector(".copy-button")
    if not isinstance(copy_button, HTMLElement):
        raise ValueError("Expected a code copy button")
    assert copy_button.textContent == "Copy"


@js
def test_docs_navigation_restores_its_scroll_position_after_navigation():
    sessionStorage.removeItem("pyjs-docs-navigation-scroll")
    first = mounted_docs()
    first.navigation_panel.setAttribute("style", "height:100px;overflow-y:auto")
    first.navigation_panel.scrollTop = 240
    first.navigation_panel.dispatchEvent(Event("click"))

    assert sessionStorage.getItem("pyjs-docs-navigation-scroll") == "240.0"

    second = mounted_docs()
    second.navigation_panel.setAttribute("style", "height:100px;overflow-y:auto")
    second.restore_navigation_position()

    assert second.navigation_panel.scrollTop == 240
    sessionStorage.removeItem("pyjs-docs-navigation-scroll")
