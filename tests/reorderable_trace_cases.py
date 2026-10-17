from pyjs import js
from pyjs.testing.interaction.reorder import (
    ReorderTraceRecorder,
    replay_reorder_trace,
)
from pyjs.ui.interaction import InteractionProjection, InteractionSample
from pyjs.ui.reorderable import (
    HierarchicalReorder,
    ReorderSession,
)
from pyjs.ui.reorderable import ReorderItem as Item
from pyjs.ui.reorderable import ReorderRow as Row


@js
def assert_reorder_trace_scenarios():
    recorder = ReorderTraceRecorder()
    session = recorder.begin(
        HierarchicalReorder(max_depth=3, indent_step=36),
        [
            Item("private-parent-id", 0),
            Item("private-child-id", 1),
            Item("private-other-id", 0),
        ],
        0,
    )
    assert isinstance(session, ReorderSession)
    rows = [Row("private-other-id", 0, 40)]
    decision = session.update(rows, 30.0, 36.0)
    recorder.updated(
        rows,
        30.0,
        36.0,
        decision,
        sample=InteractionSample("move", 50, 130, 4, 16, 4, 12),
        projections=[
            InteractionProjection("private-parent-id", 36, 12),
        ],
    )
    recorder.committed(decision, "private-other-id", 8)
    trace = recorder.trace()

    assert trace.setup.order == ["item-0", "item-1", "item-2"]
    assert trace.interaction.source_id == "item-0"
    assert trace.interaction.frames[0].measurements[0].item_id == "item-2"
    assert trace.interaction.frames[0].decision.order == [
        "item-2",
        "item-0",
        "item-1",
    ]
    assert trace.interaction.frames[0].decision.depths == [0, 1, 2]
    extensions = trace.interaction.frames[0].extensions
    assert extensions["reorder.content_pointer_y"] == "30"
    assert extensions["reorder.total_delta_x"] == "36"
    assert [sample.phase for sample in trace.interaction.inputs] == ["move"]
    commit = trace.interaction.commit
    if commit is None:
        raise ValueError("Expected a recorded commit")
    assert commit.scroll_anchor_id == "item-2"

    replay = replay_reorder_trace(trace)
    assert replay.comparison.matches()
    assert replay.actual.interaction.frames[0].decision.order == [
        "item-2",
        "item-0",
        "item-1",
    ]
