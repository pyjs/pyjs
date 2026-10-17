import pytest

from examples.components.catalog import CatalogApp, main
from pyjs.web.ui.dialog import Dialog


@pytest.mark.pyjs_python
def test_catalog_dialog_can_be_rendered_on_the_server():
    app = main()

    assert isinstance(app, CatalogApp)
    assert isinstance(app.dialog, Dialog)
    assert app.dialog.getAttribute("id") is not None
    assert app.dialog.content.dialog_element.tagName == "DIALOG"
    assert app.dialog.content.dialog_element.getAttribute("aria-label") == "Edit profile"
