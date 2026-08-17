import json
from dataclasses import asdict, dataclass, field

from pyjs import js
from pyjs.python import repr_value


@js
@dataclass(frozen=True, repr=False)
class InteractionSample:
    phase: str
    x: float = 0
    y: float = 0
    pointer_id: int = 0
    elapsed_ms: float = 0
    delta_x: float = 0
    delta_y: float = 0


@js
@dataclass(frozen=True, repr=False)
class InteractionMeasurement:
    item_id: str
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    clipped: bool = False


@js
@dataclass(frozen=True, repr=False)
class InteractionViewport:
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    scroll_x: float = 0
    scroll_y: float = 0
    content_width: float = 0
    content_height: float = 0


@js
@dataclass(frozen=True, repr=False)
class InteractionDecision:
    slot: str = ""
    destination_index: int = -1
    destination_depth: int = -1
    destination_column: int = -1
    destination_lane: int = -1
    group: str = ""
    scroll_offset: float = 0
    order: list[str] = field(default_factory=list)
    depths: list[int] = field(default_factory=list)


@js
@dataclass(frozen=True, repr=False)
class InteractionProjection:
    item_id: str
    translate_x: float = 0
    translate_y: float = 0
    visible: bool = True
    clip_x: float = 0
    clip_y: float = 0
    clip_width: float = 0
    clip_height: float = 0


@js
@dataclass(frozen=True, repr=False)
class InteractionFrame:
    sample: InteractionSample
    measurements: list[InteractionMeasurement]
    decision: InteractionDecision
    viewport: InteractionViewport | None = None
    projections: list[InteractionProjection] = field(default_factory=list)
    extensions: dict[str, str] = field(default_factory=dict)


@js
@dataclass(frozen=True, repr=False)
class InteractionCommit:
    order: list[str]
    depths: list[int] = field(default_factory=list)
    scroll_anchor_id: str = ""
    scroll_anchor_offset: float = 0
    extensions: dict[str, str] = field(default_factory=dict)


@js
@dataclass(frozen=True, repr=False)
class InteractionTrace:
    kind: str
    source_id: str
    frames: list[InteractionFrame] = field(default_factory=list)
    commit: InteractionCommit | None = None
    extensions: dict[str, str] = field(default_factory=dict)
    version: int = 1


@js
@dataclass(frozen=True, repr=False)
class InteractionDifference:
    frame_index: int
    stage: str
    field: str
    expected: str
    actual: str

    def describe(self) -> str:
        location = self.stage
        if self.frame_index >= 0:
            location += " frame " + str(self.frame_index)
        return (
            location
            + " diverged at "
            + self.field
            + ": expected "
            + self.expected
            + ", got "
            + self.actual
        )


@js
@dataclass(frozen=True, repr=False)
class InteractionComparison:
    difference: InteractionDifference | None = None

    def matches(self) -> bool:
        return self.difference is None


@js
def _display_value(value: object) -> str:
    return repr(value)


@_display_value.client
def _display_value(value: object) -> str:
    return repr_value(value)


@js
def _different_float(left: float, right: float, tolerance: float) -> bool:
    return abs(left - right) > tolerance


@js
def _difference(
    frame_index: int,
    stage: str,
    field_name: str,
    expected: object,
    actual: object,
) -> InteractionComparison:
    return InteractionComparison(
        InteractionDifference(
            frame_index,
            stage,
            field_name,
            _display_value(expected),
            _display_value(actual),
        )
    )


@js
def _compare_sample(
    frame_index: int,
    expected: InteractionSample,
    actual: InteractionSample,
    tolerance: float,
) -> InteractionComparison:
    if expected.phase != actual.phase:
        return _difference(frame_index, "input", "phase", expected.phase, actual.phase)
    if _different_float(expected.x, actual.x, tolerance):
        return _difference(frame_index, "input", "x", expected.x, actual.x)
    if _different_float(expected.y, actual.y, tolerance):
        return _difference(frame_index, "input", "y", expected.y, actual.y)
    if expected.pointer_id != actual.pointer_id:
        return _difference(
            frame_index,
            "input",
            "pointer_id",
            expected.pointer_id,
            actual.pointer_id,
        )
    if _different_float(expected.elapsed_ms, actual.elapsed_ms, tolerance):
        return _difference(
            frame_index,
            "input",
            "elapsed_ms",
            expected.elapsed_ms,
            actual.elapsed_ms,
        )
    if _different_float(expected.delta_x, actual.delta_x, tolerance):
        return _difference(
            frame_index,
            "input",
            "delta_x",
            expected.delta_x,
            actual.delta_x,
        )
    if _different_float(expected.delta_y, actual.delta_y, tolerance):
        return _difference(
            frame_index,
            "input",
            "delta_y",
            expected.delta_y,
            actual.delta_y,
        )
    return InteractionComparison()


