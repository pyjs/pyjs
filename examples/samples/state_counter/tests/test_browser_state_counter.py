import pytest
from pyjs import js
from pyjs.web.dom import document
from pyjs.web.events import Event
from pyjs_examples.samples.state_counter.state_counter import Counter

pytestmark = pytest.mark.pyjs_web


@js
def test_counter_buttons_update_the_mounted_element():
    document.body.replaceChildren()
    counter = Counter()
    document.body.append(counter)

    counter.increment_button.dispatchEvent(Event("click"))

    assert counter.value.textContent == "1"
