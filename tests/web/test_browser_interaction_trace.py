import pytest

from pyjs import js
from pyjs.testing.interaction.trace import (
    InteractionDecision,
    InteractionFrame,
    InteractionTrace,
    compare_interaction_traces,
)
from pyjs.ui.interaction import InteractionMeasurement, InteractionSample

pytestmark = pytest.mark.pyjs_web


@js
def test_interaction_trace_comparison_runs_in_the_browser():
    expected = InteractionTrace(
        "reorder",
        "item-0",
        [
            InteractionFrame(
                InteractionSample("move", 10, 20),
                [InteractionMeasurement("item-0", 0, 20, 100, 40)],
                InteractionDecision(
                    destination_index=1,
                    order=["item-1", "item-0"],
                ),
            )
        ],
    )
    matching = InteractionTrace(
        "reorder",
        "item-0",
        [
            InteractionFrame(
                InteractionSample("move", 10, 20),
                [InteractionMeasurement("item-0", 0, 20, 100, 40)],
                InteractionDecision(
                    destination_index=1,
                    order=["item-1", "item-0"],
                ),
            )
        ],
    )
    divergent = InteractionTrace(
        "reorder",
        "item-0",
        [
            InteractionFrame(
                InteractionSample("move", 10, 20),
                [InteractionMeasurement("item-0", 0, 20, 100, 41)],
                InteractionDecision(
                    destination_index=1,
                    order=["item-1", "item-0"],
                ),
            )
        ],
    )

    matching_comparison = compare_interaction_traces(expected, matching)
    assert matching_comparison.matches()
    comparison = compare_interaction_traces(expected, divergent)
    assert not comparison.matches()
    difference = comparison.difference
    if difference is None:
        raise ValueError("Expected a trace difference")
    assert difference.stage == "measurement"
    assert difference.field == "items[0].height"