@js
def _compare_measurements(
    frame_index: int,
    expected: list[InteractionMeasurement],
    actual: list[InteractionMeasurement],
    tolerance: float,
) -> InteractionComparison:
    if len(expected) != len(actual):
        return _difference(
            frame_index,
            "measurement",
            "count",
            len(expected),
            len(actual),
        )
    for index in range(len(expected)):
        left = expected[index]
        right = actual[index]
        prefix = "items[" + str(index) + "]."
        if left.item_id != right.item_id:
            return _difference(
                frame_index,
                "measurement",
                prefix + "item_id",
                left.item_id,
                right.item_id,
            )
        if _different_float(left.x, right.x, tolerance):
            return _difference(
                frame_index, "measurement", prefix + "x", left.x, right.x
            )
        if _different_float(left.y, right.y, tolerance):
            return _difference(
                frame_index, "measurement", prefix + "y", left.y, right.y
            )
        if _different_float(left.width, right.width, tolerance):
            return _difference(
                frame_index,
                "measurement",
                prefix + "width",
                left.width,
                right.width,
            )
        if _different_float(left.height, right.height, tolerance):
            return _difference(
                frame_index,
                "measurement",
                prefix + "height",
                left.height,
                right.height,
            )
        if left.clipped != right.clipped:
            return _difference(
                frame_index,
                "measurement",
                prefix + "clipped",
                left.clipped,
                right.clipped,
            )
    return InteractionComparison()


@js
def _compare_viewport(
    frame_index: int,
    expected: InteractionViewport | None,
    actual: InteractionViewport | None,
    tolerance: float,
) -> InteractionComparison:
    if expected is None:
        if actual is None:
            return InteractionComparison()
        return _difference(frame_index, "viewport", "state", expected, actual)
    if actual is None:
        return _difference(frame_index, "viewport", "state", expected, actual)
    if _different_float(expected.x, actual.x, tolerance):
        return _difference(frame_index, "viewport", "x", expected.x, actual.x)
    if _different_float(expected.y, actual.y, tolerance):
        return _difference(frame_index, "viewport", "y", expected.y, actual.y)
    if _different_float(expected.width, actual.width, tolerance):
        return _difference(
            frame_index, "viewport", "width", expected.width, actual.width
        )
    if _different_float(expected.height, actual.height, tolerance):
        return _difference(
            frame_index, "viewport", "height", expected.height, actual.height
        )
    if _different_float(expected.scroll_x, actual.scroll_x, tolerance):
        return _difference(
            frame_index, "viewport", "scroll_x", expected.scroll_x, actual.scroll_x
        )
    if _different_float(expected.scroll_y, actual.scroll_y, tolerance):
        return _difference(
            frame_index, "viewport", "scroll_y", expected.scroll_y, actual.scroll_y
        )
    if _different_float(expected.content_width, actual.content_width, tolerance):
        return _difference(
            frame_index,
            "viewport",
            "content_width",
            expected.content_width,
            actual.content_width,
        )
    if _different_float(expected.content_height, actual.content_height, tolerance):
        return _difference(
            frame_index,
            "viewport",
            "content_height",
            expected.content_height,
            actual.content_height,
        )
    return InteractionComparison()


