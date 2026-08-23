import json
from dataclasses import asdict, dataclass

from pyjs import js
from pyjs.nativescript.simulator import (
    MasonryDragDecision,
    MasonryDragSession,
    MasonryDragSimulator,
    MasonryItemGeometry,
    MasonryLayoutSnapshot,
    MasonryViewport,
    MasonryViewportAnchor,
    NativeRect,
)
from pyjs.ui.interaction import (
    InteractionMeasurement,
    InteractionProjection,
    InteractionSample,
    InteractionViewport,
)

from .gesture import GestureScript
from .trace import (
    InteractionCommit,
    InteractionComparison,
    InteractionDecision,
    InteractionFrame,
    InteractionTrace,
    compare_interaction_traces,
    interaction_trace_from_dict,
)


@js
@dataclass(frozen=True, repr=False)
class MasonryTraceItem:
    item_id: str
    width: float
    height: float
    placement_height: float
    group: str
    margin_top: float
    margin_right: float
    margin_bottom: float
    margin_left: float
    x: float
    y: float
    column: int


@js
@dataclass(frozen=True, repr=False)
class MasonryTraceSetup:
    items: list[MasonryTraceItem]
    column_lefts: list[float]
    content_top: float
    vertical_gap: float
    edge_size: float
    edge_step: float
    edge_interval_ms: float
    hysteresis: float
    group_gap: float
    source_index: int
    pointer_x: float
    pointer_y: float
    start_elapsed_ms: float
    viewport: InteractionViewport
    content_height: float
    clip_columns: bool


@js
@dataclass(frozen=True, repr=False)
class MasonryTrace:
    setup: MasonryTraceSetup
    interaction: InteractionTrace


@js
@dataclass(frozen=True, repr=False)
class MasonryReplayResult:
    actual: MasonryTrace
    comparison: InteractionComparison


@js
def _interaction_viewport(viewport: MasonryViewport) -> InteractionViewport:
    return InteractionViewport(
        viewport.screen_x,
        viewport.screen_y,
        viewport.width,
        viewport.height,
        0,
        viewport.scroll_offset,
        viewport.width,
        viewport.height + viewport.maximum_scroll,
    )


@js
def _masonry_viewport(viewport: InteractionViewport) -> MasonryViewport:
    maximum_scroll = viewport.content_height - viewport.height
    if maximum_scroll < 0:
        maximum_scroll = 0.0
    return MasonryViewport(
        viewport.x,
        viewport.y,
        viewport.width,
        viewport.height,
        viewport.scroll_y,
        maximum_scroll,
    )


