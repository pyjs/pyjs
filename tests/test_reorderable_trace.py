from dataclasses import replace

import pytest

from pyjs.testing.interaction.reorder import (
    ReorderTrace,
    ReorderTraceRecorder,
    reorder_trace_from_json,
    reorder_trace_json,
    replay_reorder_trace,
)
from pyjs.testing.interaction.trace import (
    InteractionDecision,
)
from pyjs.ui.interaction import InteractionMeasurement, InteractionProjection
from pyjs.ui.reorderable import (
    HierarchicalReorder,
    ReorderItem,
)
from pyjs.ui.reorderable import ReorderRow as Row


def recorded_trace(*, redact_ids: bool = True) -> ReorderTrace:
    recorder = ReorderTraceRecorder(redact_ids)
    session = recorder.begin(
        HierarchicalReorder(max_depth=2, indent_step=20),
        [ReorderItem("private-a", 0), ReorderItem("private-b", 0)],
        0,
    )
    if session is None:
        raise AssertionError("Expected a reorder session")
    rows = [Row("private-b", 10, 40)]
    decision = session.update(rows, 40, 20)
    recorder.updated(
        rows,
        40,
        20,
        decision,
        measurements=[
            InteractionMeasurement("private-a", 0, 0, 100, 30),
            InteractionMeasurement("private-b", 0, 10, 100, 40),
        ],
        projections=[
            InteractionProjection("private-a"),
            InteractionProjection("private-b", translate_y=-30),
        ],
    )
    recorder.committed(decision)
    return recorder.trace()


def test_reorder_trace_json_round_trips_without_private_ids():
    trace = recorded_trace()
    source = reorder_trace_json(trace)

    assert "private-a" not in source
    assert "private-b" not in source
    assert reorder_trace_from_json(source) == trace


def test_reorder_trace_can_retain_ids_when_redaction_is_disabled():
    trace = recorded_trace(redact_ids=False)

    assert trace.setup.order == ["private-a", "private-b"]
    assert trace.interaction.source_id == "private-a"


def test_replay_reports_the_first_incorrect_decision():
    trace = recorded_trace()
    frame = trace.interaction.frames[0]
    incorrect = replace(
        trace,
        interaction=replace(
            trace.interaction,
            frames=[
                replace(
                    frame,
                    decision=InteractionDecision(
                        slot="index:0",
                        destination_index=0,
                        destination_depth=frame.decision.destination_depth,
                        order=frame.decision.order,
                        depths=frame.decision.depths,
                    ),
                )
            ],
        ),
    )

    comparison = replay_reorder_trace(incorrect).comparison
    assert not comparison.matches()
    assert comparison.difference is not None
    assert comparison.difference.stage == "decision"
    assert comparison.difference.field == "slot"


def test_replay_reports_an_incorrect_platform_projection():
    trace = recorded_trace()
    frame = trace.interaction.frames[0]
    incorrect = replace(
        trace,
        interaction=replace(
            trace.interaction,
            frames=[
                replace(
                    frame,
                    projections=[
                        frame.projections[0],
                        replace(frame.projections[1], translate_y=-10),
                    ],
                )
            ],
        ),
    )

    comparison = replay_reorder_trace(incorrect).comparison
    assert not comparison.matches()
    assert comparison.difference is not None
    assert comparison.difference.stage == "projection"
    assert comparison.difference.field == "items[1].translate_y"


def test_replay_accepts_traces_recorded_before_logical_input_extensions():
    trace = recorded_trace()
    frame = trace.interaction.frames[0]
    compatible = replace(
        trace,
        interaction=replace(
            trace.interaction,
            frames=[replace(frame, extensions={})],
        ),
    )

    assert replay_reorder_trace(compatible).comparison.matches()


def test_trace_requires_recording_to_begin():
    with pytest.raises(
        ValueError,
        match="Reorder trace recording has not begun.",
    ):
        ReorderTraceRecorder().trace()