@js
def _compare_decision(
    frame_index: int,
    expected: InteractionDecision,
    actual: InteractionDecision,
    tolerance: float,
) -> InteractionComparison:
    if expected.slot != actual.slot:
        return _difference(frame_index, "decision", "slot", expected.slot, actual.slot)
    if expected.destination_index != actual.destination_index:
        return _difference(
            frame_index,
            "decision",
            "destination_index",
            expected.destination_index,
            actual.destination_index,
        )
    if expected.destination_depth != actual.destination_depth:
        return _difference(
            frame_index,
            "decision",
            "destination_depth",
            expected.destination_depth,
            actual.destination_depth,
        )
    if expected.destination_column != actual.destination_column:
        return _difference(
            frame_index,
            "decision",
            "destination_column",
            expected.destination_column,
            actual.destination_column,
        )
    if expected.destination_lane != actual.destination_lane:
        return _difference(
            frame_index,
            "decision",
            "destination_lane",
            expected.destination_lane,
            actual.destination_lane,
        )
    if expected.group != actual.group:
        return _difference(frame_index, "decision", "group", expected.group, actual.group)
    if _different_float(expected.scroll_offset, actual.scroll_offset, tolerance):
        return _difference(
            frame_index,
            "decision",
            "scroll_offset",
            expected.scroll_offset,
            actual.scroll_offset,
        )
    if expected.order != actual.order:
        return _difference(frame_index, "decision", "order", expected.order, actual.order)
    if expected.depths != actual.depths:
        return _difference(
            frame_index, "decision", "depths", expected.depths, actual.depths
        )
    return InteractionComparison()


@js
def _compare_projections(
    frame_index: int,
    expected: list[InteractionProjection],
    actual: list[InteractionProjection],
    tolerance: float,
) -> InteractionComparison:
    if len(expected) != len(actual):
        return _difference(
            frame_index,
            "projection",
            "count",
            len(expected),
            len(actual),
        )
    for index in range(len(expected)):
        left = expected[index]
        right = actual[index]
        prefix = "items[" + str(index) + "]."
        if left.item_id != right.item_id:
            return _difference(
                frame_index,
                "projection",
                prefix + "item_id",
                left.item_id,
                right.item_id,
            )
        if _different_float(left.translate_x, right.translate_x, tolerance):
            return _difference(
                frame_index,
                "projection",
                prefix + "translate_x",
                left.translate_x,
                right.translate_x,
            )
        if _different_float(left.translate_y, right.translate_y, tolerance):
            return _difference(
                frame_index,
                "projection",
                prefix + "translate_y",
                left.translate_y,
                right.translate_y,
            )
        if left.visible != right.visible:
            return _difference(
                frame_index,
                "projection",
                prefix + "visible",
                left.visible,
                right.visible,
            )
        if _different_float(left.clip_x, right.clip_x, tolerance):
            return _difference(
                frame_index,
                "projection",
                prefix + "clip_x",
                left.clip_x,
                right.clip_x,
            )
        if _different_float(left.clip_y, right.clip_y, tolerance):
            return _difference(
                frame_index,
                "projection",
                prefix + "clip_y",
                left.clip_y,
                right.clip_y,
            )
        if _different_float(left.clip_width, right.clip_width, tolerance):
            return _difference(
                frame_index,
                "projection",
                prefix + "clip_width",
                left.clip_width,
                right.clip_width,
            )
        if _different_float(left.clip_height, right.clip_height, tolerance):
            return _difference(
                frame_index,
                "projection",
                prefix + "clip_height",
                left.clip_height,
                right.clip_height,
            )
    return InteractionComparison()


@js
def _compare_extensions(
    frame_index: int,
    stage: str,
    expected: dict[str, str],
    actual: dict[str, str],
) -> InteractionComparison:
    if len(expected) != len(actual):
        return _difference(frame_index, stage, "count", len(expected), len(actual))
    for key, expected_value in expected.items():
        if key not in actual:
            return _difference(frame_index, stage, key, expected_value, "<missing>")
        actual_value = actual[key]
        if expected_value != actual_value:
            return _difference(
                frame_index,
                stage,
                key,
                expected_value,
                actual_value,
            )
    return InteractionComparison()


@js
def _compare_commit(
    expected: InteractionCommit | None,
    actual: InteractionCommit | None,
    tolerance: float,
) -> InteractionComparison:
    if expected is None:
        if actual is None:
            return InteractionComparison()
        return _difference(-1, "commit", "state", expected, actual)
    if actual is None:
        return _difference(-1, "commit", "state", expected, actual)
    if expected.order != actual.order:
        return _difference(-1, "commit", "order", expected.order, actual.order)
    if expected.depths != actual.depths:
        return _difference(-1, "commit", "depths", expected.depths, actual.depths)
    if expected.scroll_anchor_id != actual.scroll_anchor_id:
        return _difference(
            -1,
            "commit",
            "scroll_anchor_id",
            expected.scroll_anchor_id,
            actual.scroll_anchor_id,
        )
    if _different_float(
        expected.scroll_anchor_offset,
        actual.scroll_anchor_offset,
        tolerance,
    ):
        return _difference(
            -1,
            "commit",
            "scroll_anchor_offset",
            expected.scroll_anchor_offset,
            actual.scroll_anchor_offset,
        )
    return _compare_extensions(
        -1,
        "commit extension",
        expected.extensions,
        actual.extensions,
    )


