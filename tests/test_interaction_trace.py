import json
from dataclasses import replace

import pytest

from pyjs.testing.interaction.trace import (
    InteractionCommit,
    InteractionDecision,
    InteractionFrame,
    InteractionTrace,
    assert_interaction_traces_match,
    compare_interaction_traces,
    interaction_trace_from_dict,
    interaction_trace_from_json,
    interaction_trace_json,
)
from pyjs.ui.interaction import (
    InteractionMeasurement,
    InteractionProjection,
    InteractionSample,
    InteractionViewport,
)


def interaction_trace() -> InteractionTrace:
    return InteractionTrace(
        "reorder",
        "item-0",
        [
            InteractionFrame(
                InteractionSample("move", 12.5, 30, 7, 16),
                [InteractionMeasurement("item-0", 10, 20, 100, 40)],
                InteractionDecision(
                    slot="before:item-1",
                    destination_index=1,
                    destination_depth=0,
                    order=["item-1", "item-0"],
                    depths=[0, 0],
                    columns=[1, 0],
                ),
                InteractionViewport(0, 0, 320, 240, 0, 12, 320, 800),
                [InteractionProjection("item-0", 0, 40)],
                {"platform.phase": "layout"},
            )
        ],
        InteractionCommit(
            ["item-1", "item-0"],
            [0, 0],
            "item-1",
            4,
            {"platform.animation": "settled"},
            [1, 0],
        ),
        {"platform": "web"},
    )


def difference_for(actual: InteractionTrace):
    return compare_interaction_traces(interaction_trace(), actual).difference


def test_trace_json_is_deterministic_and_round_trips():
    source = interaction_trace_json(interaction_trace())

    assert source == """{
  "commit": {
    "columns": [
      1,
      0
    ],
    "depths": [
      0,
      0
    ],
    "extensions": {
      "platform.animation": "settled"
    },
    "order": [
      "item-1",
      "item-0"
    ],
    "scroll_anchor_id": "item-1",
    "scroll_anchor_offset": 4
  },
  "extensions": {
    "platform": "web"
  },
  "frames": [
    {
      "decision": {
        "columns": [
          1,
          0
        ],
        "depths": [
          0,
          0
        ],
        "destination_column": -1,
        "destination_depth": 0,
        "destination_index": 1,
        "destination_lane": -1,
        "group": "",
        "order": [
          "item-1",
          "item-0"
        ],
        "scroll_offset": 0,
        "slot": "before:item-1"
      },
      "extensions": {
        "platform.phase": "layout"
      },
      "measurements": [
        {
          "clipped": false,
          "height": 40,
          "item_id": "item-0",
          "width": 100,
          "x": 10,
          "y": 20
        }
      ],
      "projections": [
        {
          "clip_height": 0,
          "clip_width": 0,
          "clip_x": 0,
          "clip_y": 0,
          "item_id": "item-0",
          "translate_x": 0,
          "translate_y": 40,
          "visible": true
        }
      ],
      "sample": {
        "delta_x": 0,
        "delta_y": 0,
        "elapsed_ms": 16,
        "phase": "move",
        "pointer_id": 7,
        "x": 12.5,
        "y": 30
      },
      "viewport": {
        "content_height": 800,
        "content_width": 320,
        "height": 240,
        "scroll_x": 0,
        "scroll_y": 12,
        "width": 320,
        "x": 0,
        "y": 0
      }
    }
  ],
  "inputs": [],
  "kind": "reorder",
  "source_id": "item-0",
  "version": 1
}"""
    assert interaction_trace_from_json(source) == interaction_trace()


def test_trace_json_without_column_fields_remains_compatible():
    value = json.loads(interaction_trace_json(interaction_trace()))
    del value["frames"][0]["decision"]["columns"]
    del value["commit"]["columns"]
    del value["inputs"]

    trace = interaction_trace_from_dict(value)

    assert trace.frames[0].decision.columns == []
    assert trace.commit is not None
    assert trace.commit.columns == []


