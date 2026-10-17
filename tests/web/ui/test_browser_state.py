import pytest

from pyjs import effect, js, state
from pyjs.testing.web import wait_for_frames
from pyjs.web.domx import CustomElement, button, ref, span, tag
from pyjs.web.events import Event
from tests.web.ui.browser import mount

pytestmark = pytest.mark.pyjs_web


@js
class BrowserReactiveCounter(CustomElement):
    count = state(2)

    def __init__(self):
        super().__init__()
        self.output = ref(span())
        self.increment_button = ref(button("+"))
        self.increment_button.addEventListener("click", self.increment)
        tag(self, self.output, self.increment_button)

    @effect(count)
    def render_count(self):
        self.output.textContent = str(self.count)
        effect_runs = self.getAttribute("effect-runs")
        runs = 0 if effect_runs is None else int(effect_runs)
        self.setAttribute("effect-runs", str(runs + 1))

    def increment(self, event: Event):
        self.count += 1


@js
def test_reactive_state_updates_imperative_dom_effects():
    counter = BrowserReactiveCounter()
    mount(counter)

    assert counter.count == 2
    assert counter.getAttribute("count") == "2"
    assert counter.output.textContent == "2"
    assert counter.getAttribute("effect-runs") == "1"

    counter.increment_button.click()

    assert counter.count == 3
    assert counter.getAttribute("count") == "3"
    assert counter.output.textContent == "3"
    assert counter.getAttribute("effect-runs") == "2"

    counter.setAttribute("count", "7")

    assert counter.count == 7
    assert counter.output.textContent == "7"
    assert counter.getAttribute("effect-runs") == "3"


@js
async def test_reactive_state_runs_effects_after_hydrating_element_references():
    counter = BrowserReactiveCounter()
    counter.setAttribute("count", "9")
    counter.setAttribute("data-self-id", "hydrated-counter")
    counter.setAttribute("effect-runs", "1")
    counter.replaceChildren(
        span({"id": "hydrated-counter-output"}, "9"),
        button({"id": "hydrated-counter-increment_button"}, "+"),
    )

    mount(counter)
    await wait_for_frames()

    assert counter.count == 9
    assert counter.output.textContent == "9"
    assert counter.getAttribute("effect-runs") == "1"

    counter.count = 10

    assert counter.output.textContent == "10"
    assert counter.getAttribute("effect-runs") == "2"
