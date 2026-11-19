import pytest

from examples.components.catalog import CatalogApp, main
from pyjs.web.domx import button, div
from pyjs.web.ui.dialog import Dialog, DialogContent, DialogPanel


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


@pytest.mark.pyjs_python
def test_dialog_panel_exposes_fixed_sections_and_a_scrolling_body():
    field = div("Document")
    panel = DialogPanel("Edit document", field, close_on_backdrop=False)
    panel.header.append(button("Back"))
    panel.footer.append(button("Save"))
    assert list(panel.surface.children) == [panel.header, panel.body, panel.footer]
    assert list(panel.body.children) == [field]
    assert "overflow-y-auto" in panel.body.className
    assert "overflow-y-auto" not in panel.surface.className
    assert panel.header.className == panel.footer.className == "shrink-0 px-6 py-4"
    assert panel.dialog_element.getAttribute("data-close-on-backdrop") == "false"
    toolbar_panel = DialogPanel("Toolbar editor", padded_controls=False)
    assert toolbar_panel.header.className == toolbar_panel.footer.className == "shrink-0"
