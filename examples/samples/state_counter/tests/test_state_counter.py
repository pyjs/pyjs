import pytest
from pyjs import js
from pyjs.web.events import Event
from pyjs_examples.samples.state_counter.state_counter import Counter


@pytest.mark.pyjs_python
@js
def test_counter_changes_in_both_directions():
    counter = Counter()

    counter.increment(Event("click"))
    counter.increment(Event("click"))
    counter.decrement(Event("click"))

    assert counter.count == 1
    assert counter.value.textContent == "1"
