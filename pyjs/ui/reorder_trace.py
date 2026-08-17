import json
from dataclasses import asdict, dataclass

from pyjs import js
from pyjs.ui.interaction import (
    InteractionCommit,
    InteractionComparison,
    InteractionDecision,
    InteractionFrame,
    InteractionMeasurement,
    InteractionProjection,
    InteractionSample,
    InteractionTrace,
    InteractionViewport,
    compare_interaction_traces,
    interaction_trace_from_dict,
)
from pyjs.ui.reorderable import (
    HierarchicalReorder,
    ReorderDecision,
    ReorderItem,
    ReorderRow,
    ReorderSession,
)


@js
@dataclass(frozen=True, repr=False)
class ReorderTraceSetup:
    order: list[str]
    depths: list[int]
    source_index: int
    max_depth: int
    indent_step: float


@js
@dataclass(frozen=True, repr=False)
class ReorderTrace:
    setup: ReorderTraceSetup
    interaction: InteractionTrace


@js
@dataclass(frozen=True, repr=False)
class ReorderReplayResult:
    actual: ReorderTrace
    comparison: InteractionComparison


@js
class ReorderTraceRecorder:
    """Opt-in recorder for deterministic, redacted reorder traces."""

    def __init__(
        self,
        redact_ids: bool = True,
        extensions: dict[str, str] | None = None,
    ):
        self.redact_ids = redact_ids
        self.extensions: dict[str, str] = {}
        if extensions is not None:
            self.extensions = extensions
        self.ids: dict[str, str] = {}
        self.setup: ReorderTraceSetup | None = None
        self.source_id = ""
        self.frames: list[InteractionFrame] = []
        self.commit: InteractionCommit | None = None

    def item_id(self, value: str) -> str:
        if not self.redact_ids:
            return value
        if value not in self.ids:
            self.ids[value] = "item-" + str(len(self.ids))
        return self.ids[value]

    def begin(
        self,
        engine: HierarchicalReorder,
        items: list[ReorderItem],
        source_index: int,
    ) -> ReorderSession | None:
        self.ids = {}
        self.frames = []
        self.commit = None
        order: list[str] = []
        depths: list[int] = []
        for item in items:
            order.append(self.item_id(item.id))
            depths.append(item.depth)
        self.setup = ReorderTraceSetup(
            order,
            depths,
            source_index,
            engine.max_depth,
            engine.indent_step,
        )
        session = engine.begin(items, source_index)
        if isinstance(session, ReorderSession):
            self.source_id = self.item_id(session.source.id)
        else:
            self.source_id = ""
        return session

    def record_update(
        self,
        rows: list[ReorderRow],
        pointer: float,
        horizontal_delta: float,
        decision: ReorderDecision,
        *,
        sample: InteractionSample | None = None,
        measurements: list[InteractionMeasurement] | None = None,
        viewport: InteractionViewport | None = None,
        projections: list[InteractionProjection] | None = None,
        extensions: dict[str, str] | None = None,
    ) -> None:
        if sample is None:
            sample = InteractionSample(
                "move",
                horizontal_delta,
                pointer,
                delta_x=horizontal_delta,
            )
        captured_measurements: list[InteractionMeasurement] = []
        if measurements is None:
            for row in rows:
                captured_measurements.append(
                    InteractionMeasurement(
                        self.item_id(row.id),
                        y=row.start,
                        height=row.size,
                    )
                )
        else:
            for measurement in measurements:
                captured_measurements.append(
                    InteractionMeasurement(
                        self.item_id(measurement.item_id),
                        measurement.x,
                        measurement.y,
                        measurement.width,
                        measurement.height,
                        measurement.clipped,
                    )
                )
        captured_projections: list[InteractionProjection] = []
        if projections is not None:
            for projection in projections:
                captured_projections.append(
                    InteractionProjection(
                        self.item_id(projection.item_id),
                        projection.translate_x,
                        projection.translate_y,
                        projection.visible,
                        projection.clip_x,
                        projection.clip_y,
                        projection.clip_width,
                        projection.clip_height,
                    )
                )
        order: list[str] = []
        for item_id in decision.committed_item_ids():
            order.append(self.item_id(item_id))
        frame_extensions: dict[str, str] = {}
        if extensions is not None:
            frame_extensions = extensions
        self.frames.append(
            InteractionFrame(
                sample,
                captured_measurements,
                InteractionDecision(
                    slot="index:" + str(decision.insertion_index),
                    destination_index=decision.insertion_index,
                    destination_depth=decision.target_depth,
                    order=order,
                    depths=decision.committed_depths(),
                ),
                viewport,
                captured_projections,
                frame_extensions,
            )
        )

    def record_commit(
        self,
        decision: ReorderDecision,
        scroll_anchor_id: str = "",
        scroll_anchor_offset: float = 0,
        extensions: dict[str, str] | None = None,
    ) -> None:
        order: list[str] = []
        for item_id in decision.committed_item_ids():
            order.append(self.item_id(item_id))
        anchor_id = ""
        if scroll_anchor_id:
            anchor_id = self.item_id(scroll_anchor_id)
        commit_extensions: dict[str, str] = {}
        if extensions is not None:
            commit_extensions = extensions
        self.commit = InteractionCommit(
            order,
            decision.committed_depths(),
            anchor_id,
            scroll_anchor_offset,
            commit_extensions,
        )

    def trace(self) -> ReorderTrace:
        setup = self.setup
        if setup is None:
            raise ValueError("Reorder trace recording has not begun.")
        return ReorderTrace(
            setup,
            InteractionTrace(
                "hierarchical-reorder",
                self.source_id,
                self.frames,
                self.commit,
                self.extensions,
            ),
        )


