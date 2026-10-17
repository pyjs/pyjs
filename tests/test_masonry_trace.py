from dataclasses import replace

import pytest

from pyjs.testing.interaction.masonry import (
    MasonryTrace,
    MasonryTraceRecorder,
    masonry_trace_from_json,
    masonry_trace_json,
    replay_masonry_trace,
)
from pyjs.ui.interaction import InteractionSample
from pyjs.ui.masonry import (
    MasonryDragSession,
    MasonryDragSimulator,
    MasonryItemGeometry,
    MasonryViewport,
)


def recorded_trace() -> MasonryTrace:
    simulator = MasonryDragSimulator([0, 120], vertical_gap=8)
    items = [
        MasonryItemGeometry("private-a", 100, 80, group="private-notes"),
        MasonryItemGeometry("private-b", 100, 320, group="private-pinned"),
        MasonryItemGeometry("private-c", 100, 60, group="private-notes"),
        MasonryItemGeometry("private-d", 100, 140, group="private-notes"),
    ]
    layout = simulator.layout_in_columns(items, [0, 1, 0, 1])
    viewport = MasonryViewport(10, 20, 240, 180, 40, 400)
    source_rect = layout.rect_for("private-c")
    assert source_rect is not None
    pointer_x = viewport.screen_x + source_rect.x + 20
    pointer_y = viewport.screen_y + source_rect.y - viewport.scroll_offset + 20
    recorder = MasonryTraceRecorder(
        extensions={"platform": "android"},
    )
    session = recorder.begin(
        simulator,
        items,
        2,
        viewport,
        pointer_x,
        pointer_y,
        layout,
        start_elapsed_ms=500,
        clip_columns=False,
        samples=[
            InteractionSample("down", pointer_x, pointer_y),
            InteractionSample("hold", pointer_x, pointer_y, elapsed_ms=500),
        ],
    )
    assert isinstance(session, MasonryDragSession)

    decision = simulator.advance_drag(
        session,
        viewport,
        155,
        165,
        16,
    )
    recorder.updated(
        simulator,
        session,
        viewport,
        155,
        165,
        16,
        decision,
    )
    anchor = simulator.capture_anchor(layout, viewport, session.source_id)
    recorder.committed(
        decision,
        anchor,
        sample=InteractionSample("up", 155, 165, elapsed_ms=520),
    )
    return recorder.trace()


def test_masonry_trace_redacts_private_values_and_round_trips():
    trace = recorded_trace()

    source = masonry_trace_json(trace)

    assert "private-" not in source
    assert trace.setup.items[0].item_id == "item-0"
    assert trace.setup.items[0].group == "group-0"
    assert [item.group for item in trace.setup.items] == [
        "group-0",
        "group-1",
        "group-0",
        "group-0",
    ]
    assert trace.interaction.frames[0].decision.columns
    assert [sample.phase for sample in trace.interaction.inputs] == [
        "down",
        "hold",
        "move",
        "up",
    ]
    assert trace.interaction.commit is not None
    assert trace.interaction.commit.columns
    assert masonry_trace_from_json(source) == trace


def test_masonry_trace_replay_matches_the_recorded_mechanics():
    result = replay_masonry_trace(recorded_trace())

    assert result.comparison.matches()
    assert result.actual == recorded_trace()


@pytest.mark.parametrize(
    ("changed_trace", "stage", "field"),
    [
        (
            lambda trace: replace(
                trace,
                interaction=replace(
                    trace.interaction,
                    frames=[
                        replace(
                            trace.interaction.frames[0],
                            decision=replace(
                                trace.interaction.frames[0].decision,
                                columns=[1, 1, 1, 1],
                            ),
                        )
                    ],
                ),
            ),
            "decision",
            "columns",
        ),
        (
            lambda trace: replace(
                trace,
                interaction=replace(
                    trace.interaction,
                    frames=[
                        replace(
                            trace.interaction.frames[0],
                            projections=[
                                replace(
                                    trace.interaction.frames[0].projections[0],
                                    visible=False,
                                ),
                                *trace.interaction.frames[0].projections[1:],
                            ],
                        )
                    ],
                ),
            ),
            "projection",
            "items[0].visible",
        ),
        (
            lambda trace: replace(
                trace,
                interaction=replace(
                    trace.interaction,
                    commit=replace(
                        trace.interaction.commit,
                        columns=[1, 1, 1, 1],
                    ),
                ),
            ),
            "commit",
            "columns",
        ),
    ],
)
def test_masonry_trace_replay_reports_the_first_divergence(
    changed_trace,
    stage,
    field,
):
    result = replay_masonry_trace(changed_trace(recorded_trace()))

    assert result.comparison.difference is not None
    assert result.comparison.difference.stage == stage
    assert result.comparison.difference.field == field


def test_masonry_trace_requires_a_started_recording():
    with pytest.raises(ValueError, match="has not begun"):
        MasonryTraceRecorder().trace()
