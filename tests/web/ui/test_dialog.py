import pytest

from examples.components.catalog import CatalogApp, main
from pyjs.web.ui.dialog import Dialog, DialogContent


@pytest.mark.pyjs_python
def test_catalog_dialog_can_be_rendered_on_the_server():
    app = main()

    assert isinstance(app, CatalogApp)
    assert isinstance(app.dialog, Dialog)
    assert app.dialog.getAttribute("id") is not None
    assert app.dialog.content.dialog_element.tagName == "DIALOG"
    assert app.dialog.content.dialog_element.getAttribute("aria-label") == "Edit profile"


@pytest.mark.pyjs_python
def test_dialog_scroll_policy_is_opt_in_and_server_rendered():
    assert "overflow-y-auto" not in DialogContent("Default").surface.className
    assert DialogContent("Long form", scrollable=True).surface.className == (
        "relative flex flex-col gap-4 p-6 data-[placement=left]:h-full "
        "data-[placement=right]:h-full max-h-dvh overflow-y-auto overscroll-contain "
        "data-[placement=center]:max-h-[calc(100dvh-2rem)]")
