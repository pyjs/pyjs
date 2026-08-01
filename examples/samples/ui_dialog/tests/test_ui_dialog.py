import pytest
from pyjs_examples.samples.ui_dialog.ui_dialog import DialogSample


@pytest.mark.pyjs_python
def test_dialog_sample_has_an_accessible_label():
    app = DialogSample()

    assert app.dialog.content.dialog_element.getAttribute("aria-label") == "Welcome to PyJS"
    assert app.dialog.trigger.element.getAttribute("aria-haspopup") == "dialog"
