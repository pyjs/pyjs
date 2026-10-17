import pytest

from pyjs import js
from pyjs.testing.interaction.gesture import (
    GesturePoint,
    GestureScript,
    InteractionClock,
)
from pyjs.testing.web import (
    dispatch_pointer_script,
    wait_for_event,
    wait_for_settled_phase,
)
from pyjs.web.dom import document
from pyjs.web.domx import div, require_closest, require_element, span
from pyjs.web.events import PointerEvent


@js
class PointerListener:
    def __init__(self):
        self.events: list[str] = []
        self.positions: list[int] = []

    @js.keep
    def handleEvent(self, event: PointerEvent):
        self.events.append(event.type)
        self.positions.append(event.clientX)


@pytest.mark.pyjs_web
@js
async def test_wait_for_event_is_armed_before_a_synchronous_action():
    target = div()

    event = await wait_for_event(target, "click", target.click)

    assert event.type == "click"


@pytest.mark.pyjs_web
@js
async def test_wait_for_event_can_await_an_already_scheduled_event():
    styles = document.createElement("style")
    styles.textContent = "@keyframes pyjs-finish { from { opacity:.99 } to { opacity:1 } }"
    document.head.append(styles)
    target = document.createElement("div")
    target.setAttribute("style", "animation:pyjs-finish 1ms linear")
    document.body.append(target)

    event = await wait_for_event(target, "animationend")

    assert event.type == "animationend"


@pytest.mark.pyjs_web
@js
def test_require_element_returns_a_matching_element():
    element = document.createElement("div")
    element.setAttribute("data-testid", "match")
    document.body.append(element)

    assert require_element(document.body, "[data-testid=match]") is element


@pytest.mark.pyjs_web
@js
def test_require_element_raises_when_the_selector_does_not_match():
    message = ""
    try:
        require_element(document.body, "[data-testid=missing]")
    except Exception as error:
        message = error.message
    assert message == "Required element not found: [data-testid=missing]"


@pytest.mark.pyjs_web
@js
def test_require_closest_returns_a_matching_ancestor():
    ancestor = div({"data-testid": "ancestor"}, span())
    child = ancestor.children[0]

    assert require_closest(child, "[data-testid=ancestor]") is ancestor


@pytest.mark.pyjs_web
@js
def test_require_closest_raises_when_the_selector_does_not_match():
    child = span()
    message = ""
    try:
        require_closest(child, "[data-testid=missing]")
    except Exception as error:
        message = error.message
    assert message == "Required ancestor not found: [data-testid=missing]"


@pytest.mark.pyjs_web
@js
def test_pointer_script_dispatches_the_common_gesture_as_dom_events():
    target = div()
    listener = PointerListener()
    target.addEventListener("pointerdown", listener)
    target.addEventListener("pointermove", listener)
    target.addEventListener("pointerup", listener)
    script = (
        GestureScript()
        .long_press(10, 20, 500)
        .path([GesturePoint(15, 25, 20)])
        .release()
    )
    clock = InteractionClock(100)

    dispatch_pointer_script(target, script, clock)

    assert listener.events == [
        "pointerdown",
        "pointermove",
        "pointermove",
        "pointerup",
    ]
    assert listener.positions == [10, 10, 15, 15]
    assert clock.now() == 620


@pytest.mark.pyjs_web
@js
async def test_settled_phase_wait_returns_without_sleeping():
    clock = InteractionClock()

    await wait_for_settled_phase(clock, "layout")

    assert clock.is_settled("layout")


@pytest.mark.pyjs_web
@js
async def test_settled_phase_wait_has_a_bounded_failure():
    clock = InteractionClock()
    clock.begin_phase("layout")
    message = ""

    try:
        await wait_for_settled_phase(clock, "layout", max_frames=0)
    except Exception as error:
        message = error.message

    assert message == "Interaction phase 'layout' did not settle."
