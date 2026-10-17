import pytest

from pyjs import js
from pyjs.testing.web import mount, wait_for_frames
from pyjs.web.dom import document
from pyjs.web.domx import CustomElement

pytestmark = pytest.mark.pyjs_web


@js
class LifecycleProbe(CustomElement):
    def __init__(self):
        super().__init__()
        self.initialize_count = 0
        self.reconnect_count = 0
        self.disconnect_count = 0

    def initialize(self):
        self.initialize_count += 1

    def reconnected(self):
        self.reconnect_count += 1

    def disconnected(self):
        self.disconnect_count += 1


@js
class HydrationProbe(CustomElement):
    def initialize(self):
        self.set_data("initialized", "true")


@js
def test_custom_element_distinguishes_initialization_from_reconnection():
    probe = LifecycleProbe()

    mount(probe)
    assert probe.initialize_count == 1
    assert probe.reconnect_count == 0
    assert probe.disconnect_count == 0

    probe.remove()
    assert probe.initialize_count == 1
    assert probe.reconnect_count == 0
    assert probe.disconnect_count == 1

    document.body.append(probe)
    assert probe.initialize_count == 1
    assert probe.reconnect_count == 1
    assert probe.disconnect_count == 1

    probe.remove()
    assert probe.disconnect_count == 2


@js
async def test_detached_element_defers_queued_hydration_until_reconnected():
    probe = HydrationProbe()
    probe.set_data("self-id", "hydration-probe")

    document.body.append(probe)
    probe.remove()
    await wait_for_frames()

    assert probe.get_data("initialized") is None

    document.body.append(probe)
    await wait_for_frames()

    assert probe.get_data("initialized") == "true"
    probe.remove()
