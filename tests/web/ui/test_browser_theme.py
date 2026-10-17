import pytest

from pyjs import js
from pyjs.web.dom import window
from pyjs.web.ui.button import Button
from pyjs.web.ui.theme import Theme, ThemeProvider
from tests.web.ui.browser import mount

pytestmark = pytest.mark.pyjs_web


@js
def test_theme_provider_scopes_component_colors():
    button = Button("Save")
    provider = ThemeProvider(
        Theme(
            "orchard",
            primary="#166534",
            primary_hover="#15803d",
            radius="1rem",
        ),
        button,
    )
    mount(provider)

    style = window.getComputedStyle(button.element)
    assert provider.getAttribute("data-pyjs-theme") == "orchard"
    assert style.getPropertyValue("background-color") == "rgb(22, 101, 52)"
    assert style.getPropertyValue("border-radius") == "16px"
