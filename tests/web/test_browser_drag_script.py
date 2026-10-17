import pytest

from pyjs import js
from pyjs.testing.interaction.gesture import GestureScript
from pyjs.testing.web import dispatch_drag_script
from pyjs.web.domx import div

pytestmark = pytest.mark.pyjs_web


@js
def test_drag_script_dispatches_the_html_lifecycle_through_an_escape_hatch():
    source = div()
    target = div()
    events: list[str] = []
    source.addEventListener("dragstart", lambda _event: events.append("start"))
    source.addEventListener("dragend", lambda _event: events.append("end"))
    target.addEventListener("dragenter", lambda _event: events.append("enter"))
    target.addEventListener("dragover", lambda _event: events.append("over"))
    target.addEventListener("drop", lambda _event: events.append("drop"))

    transfer = dispatch_drag_script(
        source,
        GestureScript()
        .long_press(10, 10, 500)
        .line_to(90, 90, 32, steps=2)
        .release(),
        lambda _sample: target,
    )

    assert transfer is not None
    assert events == ["start", "enter", "over", "over", "drop", "end"]


@js
def test_cancelled_drag_script_ends_without_dropping():
    source = div()
    events: list[str] = []
    source.addEventListener("dragstart", lambda _event: events.append("start"))
    source.addEventListener("drop", lambda _event: events.append("drop"))
    source.addEventListener("dragend", lambda _event: events.append("end"))

    dispatch_drag_script(source, GestureScript().press(10, 10).cancel())

    assert events == ["start", "end"]