@js
def _replay_projections(
    frame: InteractionFrame,
    session: ReorderSession,
    decision: ReorderDecision,
) -> list[InteractionProjection]:
    projections: list[InteractionProjection] = []
    if not frame.projections:
        return projections
    dragged_height = 0.0
    for measurement in frame.measurements:
        if measurement.item_id == session.source.id:
            dragged_height = measurement.height
    source_visible_index = session.source_index
    visible_index = 0
    for expected in frame.projections:
        hidden = expected.item_id in session.hidden_item_ids
        offset = 0.0
        if not hidden and expected.item_id != session.source.id:
            if source_visible_index < decision.insertion_index:
                if (
                    visible_index > source_visible_index
                    and visible_index <= decision.insertion_index
                ):
                    offset = -dragged_height
            elif source_visible_index > decision.insertion_index:
                if (
                    visible_index >= decision.insertion_index
                    and visible_index < source_visible_index
                ):
                    offset = dragged_height
        projections.append(
            InteractionProjection(
                expected.item_id,
                expected.translate_x,
                offset,
                expected.visible and not hidden,
                expected.clip_x,
                expected.clip_y,
                expected.clip_width,
                expected.clip_height,
            )
        )
        if not hidden:
            visible_index += 1
    return projections


@js
def replay_reorder_trace(
    expected: ReorderTrace,
    tolerance: float = 0.001,
) -> ReorderReplayResult:
    setup = expected.setup
    items: list[ReorderItem] = []
    for index in range(len(setup.order)):
        items.append(ReorderItem(setup.order[index], setup.depths[index]))
    recorder = ReorderTraceRecorder(False, expected.interaction.extensions)
    session = recorder.begin(
        HierarchicalReorder(setup.max_depth, setup.indent_step),
        items,
        setup.source_index,
    )
    if not isinstance(session, ReorderSession):
        raise ValueError("Reorder trace contains an invalid source index.")
    decision: ReorderDecision | None = None
    for frame in expected.interaction.frames:
        rows: list[ReorderRow] = []
        for measurement in frame.measurements:
            rows.append(
                ReorderRow(
                    measurement.item_id,
                    measurement.y,
                    measurement.height,
                )
            )
        decision = session.update(
            rows,
            frame.sample.y,
            frame.sample.delta_x,
        )
        projections = _replay_projections(frame, session, decision)
        recorder.record_update(
            rows,
            frame.sample.y,
            frame.sample.delta_x,
            decision,
            sample=frame.sample,
            measurements=frame.measurements,
            viewport=frame.viewport,
            projections=projections,
            extensions=frame.extensions,
        )
    expected_commit = expected.interaction.commit
    if expected_commit is not None:
        if decision is None:
            raise ValueError("A reorder trace commit requires at least one frame.")
        recorder.record_commit(
            decision,
            expected_commit.scroll_anchor_id,
            expected_commit.scroll_anchor_offset,
            expected_commit.extensions,
        )
    actual = recorder.trace()
    return ReorderReplayResult(
        actual,
        compare_interaction_traces(
            expected.interaction,
            actual.interaction,
            tolerance,
        ),
    )


def reorder_trace_json(trace: ReorderTrace, *, indent: int = 2) -> str:
    return json.dumps(asdict(trace), indent=indent, sort_keys=True)


def reorder_trace_from_json(source: str) -> ReorderTrace:
    value = json.loads(source)
    return ReorderTrace(
        ReorderTraceSetup(**value["setup"]),
        interaction_trace_from_dict(value["interaction"]),
    )


__all__ = [
    "ReorderReplayResult",
    "ReorderTrace",
    "ReorderTraceRecorder",
    "ReorderTraceSetup",
    "reorder_trace_from_json",
    "reorder_trace_json",
    "replay_reorder_trace",
]
