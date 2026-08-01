import pytest
from pyjs import js
from pyjs.web.dom import document
from pyjs.web.events import Event
from pyjs_examples.samples.ui_dialog.ui_dialog import DialogSample

pytestmark = pytest.mark.pyjs_web


@js
def test_dialog_opens_and_closes():
    document.body.replaceChildren()
    app = DialogSample()
    document.body.append(app)

    app.dialog.trigger.element.dispatchEvent(Event("click"))
    assert app.dialog.is_open
    assert app.dialog.content.dialog_element.open

    app.dialog.close()
    assert not app.dialog.is_open