@js
def compare_interaction_traces(
    expected: InteractionTrace,
    actual: InteractionTrace,
    tolerance: float = 0.001,
) -> InteractionComparison:
    if expected.version != actual.version:
        return _difference(-1, "trace", "version", expected.version, actual.version)
    if expected.kind != actual.kind:
        return _difference(-1, "trace", "kind", expected.kind, actual.kind)
    if expected.source_id != actual.source_id:
        return _difference(
            -1, "trace", "source_id", expected.source_id, actual.source_id
        )
    if len(expected.frames) != len(actual.frames):
        return _difference(
            -1, "trace", "frame_count", len(expected.frames), len(actual.frames)
        )
    for index in range(len(expected.frames)):
        left = expected.frames[index]
        right = actual.frames[index]
        comparison = _compare_sample(index, left.sample, right.sample, tolerance)
        if not comparison.matches():
            return comparison
        comparison = _compare_measurements(
            index,
            left.measurements,
            right.measurements,
            tolerance,
        )
        if not comparison.matches():
            return comparison
        comparison = _compare_viewport(
            index,
            left.viewport,
            right.viewport,
            tolerance,
        )
        if not comparison.matches():
            return comparison
        comparison = _compare_decision(
            index,
            left.decision,
            right.decision,
            tolerance,
        )
        if not comparison.matches():
            return comparison
        comparison = _compare_extensions(
            index,
            "extension",
            left.extensions,
            right.extensions,
        )
        if not comparison.matches():
            return comparison
        comparison = _compare_projections(
            index,
            left.projections,
            right.projections,
            tolerance,
        )
        if not comparison.matches():
            return comparison
    comparison = _compare_commit(expected.commit, actual.commit, tolerance)
    if not comparison.matches():
        return comparison
    return _compare_extensions(-1, "extension", expected.extensions, actual.extensions)


def interaction_trace_json(trace: InteractionTrace, *, indent: int = 2) -> str:
    return json.dumps(asdict(trace), indent=indent, sort_keys=True)


def interaction_trace_from_dict(value: dict[str, object]) -> InteractionTrace:
    frames: list[InteractionFrame] = []
    for frame in value["frames"]:
        viewport = frame["viewport"]
        frames.append(
            InteractionFrame(
                InteractionSample(**frame["sample"]),
                [
                    InteractionMeasurement(**measurement)
                    for measurement in frame["measurements"]
                ],
                InteractionDecision(**frame["decision"]),
                InteractionViewport(**viewport) if viewport is not None else None,
                [
                    InteractionProjection(**projection)
                    for projection in frame["projections"]
                ],
                frame["extensions"],
            )
        )
    commit = value["commit"]
    return InteractionTrace(
        value["kind"],
        value["source_id"],
        frames,
        InteractionCommit(**commit) if commit is not None else None,
        value["extensions"],
        value["version"],
    )


def interaction_trace_from_json(source: str) -> InteractionTrace:
    return interaction_trace_from_dict(json.loads(source))


def assert_interaction_traces_match(
    expected: InteractionTrace,
    actual: InteractionTrace,
    tolerance: float = 0.001,
) -> None:
    comparison = compare_interaction_traces(expected, actual, tolerance)
    if comparison.difference is not None:
        raise AssertionError(comparison.difference.describe())


__all__ = [
    "InteractionCommit",
    "InteractionComparison",
    "InteractionDecision",
    "InteractionDifference",
    "InteractionFrame",
    "InteractionMeasurement",
    "InteractionProjection",
    "InteractionSample",
    "InteractionTrace",
    "InteractionViewport",
    "assert_interaction_traces_match",
    "compare_interaction_traces",
    "interaction_trace_from_dict",
    "interaction_trace_from_json",
    "interaction_trace_json",
]
