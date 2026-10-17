import pytest

from pyjs.testing.interaction.gesture import GestureScript, InteractionClock
from pyjs.ui.interaction import InteractionSampler
from tests.gesture_cases import assert_gesture_scenarios


def test_gesture_scenarios():
    assert_gesture_scenarios()


def test_gesture_rejects_invalid_pointer_lifecycle():
    with pytest.raises(ValueError, match="The gesture pointer is not pressed."):
        GestureScript().move_to(1, 2)

    script = GestureScript().press(1, 2)
    with pytest.raises(ValueError, match="The gesture pointer is already pressed."):
        script.press(3, 4)

    script.cancel().press(5, 6)
    assert script.samples[-1].phase == "down"
    assert script.samples[-1].delta_x == 0
    assert script.samples[-1].delta_y == 0


def test_interaction_clock_reports_unsettled_phase():
    clock = InteractionClock()
    clock.begin_phase("animation")

    with pytest.raises(
        ValueError,
        match="Interaction phase 'animation' has not settled.",
    ):
        clock.require_settled("animation")


def test_interaction_sampler_rejects_invalid_pointer_lifecycle():
    sampler = InteractionSampler()
    with pytest.raises(ValueError, match="not active"):
        sampler.sample("move", 1, 2, 10)

    sampler.begin(1, 2, 10)
    with pytest.raises(ValueError, match="already active"):
        sampler.begin(1, 2, 10)
    with pytest.raises(ValueError, match="Use begin"):
        sampler.sample("down", 1, 2, 10)
