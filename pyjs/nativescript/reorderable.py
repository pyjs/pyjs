from pyjs import js
from pyjs.ui.gesture import GestureScript
from pyjs.ui.interaction import (
    InteractionMeasurement,
    InteractionProjection,
    InteractionSample,
    InteractionViewport,
)
from pyjs.ui.reorder_trace import ReorderTraceRecorder
from pyjs.ui.reorderable import (
    HierarchicalReorder,
    ReorderDecision,
    ReorderItem,
    ReorderRow,
    ReorderSession,
)

from . import Point, StackLayout, View


@js
def edge_scroll_offset(
    pointer: float,
    viewport_start: float,
    viewport_size: float,
    current_offset: float,
    maximum_offset: float,
    edge_size: float = 64,
    step: float = 24,
) -> float:
    target = current_offset
    if pointer < viewport_start + edge_size:
        target -= step
    elif pointer > viewport_start + viewport_size - edge_size:
        target += step
    if target < 0:
        return 0.0
    if target > maximum_offset:
        return maximum_offset
    return target


@js
class ReorderableStackLayout(StackLayout):
    """A natural-height stack with measured insertion hit testing.

    The layout deliberately does not virtualize its children. Applications own
    the gesture and data mutation, while this class provides stable child
    management and geometry-based insertion slots for mixed-height rows.
    """

    def __init__(self):
        super().__init__()
        self.item_views: list[View] = []
        self.preview_locations: list[Point] = []
        self.hierarchical_items: list[ReorderItem] = []
        self.hierarchical_session: ReorderSession | None = None
        self.hierarchical_decision: ReorderDecision | None = None
        self.hierarchical_hidden_indices: list[int] = []
        self.hierarchical_hidden_visibility: list[str] = []
        self.reorder_recorder: ReorderTraceRecorder | None = None

    def record_interactions(self, redact_ids: bool = True) -> ReorderTraceRecorder:
        recorder = ReorderTraceRecorder(redact_ids, {"platform": "nativescript"})
        self.reorder_recorder = recorder
        return recorder

    def set_items(self, views: list[View]):
        self.item_views = views
        self.removeChildren()
        for view in views:
            self.addChild(view)

    def insertion_index_at(self, y: float, excluded_index: int = -1) -> int:
        insertion_index = 0
        for index in range(len(self.item_views)):
            if index == excluded_index:
                continue
            view = self.item_views[index]
            location = view.getLocationRelativeTo(self)
            if index < len(self.preview_locations):
                location = self.preview_locations[index]
            size = view.getActualSize()
            if y <= location.y + size.height / 2:
                return insertion_index
            insertion_index += 1
        return insertion_index

    def begin_preview(self):
        self.preview_locations = []
        for view in self.item_views:
            self.preview_locations.append(view.getLocationRelativeTo(self))

    def begin_hierarchical_preview(
        self,
        items: list[ReorderItem],
        source_index: int,
        max_depth: int = 5,
        indent_step: float = 36,
    ) -> ReorderSession | None:
        engine = HierarchicalReorder(max_depth, indent_step)
        recorder = self.reorder_recorder
        if isinstance(recorder, ReorderTraceRecorder):
            session = recorder.begin(engine, items, source_index)
        else:
            session = engine.begin(items, source_index)
        if not isinstance(session, ReorderSession):
            return None
        self.hierarchical_items = items
        self.hierarchical_session = session
        self.hierarchical_hidden_indices = []
        self.hierarchical_hidden_visibility = []
        for hidden_id in session.hidden_item_ids:
            for index in range(len(items)):
                if items[index].id == hidden_id and index < len(self.item_views):
                    self.hierarchical_hidden_indices.append(index)
                    self.hierarchical_hidden_visibility.append(
                        self.item_views[index].visibility
                    )
                    self.item_views[index].visibility = "collapse"
        self.begin_preview()
        self.hierarchical_decision = session.preview(
            source_index,
            session.source_depth,
        )
        return session

    def update_hierarchical_preview(
        self,
        pointer: float,
        horizontal_delta: float,
        sample: InteractionSample | None = None,
    ) -> ReorderDecision | None:
        session = self.hierarchical_session
        if not isinstance(session, ReorderSession):
            return None
        rows: list[ReorderRow] = []
        visible_indices: list[int] = []
        source_visible_index = -1
        for index in range(len(self.hierarchical_items)):
            item = self.hierarchical_items[index]
            if item.id in session.hidden_item_ids:
                continue
            if item.id == session.source.id:
                source_visible_index = len(visible_indices)
                visible_indices.append(index)
                continue
            view = self.item_views[index]
            location = view.getLocationRelativeTo(self)
            if index < len(self.preview_locations):
                location = self.preview_locations[index]
            size = view.getActualSize()
            rows.append(ReorderRow(item.id, location.y, size.height))
            visible_indices.append(index)
        decision = session.update(rows, pointer, horizontal_delta)
        source_view = self.item_views[session.source_index]
        dragged_height = source_view.getActualSize().height
        for visible_index in range(len(visible_indices)):
            item_index = visible_indices[visible_index]
            if visible_index == source_visible_index:
                continue
            offset = 0.0
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
            self.item_views[item_index].translateY = offset
        self.hierarchical_decision = decision
        recorder = self.reorder_recorder
        if isinstance(recorder, ReorderTraceRecorder):
            measurements: list[InteractionMeasurement] = []
            projections: list[InteractionProjection] = []
            for index in range(len(self.hierarchical_items)):
                item = self.hierarchical_items[index]
                view = self.item_views[index]
                location = view.getLocationRelativeTo(self)
                if index < len(self.preview_locations):
                    location = self.preview_locations[index]
                item_size = view.getActualSize()
                measurements.append(
                    InteractionMeasurement(
                        item.id,
                        location.x,
                        location.y,
                        item_size.width,
                        item_size.height,
                    )
                )
                projections.append(
                    InteractionProjection(
                        item.id,
                        view.translateX,
                        view.translateY,
                        view.visibility == "visible",
                    )
                )
            size = self.getActualSize()
            recorder.record_update(
                rows,
                pointer,
                horizontal_delta,
                decision,
                sample=sample,
                measurements=measurements,
                viewport=InteractionViewport(width=size.width, height=size.height),
                projections=projections,
            )
        return decision

    def commit_hierarchical_preview(self) -> ReorderDecision | None:
        decision = self.hierarchical_decision
        if not isinstance(decision, ReorderDecision):
            return None
        recorder = self.reorder_recorder
        if isinstance(recorder, ReorderTraceRecorder):
            recorder.record_commit(decision)
        return decision

    def play_hierarchical_gesture(
        self,
        script: GestureScript,
    ) -> ReorderDecision | None:
        start_x = 0.0
        active = False
        decision: ReorderDecision | None = None
        for sample in script.samples:
            if sample.phase == "down":
                start_x = sample.x
                active = True
            elif active and (sample.phase == "hold" or sample.phase == "move"):
                decision = self.update_hierarchical_preview(
                    sample.y,
                    sample.x - start_x,
                    sample,
                )
            elif sample.phase == "up":
                decision = self.commit_hierarchical_preview()
                active = False
            elif sample.phase == "cancel":
                self.clear_hierarchical_preview()
                decision = None
                active = False
        return decision

    def clear_hierarchical_preview(self, excluded_index: int = -1):
        self.clear_preview(excluded_index)
        for hidden_index in range(len(self.hierarchical_hidden_indices)):
            item_index = self.hierarchical_hidden_indices[hidden_index]
            self.item_views[item_index].visibility = (
                self.hierarchical_hidden_visibility[hidden_index]
            )
        self.hierarchical_items = []
        self.hierarchical_session = None
        self.hierarchical_decision = None
        self.hierarchical_hidden_indices = []
        self.hierarchical_hidden_visibility = []

    def preview_insertion(
        self,
        source_index: int,
        insertion_index: int,
        dragged_height: float,
    ):
        if len(self.preview_locations) != len(self.item_views):
            self.begin_preview()
        for index in range(len(self.item_views)):
            if index == source_index:
                continue
            offset = 0.0
            if source_index < insertion_index:
                if index > source_index and index <= insertion_index:
                    offset = -dragged_height
            elif source_index > insertion_index:
                if index >= insertion_index and index < source_index:
                    offset = dragged_height
            self.item_views[index].translateY = offset

    def clear_preview(self, excluded_index: int = -1):
        for index in range(len(self.item_views)):
            if index != excluded_index:
                self.item_views[index].translateY = 0.0
        self.preview_locations = []


__all__ = ["ReorderableStackLayout", "edge_scroll_offset"]
