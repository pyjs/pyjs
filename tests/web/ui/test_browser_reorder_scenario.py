import pytest

from pyjs import js
from pyjs.testing.interaction.reorder import play_reorder_gesture
from pyjs.testing.web import mount
from pyjs.web.domx import div
from pyjs.web.ui.reorderable import ReorderableOutlineController
from tests.reorder_scenarios import mixed_height_cross_axis_scenario

pytestmark = pytest.mark.pyjs_web


@js
def test_shared_reorder_scenario_runs_against_browser_geometry():
    scenario = mixed_height_cross_axis_scenario()
    container = div()
    for row in scenario.rows:
        container.append(
            div(
                {
                    "data-reorder-id": row.id,
                    "style": "height: " + str(row.size) + "px",
                }
            )
        )
    mount(container)
    controller = ReorderableOutlineController(
        container,
        max_depth=scenario.max_depth,
        indent_step=scenario.indent_step,
    )

    controller.begin(scenario.items, scenario.source_index)
    scenario.assert_decision(play_reorder_gesture(controller, scenario.gesture))
