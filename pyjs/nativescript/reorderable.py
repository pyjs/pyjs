from pyjs import js
from pyjs.ui.interaction import (
    InteractionMeasurement,
    InteractionProjection,
    InteractionSample,
    InteractionViewport,
)
from pyjs.ui.reorderable import (
    HierarchicalReorder,
    ReorderDecision,
    ReorderItem,
    ReorderObserver,
    ReorderRow,
    ReorderSession,
    edge_scroll_offset,
)

from . import Point, StackLayout, View


@js
class ReorderableStackLayout(StackLayout):
    """A natural-height stack with measured insertion hit testing.

    The layout deliberately does not virtualize its children. Applications own
    the gesture and data mutation, while this class provides stable child
    management and geometry-based insertion slots for mixed-height rows.
    """

    def __init__(self, observer: ReorderObserver | None = None):
        super().__init__()
        self.item_views: list[View] = []
        self.preview_locations: list[Point] = []
        self.hierarchical_items: list[ReorderItem] = []
        self.hierarchical_session: ReorderSession | None = None
        self.hierarchical_decision: ReorderDecision | None = None
        self.hierarchical_hidden_indices: list[int] = []
        self.hierarchical_hidden_visibility: list[str] = []
        self.hierarchical_rows: list[ReorderRow] = []
        self.hierarchical_visible_indices: list[int] = []
        self.hierarchical_source_visible_index = -1
        self.hierarchical_shifted_indices = set[int]()
        self.hierarchical_shift_offset = 0.0
        self.hierarchical_dragged_height = 0.0
        self.reorder_observer = observer

    def begin(
        self,
        items: list[ReorderItem],
        source_index: int,
        max_depth: int = 5,
        indent_step: float = 36,
        samples: list[InteractionSample] | None = None,
    ) -> ReorderSession | None:
        return self.begin_hierarchical_preview(
            items,
            source_index,
            max_depth,
            indent_step,
            samples,
        )

    def update(
        self,
        pointer: float,
        horizontal_delta: float,
        sample: InteractionSample | None = None,
        rows: list[ReorderRow] | None = None,
        viewport: InteractionViewport | None = None,
    ) -> ReorderDecision | None:
        return self.update_hierarchical_preview(
            pointer,
            horizontal_delta,
            sample,
            rows,
            viewport,
        )

    def commit(
        self,
        sample: InteractionSample | None = None,
        scroll_anchor_id: str = "",
        scroll_anchor_offset: float = 0,
    ) -> ReorderDecision | None:
        return self.commit_hierarchical_preview(
            sample,
            scroll_anchor_id,
            scroll_anchor_offset,
        )

    def clear(self, sample: InteractionSample | None = None) -> None:
        self.clear_hierarchical_preview(sample=sample)

    def refresh_geometry(self) -> list[ReorderRow]:
        return self.refresh_hierarchical_geometry()

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
        samples: list[InteractionSample] | None = None,
    ) -> ReorderSession | None:
        engine = HierarchicalReorder(max_depth, indent_step)
        session = engine.begin(items, source_index)
        observer = self.reorder_observer
        if observer is not None:
            observer.started(engine, items, source_index, session, samples)
        if not isinstance(session, ReorderSession):
            return None
        self.hierarchical_items = items
        self.hierarchical_session = session
        self.hierarchical_hidden_indices = []
        self.hierarchical_hidden_visibility = []
        item_indices: dict[str, int] = {}
        for index in range(len(items)):
            item_indices[items[index].id] = index
        for hidden_id in session.hidden_item_ids:
            if hidden_id not in item_indices:
                continue
            hidden_index = item_indices[hidden_id]
            if hidden_index < len(self.item_views):
                self.hierarchical_hidden_indices.append(hidden_index)
                self.hierarchical_hidden_visibility.append(
                    self.item_views[hidden_index].visibility
                )
                self.item_views[hidden_index].visibility = "collapse"
        self.begin_preview()
        self.refresh_hierarchical_geometry()
        self.hierarchical_decision = session.preview(
            source_index,
            session.source_depth,
        )
        return session

    def refresh_hierarchical_geometry(self) -> list[ReorderRow]:
        """Remeasure rows after an application-controlled layout change."""

        self.hierarchical_rows = []
        self.hierarchical_visible_indices = []
        self.hierarchical_source_visible_index = -1
        self.hierarchical_dragged_height = 0.0
        session = self.hierarchical_session
        if not isinstance(session, ReorderSession):
            return self.hierarchical_rows
        self.hierarchical_dragged_height = self.item_views[
            session.source_index
        ].getActualSize().height
        hidden_ids: set[str] = set(session.hidden_item_ids)
        for index in range(len(self.hierarchical_items)):
            item = self.hierarchical_items[index]
            if item.id in hidden_ids:
                continue
            if item.id == session.source.id:
                self.hierarchical_source_visible_index = len(
                    self.hierarchical_visible_indices
                )
                self.hierarchical_visible_indices.append(index)
                continue
            view = self.item_views[index]
            location = view.getLocationRelativeTo(self)
            if index < len(self.preview_locations):
                location = self.preview_locations[index]
            size = view.getActualSize()
            self.hierarchical_rows.append(ReorderRow(item.id, location.y, size.height))
            self.hierarchical_visible_indices.append(index)
        return self.hierarchical_rows

    def update_hierarchical_preview(
        self,
        pointer: float,
        horizontal_delta: float,
        sample: InteractionSample | None = None,
        rows: list[ReorderRow] | None = None,
        viewport: InteractionViewport | None = None,
    ) -> ReorderDecision | None:
        session = self.hierarchical_session
        if not isinstance(session, ReorderSession):
            return None
        if rows is None:
            rows = self.hierarchical_rows
            if len(rows) == 0 and len(session.remaining_items) > 0:
                rows = self.refresh_hierarchical_geometry()
        decision = session.update(rows, pointer, horizontal_delta)
        dragged_height = self.hierarchical_dragged_height
        shifted: set[int] = set()
        source_visible_index = self.hierarchical_source_visible_index
        if source_visible_index < decision.insertion_index:
            for visible_index in range(
                source_visible_index + 1,
                decision.insertion_index + 1,
            ):
                shifted.add(self.hierarchical_visible_indices[visible_index])
        elif source_visible_index > decision.insertion_index:
            for visible_index in range(
                decision.insertion_index,
                source_visible_index,
            ):
                shifted.add(self.hierarchical_visible_indices[visible_index])
        for item_index in self.hierarchical_shifted_indices:
            if item_index not in shifted:
                self.item_views[item_index].translateY = 0.0
        offset = dragged_height
        if source_visible_index < decision.insertion_index:
            offset = -dragged_height
        for item_index in shifted:
            if (
                item_index not in self.hierarchical_shifted_indices
                or offset != self.hierarchical_shift_offset
            ):
                self.item_views[item_index].translateY = offset
        self.hierarchical_shifted_indices = shifted
        self.hierarchical_shift_offset = offset
        self.hierarchical_decision = decision
        observer = self.reorder_observer
        if observer is not None:
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
            captured_viewport = viewport
            if captured_viewport is None:
                size = self.getActualSize()
                captured_viewport = InteractionViewport(
                    width=size.width,
                    height=size.height,
                )
            observer.updated(
                rows,
                pointer,
                horizontal_delta,
                decision,
                sample=sample,
                measurements=measurements,
                viewport=captured_viewport,
                projections=projections,
            )
        return decision

    def commit_hierarchical_preview(
        self,
        sample: InteractionSample | None = None,
        scroll_anchor_id: str = "",
        scroll_anchor_offset: float = 0,
    ) -> ReorderDecision | None:
        decision = self.hierarchical_decision
        if not isinstance(decision, ReorderDecision):
            return None
        observer = self.reorder_observer
        if observer is not None:
            observer.committed(
                decision,
                scroll_anchor_id,
                scroll_anchor_offset,
                sample=sample,
            )
        return decision

    def clear_hierarchical_preview(
        self,
        excluded_index: int = -1,
        sample: InteractionSample | None = None,
    ):
        observer = self.reorder_observer
        if observer is not None:
            observer.cancelled(sample)
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
        self.hierarchical_rows = []
        self.hierarchical_visible_indices = []
        self.hierarchical_source_visible_index = -1
        self.hierarchical_shifted_indices = set[int]()
        self.hierarchical_shift_offset = 0.0
        self.hierarchical_dragged_height = 0.0

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