@js
class MasonryTraceRecorder:
    """Opt-in recorder for deterministic, redacted masonry drag traces."""

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
        self.groups: dict[str, str] = {}
        self.setup: MasonryTraceSetup | None = None
        self.source_id = ""
        self.frames: list[InteractionFrame] = []
        self.commit: InteractionCommit | None = None
        self.samples: list[InteractionSample] = []
        self.elapsed_ms = 0.0
        self.last_x = 0.0
        self.last_y = 0.0

    def item_id(self, value: str) -> str:
        if not self.redact_ids:
            return value
        if value not in self.ids:
            self.ids[value] = "item-" + str(len(self.ids))
        return self.ids[value]

    def group_id(self, value: str) -> str:
        if not self.redact_ids:
            return value
        if value not in self.groups:
            self.groups[value] = "group-" + str(len(self.groups))
        return self.groups[value]

    def begin(
        self,
        simulator: MasonryDragSimulator,
        items: list[MasonryItemGeometry],
        source_index: int,
        viewport: MasonryViewport,
        pointer_x: float,
        pointer_y: float,
        original_layout: MasonryLayoutSnapshot | None = None,
        *,
        start_elapsed_ms: float = 0,
        clip_columns: bool = True,
        samples: list[InteractionSample] | None = None,
    ) -> MasonryDragSession | None:
        layout = simulator.layout(items)
        if original_layout is not None:
            layout = original_layout
        session = simulator.begin_drag(
            items,
            source_index,
            viewport,
            pointer_x,
            pointer_y,
            layout,
        )
        self.started(
            simulator,
            items,
            source_index,
            viewport,
            pointer_x,
            pointer_y,
            session,
            layout,
            start_elapsed_ms=start_elapsed_ms,
            clip_columns=clip_columns,
            samples=samples,
        )
        return session

    def started(
        self,
        simulator: MasonryDragSimulator,
        items: list[MasonryItemGeometry],
        source_index: int,
        viewport: MasonryViewport,
        pointer_x: float,
        pointer_y: float,
        session: MasonryDragSession | None,
        original_layout: MasonryLayoutSnapshot,
        *,
        start_elapsed_ms: float = 0,
        clip_columns: bool = True,
        samples: list[InteractionSample] | None = None,
    ) -> None:
        self.ids = {}
        self.groups = {}
        self.frames = []
        self.commit = None
        self.samples = []
        if samples is not None:
            for sample in samples:
                self.samples.append(sample)
            if len(samples) > 0:
                start_elapsed_ms = samples[-1].elapsed_ms
        self.elapsed_ms = start_elapsed_ms
        self.last_x = pointer_x
        self.last_y = pointer_y
        layout = original_layout
        captured_items: list[MasonryTraceItem] = []
        for item in items:
            layout_index = layout.index_of(item.id)
            x = 0.0
            y = 0.0
            column = -1
            if layout_index >= 0:
                rect = layout.rects[layout_index]
                x = rect.x
                y = rect.y
                column = layout.columns[layout_index]
            captured_items.append(
                MasonryTraceItem(
                    self.item_id(item.id),
                    item.width,
                    item.height,
                    item.placement_height,
                    self.group_id(item.group),
                    item.margin_top,
                    item.margin_right,
                    item.margin_bottom,
                    item.margin_left,
                    x,
                    y,
                    column,
                )
            )
        self.setup = MasonryTraceSetup(
            captured_items,
            [left for left in simulator.column_lefts],
            simulator.content_top,
            simulator.vertical_gap,
            simulator.edge_size,
            simulator.edge_step,
            simulator.edge_interval_ms,
            simulator.hysteresis,
            simulator.group_gap,
            source_index,
            pointer_x,
            pointer_y,
            start_elapsed_ms,
            _interaction_viewport(viewport),
            layout.content_height,
            clip_columns,
        )
        if isinstance(session, MasonryDragSession):
            self.source_id = self.item_id(session.source_id)
        else:
            self.source_id = ""

    def updated(
        self,
        simulator: MasonryDragSimulator,
        session: MasonryDragSession,
        viewport: MasonryViewport,
        pointer_x: float,
        pointer_y: float,
        elapsed_ms: float,
        decision: MasonryDragDecision,
        *,
        sample: InteractionSample | None = None,
        measurements: list[InteractionMeasurement] | None = None,
        projections: list[InteractionProjection] | None = None,
        extensions: dict[str, str] | None = None,
    ) -> None:
        if elapsed_ms < 0:
            elapsed_ms = 0.0
        if sample is None:
            self.elapsed_ms += elapsed_ms
            sample = InteractionSample(
                "move",
                pointer_x,
                pointer_y,
                1,
                self.elapsed_ms,
                pointer_x - self.last_x,
                pointer_y - self.last_y,
            )
        else:
            self.elapsed_ms = sample.elapsed_ms
        self.samples.append(sample)
        self.last_x = pointer_x
        self.last_y = pointer_y

        captured_measurements: list[InteractionMeasurement] = []
        if measurements is None:
            for item in session.items:
                rect = session.original_layout.rect_for(item.id)
                if isinstance(rect, NativeRect):
                    captured_measurements.append(
                        InteractionMeasurement(
                            self.item_id(item.id),
                            rect.x,
                            rect.y,
                            rect.width,
                            rect.height,
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
        if projections is None:
            clip_columns = True
            setup = self.setup
            if setup is not None:
                clip_columns = setup.clip_columns
            projection = simulator.project_preview(
                session,
                decision,
                viewport,
                clip_columns,
            )
            for index in range(len(session.items)):
                item = session.items[index]
                projected = projection.item_for(item.id)
                if projected is not None:
                    captured_projections.append(
                        InteractionProjection(
                            self.item_id(item.id),
                            decision.translate_x[index],
                            decision.translate_y[index],
                            projected.is_visible,
                            projected.visible_rect.x,
                            projected.visible_rect.y,
                            projected.visible_rect.width,
                            projected.visible_rect.height,
                        )
                    )
        else:
            for projection_item in projections:
                captured_projections.append(
                    InteractionProjection(
                        self.item_id(projection_item.item_id),
                        projection_item.translate_x,
                        projection_item.translate_y,
                        projection_item.visible,
                        projection_item.clip_x,
                        projection_item.clip_y,
                        projection_item.clip_width,
                        projection_item.clip_height,
                    )
                )

        order: list[str] = []
        for item_id in decision.preview_layout.item_ids:
            order.append(self.item_id(item_id))
        columns: list[int] = []
        for column in decision.preview_layout.columns:
            columns.append(column)
        source_group = ""
        if session.source_index >= 0 and session.source_index < len(session.items):
            source_group = self.group_id(session.items[session.source_index].group)
        frame_extensions: dict[str, str] = {}
        if extensions is not None:
            frame_extensions = extensions
        self.frames.append(
            InteractionFrame(
                sample,
                captured_measurements,
                InteractionDecision(
                    slot=(
                        "column:"
                        + str(decision.destination_column)
                        + ":lane:"
                        + str(decision.destination_lane_index)
                    ),
                    destination_index=decision.destination_index,
                    destination_column=decision.destination_column,
                    destination_lane=decision.destination_lane_index,
                    group=source_group,
                    scroll_offset=decision.scroll_offset,
                    order=order,
                    columns=columns,
                ),
                _interaction_viewport(viewport),
                captured_projections,
                frame_extensions,
            )
        )

    def committed(
        self,
        decision: MasonryDragDecision,
        anchor: MasonryViewportAnchor | None = None,
        sample: InteractionSample | None = None,
        extensions: dict[str, str] | None = None,
    ) -> None:
        if sample is not None:
            self.samples.append(sample)
        order: list[str] = []
        for item_id in decision.preview_layout.item_ids:
            order.append(self.item_id(item_id))
        columns: list[int] = []
        for column in decision.preview_layout.columns:
            columns.append(column)
        anchor_id = ""
        anchor_offset = 0.0
        if anchor is not None:
            if anchor.item_id:
                anchor_id = self.item_id(anchor.item_id)
            anchor_offset = anchor.screen_y
        commit_extensions: dict[str, str] = {}
        if extensions is not None:
            commit_extensions = extensions
        self.commit = InteractionCommit(
            order,
            scroll_anchor_id=anchor_id,
            scroll_anchor_offset=anchor_offset,
            extensions=commit_extensions,
            columns=columns,
        )

    def cancelled(self, sample: InteractionSample | None = None) -> None:
        if sample is not None:
            self.samples.append(sample)

    def trace(self) -> MasonryTrace:
        setup = self.setup
        if setup is None:
            raise ValueError("Masonry trace recording has not begun.")
        return MasonryTrace(
            setup,
            InteractionTrace(
                "masonry-reorder",
                self.source_id,
                self.frames,
                self.commit,
                self.extensions,
                inputs=self.samples,
            ),
        )


@js
class MasonryGestureTarget:
    """Structural interface implemented by the NativeScript masonry layout."""

    __pyjs_structural__ = True

    def start_simulated_drag(
        self,
        source_index: int,
        pointer_x: float,
        pointer_y: float,
        samples: list[InteractionSample] | None = None,
    ) -> None: ...

    def update_simulated_drag(
        self,
        pointer_x: float,
        pointer_y: float,
        elapsed_ms: float = -1,
        sample: InteractionSample | None = None,
    ) -> MasonryDragDecision | None: ...

    def commit_simulated_drag(
        self,
        anchor: MasonryViewportAnchor | None = None,
        sample: InteractionSample | None = None,
    ) -> MasonryDragDecision | None: ...

    def clear_simulated_drag(
        self,
        excluded_index: int = -1,
        sample: InteractionSample | None = None,
    ) -> None: ...


@js
def play_masonry_gesture(
    target: MasonryGestureTarget,
    source_index: int,
    script: GestureScript,
) -> MasonryDragDecision | None:
    active = False
    previous_elapsed = 0.0
    decision: MasonryDragDecision | None = None
    for sample in script.samples:
        elapsed_ms = sample.elapsed_ms - previous_elapsed
        if elapsed_ms < 0:
            elapsed_ms = 0.0
        if sample.phase == "down":
            target.start_simulated_drag(
                source_index,
                sample.x,
                sample.y,
                [sample],
            )
            active = True
        elif active and (sample.phase == "hold" or sample.phase == "move"):
            decision = target.update_simulated_drag(
                sample.x,
                sample.y,
                elapsed_ms,
                sample,
            )
        elif active and sample.phase == "up":
            decision = target.commit_simulated_drag(sample=sample)
            active = False
        elif sample.phase == "cancel":
            target.clear_simulated_drag(sample=sample)
            decision = None
            active = False
        previous_elapsed = sample.elapsed_ms
    return decision


@js
def _items_and_layout(
    setup: MasonryTraceSetup,
) -> tuple[list[MasonryItemGeometry], MasonryLayoutSnapshot]:
    items: list[MasonryItemGeometry] = []
    item_ids: list[str] = []
    rects: list[NativeRect] = []
    columns: list[int] = []
    for item in setup.items:
        items.append(
            MasonryItemGeometry(
                item.item_id,
                item.width,
                item.height,
                item.placement_height,
                item.group,
                item.margin_top,
                item.margin_right,
                item.margin_bottom,
                item.margin_left,
            )
        )
        item_ids.append(item.item_id)
        rects.append(NativeRect(item.x, item.y, item.width, item.height))
        columns.append(item.column)
    return (
        items,
        MasonryLayoutSnapshot(item_ids, rects, columns, setup.content_height),
    )


@js
def replay_masonry_trace(
    expected: MasonryTrace,
    tolerance: float = 0.001,
) -> MasonryReplayResult:
    setup = expected.setup
    simulator = MasonryDragSimulator(
        setup.column_lefts,
        setup.content_top,
        setup.vertical_gap,
        setup.edge_size,
        setup.edge_step,
        setup.edge_interval_ms,
        setup.hysteresis,
        setup.group_gap,
    )
    items, original_layout = _items_and_layout(setup)
    viewport = _masonry_viewport(setup.viewport)
    recorder = MasonryTraceRecorder(False, expected.interaction.extensions)
    session = recorder.begin(
        simulator,
        items,
        setup.source_index,
        viewport,
        setup.pointer_x,
        setup.pointer_y,
        original_layout,
        start_elapsed_ms=setup.start_elapsed_ms,
        clip_columns=setup.clip_columns,
    )
    if not isinstance(session, MasonryDragSession):
        raise ValueError("Masonry trace contains an invalid source index.")
    decision: MasonryDragDecision | None = None
    previous_elapsed = setup.start_elapsed_ms
    for frame in expected.interaction.frames:
        if frame.viewport is not None:
            viewport = _masonry_viewport(frame.viewport)
        elapsed_ms = frame.sample.elapsed_ms - previous_elapsed
        if elapsed_ms < 0:
            elapsed_ms = 0.0
        decision = simulator.advance_drag(
            session,
            viewport,
            frame.sample.x,
            frame.sample.y,
            elapsed_ms,
        )
        recorder.updated(
            simulator,
            session,
            viewport,
            frame.sample.x,
            frame.sample.y,
            elapsed_ms,
            decision,
            sample=frame.sample,
            measurements=frame.measurements,
            extensions=frame.extensions,
        )
        previous_elapsed = frame.sample.elapsed_ms
    expected_commit = expected.interaction.commit
    if expected_commit is not None:
        if decision is None:
            raise ValueError("A masonry trace commit requires at least one frame.")
        anchor: MasonryViewportAnchor | None = None
        if expected_commit.scroll_anchor_id:
            anchor = MasonryViewportAnchor(
                expected_commit.scroll_anchor_id,
                expected_commit.scroll_anchor_offset,
            )
        recorder.committed(
            decision,
            anchor,
            extensions=expected_commit.extensions,
        )
    recorder.samples = []
    for sample in expected.interaction.inputs:
        recorder.samples.append(sample)
    actual = recorder.trace()
    return MasonryReplayResult(
        actual,
        compare_interaction_traces(
            expected.interaction,
            actual.interaction,
            tolerance,
        ),
    )


def masonry_trace_json(trace: MasonryTrace, *, indent: int = 2) -> str:
    return json.dumps(asdict(trace), indent=indent, sort_keys=True)


def masonry_trace_from_json(source: str) -> MasonryTrace:
    value = json.loads(source)
    setup_value = value["setup"]
    setup = MasonryTraceSetup(
        [MasonryTraceItem(**item) for item in setup_value["items"]],
        setup_value["column_lefts"],
        setup_value["content_top"],
        setup_value["vertical_gap"],
        setup_value["edge_size"],
        setup_value["edge_step"],
        setup_value["edge_interval_ms"],
        setup_value["hysteresis"],
        setup_value.get("group_gap", 0),
        setup_value["source_index"],
        setup_value["pointer_x"],
        setup_value["pointer_y"],
        setup_value["start_elapsed_ms"],
        InteractionViewport(**setup_value["viewport"]),
        setup_value["content_height"],
        setup_value["clip_columns"],
    )
    return MasonryTrace(
        setup,
        interaction_trace_from_dict(value["interaction"]),
    )


__all__ = [
    "MasonryGestureTarget",
    "MasonryReplayResult",
    "MasonryTrace",
    "MasonryTraceItem",
    "MasonryTraceRecorder",
    "MasonryTraceSetup",
    "masonry_trace_from_json",
    "masonry_trace_json",
    "play_masonry_gesture",
    "replay_masonry_trace",
]
