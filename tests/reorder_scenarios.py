from pyjs import js
from pyjs.testing.interaction.gesture import GestureScript
from pyjs.testing.interaction.scenario import ReorderScenario
from pyjs.ui.reorderable import ReorderItem, ReorderRow


@js
def mixed_height_cross_axis_scenario() -> ReorderScenario:
    """Move the first row beyond mixed-height siblings, then indent it."""

    return ReorderScenario(
        "mixed-height move with cross-axis indentation",
        [
            ReorderItem("source"),
            ReorderItem("short"),
            ReorderItem("tall"),
            ReorderItem("last"),
        ],
        0,
        [
            ReorderRow("source", 0, 40),
            ReorderRow("short", 40, 40),
            ReorderRow("tall", 80, 160),
            ReorderRow("last", 240, 64),
        ],
        GestureScript()
        .long_press(12, 20, 500)
        .move_to(12, 161, 16)
        .line_to(48, 400, 64, steps=4)
        .release(),
        ["short", "tall", "last", "source"],
        [0, 0, 0, 1],
        max_depth=3,
        indent_step=36,
    )
