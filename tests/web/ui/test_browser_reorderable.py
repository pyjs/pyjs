import pytest

from pyjs import js
from pyjs.testing.interaction.gesture import GestureScript
from pyjs.testing.interaction.reorder import (
    ReorderTraceRecorder,
    play_reorder_gesture,
)
from pyjs.ui.reorderable import ReorderDecision, ReorderItem, ReorderSession
from pyjs.web.dom import document
from pyjs.web.domx import div
from pyjs.web.ui.reorderable import ReorderableOutlineController

pytestmark = pytest.mark.pyjs_web


@js
def test_reorderable_outline_collapses_descendants_and_uses_dom_geometry():
    container = div()
    parent = div(
        {"data-reorder-id": "parent", "style": "height: 40px"},
        "Parent",
    )
    child = div(
        {"data-reorder-id": "child", "style": "height: 80px"},
        "Child",
    )
    leaf = div(
        {"data-reorder-id": "leaf", "style": "height: 120px"},
        "Leaf",
    )
    other = div(
        {"data-reorder-id": "other", "style": "height: 48px"},
        "Other",
    )
    container.append(parent, child, leaf, other)
    document.body.append(container)
    recorder = ReorderTraceRecorder(extensions={"platform": "web"})
    controller = ReorderableOutlineController(
        container,
        max_depth=2,
        observer=recorder,
    )

    session = controller.begin(
        [
            ReorderItem("parent", 0),
            ReorderItem("child", 1),
            ReorderItem("leaf", 2),
            ReorderItem("other", 0),
        ],
        0,
    )
    assert isinstance(session, ReorderSession)
    assert child.hidden
    assert leaf.hidden
    bounds = other.getBoundingClientRect()
    decision = play_reorder_gesture(
        controller,
        GestureScript()
        .long_press(0, bounds.top, 500)
        .move_to(0, bounds.bottom + 1, 16)
        .release(),
        recorder,
    )
    assert isinstance(decision, ReorderDecision)
    assert decision.visible_item_ids() == ["other", "parent"]
    assert decision.committed_depths() == [0, 0, 1, 2]
    controller.commit(scroll_anchor_id="other", scroll_anchor_offset=3)
    trace = recorder.trace()
    assert [sample.phase for sample in trace.interaction.inputs] == [
        "down",
        "hold",
        "move",
        "up",
    ]
    assert trace.interaction.frames[1].measurements[3].item_id == "item-3"
    assert trace.interaction.frames[1].measurements[3].height == bounds.height
    viewport = trace.interaction.frames[1].viewport
    if viewport is None:
        raise ValueError("Expected a captured viewport")
    assert viewport.width > 0
    commit = trace.interaction.commit
    if commit is None:
        raise ValueError("Expected a recorded commit")
    assert commit.scroll_anchor_id == "item-3"

    fixed_pointer = bounds.top + 30
    cached_decision = controller.update(fixed_pointer, 0)
    assert isinstance(cached_decision, ReorderDecision)
    assert cached_decision.insertion_index == 1
    other.style.height = "100px"
    stale_decision = controller.update(fixed_pointer, 0)
    assert isinstance(stale_decision, ReorderDecision)
    assert stale_decision.insertion_index == 1
    controller.refresh_geometry()
    refreshed_decision = controller.update(fixed_pointer, 0)
    assert isinstance(refreshed_decision, ReorderDecision)
    assert refreshed_decision.insertion_index == 0

    controller.clear()
    assert child.hidden is False
    assert leaf.hidden is False
    container.remove()