def test_comparison_reports_raw_input_timeline_divergence():
    expected = replace(
        interaction_trace(),
        inputs=[InteractionSample("down", 10, 20, 4, 0)],
    )
    actual = replace(
        expected,
        inputs=[InteractionSample("down", 10, 20, 4, 5)],
    )

    difference = compare_interaction_traces(expected, actual).difference

    assert difference is not None
    assert difference.stage == "input"
    assert difference.field == "elapsed_ms"


def test_comparison_accepts_small_measurement_and_projection_differences():
    expected = interaction_trace()
    frame = expected.frames[0]
    measurement = replace(frame.measurements[0], y=20.0009)
    projection = replace(frame.projections[0], translate_y=40.0009)
    actual = replace(
        expected,
        frames=[
            replace(
                frame,
                measurements=[measurement],
                projections=[projection],
            )
        ],
    )

    assert compare_interaction_traces(expected, actual).matches()


@pytest.mark.parametrize(
    ("actual", "stage", "field"),
    [
        (
            replace(
                interaction_trace(),
                frames=[
                    replace(
                        interaction_trace().frames[0],
                        sample=replace(
                            interaction_trace().frames[0].sample,
                            phase="cancel",
                        ),
                    )
                ],
            ),
            "input",
            "phase",
        ),
        (
            replace(
                interaction_trace(),
                frames=[
                    replace(
                        interaction_trace().frames[0],
                        measurements=[
                            replace(
                                interaction_trace().frames[0].measurements[0],
                                height=42,
                            )
                        ],
                    )
                ],
            ),
            "measurement",
            "items[0].height",
        ),
        (
            replace(
                interaction_trace(),
                frames=[
                    replace(
                        interaction_trace().frames[0],
                        viewport=replace(
                            interaction_trace().frames[0].viewport,
                            scroll_y=24,
                        ),
                    )
                ],
            ),
            "viewport",
            "scroll_y",
        ),
        (
            replace(
                interaction_trace(),
                frames=[
                    replace(
                        interaction_trace().frames[0],
                        decision=replace(
                            interaction_trace().frames[0].decision,
                            destination_depth=1,
                        ),
                    )
                ],
            ),
            "decision",
            "destination_depth",
        ),
        (
            replace(
                interaction_trace(),
                frames=[
                    replace(
                        interaction_trace().frames[0],
                        decision=replace(
                            interaction_trace().frames[0].decision,
                            columns=[0, 1],
                        ),
                    )
                ],
            ),
            "decision",
            "columns",
        ),
        (
            replace(
                interaction_trace(),
                frames=[
                    replace(
                        interaction_trace().frames[0],
                        projections=[
                            replace(
                                interaction_trace().frames[0].projections[0],
                                visible=False,
                            )
                        ],
                    )
                ],
            ),
            "projection",
            "items[0].visible",
        ),
        (
            replace(
                interaction_trace(),
                commit=replace(interaction_trace().commit, scroll_anchor_id="item-0"),
            ),
            "commit",
            "scroll_anchor_id",
        ),
        (
            replace(
                interaction_trace(),
                commit=replace(interaction_trace().commit, columns=[0, 1]),
            ),
            "commit",
            "columns",
        ),
        (
            replace(interaction_trace(), extensions={"platform": "android"}),
            "extension",
            "platform",
        ),
    ],
)
def test_comparison_reports_the_first_divergence(actual, stage, field):
    difference = difference_for(actual)

    assert difference is not None
    assert difference.stage == stage
    assert difference.field == field


def test_assertion_explains_the_divergent_stage_frame_and_field():
    expected = interaction_trace()
    frame = expected.frames[0]
    actual = replace(
        expected,
        frames=[
            replace(
                frame,
                measurements=[replace(frame.measurements[0], height=44)],
            )
        ],
    )

    with pytest.raises(
        AssertionError,
        match=r"measurement frame 0 diverged at items\[0\]\.height: expected 40, got 44",
    ):
        assert_interaction_traces_match(expected, actual)
