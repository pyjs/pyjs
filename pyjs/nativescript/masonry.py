from pyjs import js
from pyjs.javascript import Date

from . import GridLayout, Point, Screen, ScrollView, StackLayout, View
from .simulator import (
    MasonryDragDecision,
    MasonryDragSession,
    MasonryDragSimulator,
    MasonryItemGeometry,
    MasonryLayoutSnapshot,
    MasonryViewport,
    MasonryViewportAnchor,
    NativeRect,
)


@js
def _layout_margin(value: object) -> float:
    if isinstance(value, int):
        return float(value)
    if isinstance(value, float):
        return value
    return 0.0


@js.inline(
    "(() => {{ const nativeView = {view}.android; "
    "if (nativeView && nativeView.setClipChildren) {{ "
    "nativeView.setClipChildren({enabled}); "
    "nativeView.setClipToPadding({enabled}); }} }})()"
)
def set_android_descendant_clipping(view: View, enabled: bool) -> None: ...


@js
def masonry_column_count(width: float, minimum_column_width: float = 190) -> int:
    if width < minimum_column_width * 2:
        return 1
    if width < minimum_column_width * 3:
        return 2
    if width < minimum_column_width * 4:
        return 3
    return 4


@js
class MasonryLayout(ScrollView):
    """Natural-height columns composed from NativeScript core views.

    This layout deliberately does not virtualize its children. It is useful for
    modest collections and as a behavior reference for a future native recycler.
    """

    def __init__(self, minimum_column_width: float = 190):
        super().__init__()
        self.minimum_column_width = minimum_column_width
        self.column_count = masonry_column_count(
            Screen.mainScreen.widthDIPs,
            minimum_column_width,
        )
        self.item_views: list[View] = []
        self.estimated_heights: list[float] = []
        self.item_groups: list[str] = []
        self.preview_locations: list[Point] = []
        self.drag_simulator: MasonryDragSimulator | None = None
        self.drag_session: MasonryDragSession | None = None
        self.drag_decision: MasonryDragDecision | None = None
        self.drag_clipping_disabled = False
        self.drag_updated_at = 0
        self.grid = GridLayout()
        self.columns: list[StackLayout] = []
        self.content = self.grid
        self.rebuild_columns()

    def rebuild_columns(self):
        self.grid.removeChildren()
        self.columns = []
        if self.column_count == 1:
            self.grid.columns = "*"
        elif self.column_count == 2:
            self.grid.columns = "*,*"
        elif self.column_count == 3:
            self.grid.columns = "*,*,*"
        else:
            self.grid.columns = "*,*,*,*"
        for index in range(self.column_count):
            column = StackLayout()
            column.column = index
            self.columns.append(column)
            self.grid.addChild(column)

    def set_items(
        self,
        views: list[View],
        estimated_heights: list[float],
        groups: list[str] | None = None,
        assigned_columns: list[int] | None = None,
    ):
        # Removing a column from the grid does not detach the views it owns.
        # Detach them explicitly so reordered items can reuse the same views.
        for column in self.columns:
            column.removeChildren()
        self.item_views = views
        self.estimated_heights = estimated_heights
        self.item_groups = []
        for index in range(len(views)):
            group = "default"
            if groups is not None and index < len(groups):
                group = groups[index]
            self.item_groups.append(group)
        self.rebuild_columns()
        column_heights: list[float] = []
        for _index in range(self.column_count):
            column_heights.append(0.0)
        for index in range(len(views)):
            target_column = 0
            assigned = -1
            if assigned_columns is not None and index < len(assigned_columns):
                assigned = assigned_columns[index]
            if assigned >= 0 and assigned < self.column_count:
                target_column = assigned
            else:
                for column_index in range(1, self.column_count):
                    if column_heights[column_index] < column_heights[target_column]:
                        target_column = column_index
            self.columns[target_column].addChild(views[index])
            height = 1.0
            if index < len(estimated_heights):
                height = estimated_heights[index]
            column_heights[target_column] += height

    def measured_items(self) -> list[MasonryItemGeometry]:
        items: list[MasonryItemGeometry] = []
        for index in range(len(self.item_views)):
            view = self.item_views[index]
            size = self.item_views[index].getActualSize()
            placement_height = size.height
            if index < len(self.estimated_heights):
                placement_height = self.estimated_heights[index]
            group = "default"
            if index < len(self.item_groups):
                group = self.item_groups[index]
            items.append(
                MasonryItemGeometry(
                    view.id,
                    size.width,
                    size.height,
                    placement_height,
                    group,
                    _layout_margin(view.marginTop),
                    _layout_margin(view.marginRight),
                    _layout_margin(view.marginBottom),
                    _layout_margin(view.marginLeft),
                )
            )
        return items

    def measured_layout(self) -> MasonryLayoutSnapshot:
        item_ids: list[str] = []
        rects: list[NativeRect] = []
        columns: list[int] = []
        content_height = 0.0
        for index in range(len(self.item_views)):
            view = self.item_views[index]
            location = view.getLocationRelativeTo(self.grid)
            size = view.getActualSize()
            item_ids.append(view.id)
            rects.append(NativeRect(location.x, location.y, size.width, size.height))
            column = 0
            nearest = -1.0
            for column_index in range(len(self.columns)):
                column_location = self.columns[column_index].getLocationRelativeTo(
                    self.grid
                )
                distance = abs(column_location.x - location.x)
                if nearest < 0 or distance < nearest:
                    column = column_index
                    nearest = distance
            columns.append(column)
            if location.y + size.height > content_height:
                content_height = location.y + size.height
        return MasonryLayoutSnapshot(item_ids, rects, columns, content_height)

    def simulator(self) -> MasonryDragSimulator:
        column_lefts: list[float] = []
        content_top = 0.0
        for column in self.columns:
            location = column.getLocationRelativeTo(self.grid)
            column_lefts.append(location.x)
            if location.y > content_top:
                content_top = location.y
        return MasonryDragSimulator(column_lefts, content_top)

    def viewport(self) -> MasonryViewport:
        location = self.getLocationOnScreen()
        size = self.getActualSize()
        return MasonryViewport(
            location.x,
            location.y,
            size.width,
            size.height,
            self.verticalOffset,
            self.scrollableHeight,
        )

    def start_simulated_drag(
        self,
        source_index: int,
        pointer_screen_x: float,
        pointer_screen_y: float,
    ):
        simulator = self.simulator()
        original_layout = self.measured_layout()
        session = simulator.begin_drag(
            self.measured_items(),
            source_index,
            self.viewport(),
            pointer_screen_x,
            pointer_screen_y,
            original_layout,
        )
        if session is None:
            return
        self.drag_simulator = simulator
        self.drag_session = session
        self.drag_decision = None
        self.drag_updated_at = Date.now()
        self.set_drag_clipping(False)

    def set_drag_clipping(self, enabled: bool):
        set_android_descendant_clipping(self.grid, enabled)
        for column in self.columns:
            set_android_descendant_clipping(column, enabled)
        self.drag_clipping_disabled = not enabled

    def update_simulated_drag(
        self,
        pointer_screen_x: float,
        pointer_screen_y: float,
        elapsed_ms: float = -1,
    ) -> MasonryDragDecision | None:
        if self.drag_simulator is None or self.drag_session is None:
            return None
        if elapsed_ms < 0:
            now = Date.now()
            elapsed_ms = now - self.drag_updated_at
            if elapsed_ms < 1:
                elapsed_ms = 1
            elif elapsed_ms > 50:
                elapsed_ms = 50
            self.drag_updated_at = now
        decision = self.drag_simulator.advance_drag(
            self.drag_session,
            self.viewport(),
            pointer_screen_x,
            pointer_screen_y,
            elapsed_ms,
        )
        self.drag_decision = decision
        if decision.scroll_offset != self.verticalOffset:
            self.scroll_to_offset(decision.scroll_offset)
        for index in range(len(self.item_views)):
            self.item_views[index].translateX = decision.translate_x[index]
            self.item_views[index].translateY = decision.translate_y[index]
        return decision

    def simulated_destination(self) -> int:
        if self.drag_decision is None:
            return -1
        return self.drag_decision.destination_index

    def simulated_item_ids(self) -> list[str]:
        result: list[str] = []
        if self.drag_decision is not None:
            for item_id in self.drag_decision.preview_layout.item_ids:
                result.append(item_id)
            return result
        for view in self.item_views:
            result.append(view.id)
        return result

    def simulated_columns(self) -> list[int]:
        result: list[int] = []
        if self.drag_decision is not None:
            for column in self.drag_decision.preview_layout.columns:
                result.append(column)
            return result
        layout = self.measured_layout()
        for column in layout.columns:
            result.append(column)
        return result

    def capture_viewport_anchor(self, excluded_id: str = "") -> MasonryViewportAnchor:
        simulator = self.simulator()
        layout = self.measured_layout()
        if isinstance(self.drag_session, MasonryDragSession):
            if isinstance(self.drag_simulator, MasonryDragSimulator):
                simulator = self.drag_simulator
            layout = self.drag_session.original_layout
        return simulator.capture_anchor(
            layout,
            self.viewport(),
            excluded_id,
        )

    def restore_viewport_anchor(self, anchor: MasonryViewportAnchor):
        active_viewport = self.viewport()
        offset = self.simulator().restore_anchor(
            self.measured_layout(),
            active_viewport,
            anchor,
        )
        self.scroll_to_offset(offset)

    def scroll_to_offset(self, offset: float):
        enabled = self.isScrollEnabled
        if not enabled:
            self.isScrollEnabled = True
        self.scrollToVerticalOffset(offset, False)
        if not enabled:
            self.isScrollEnabled = False

    def clear_simulated_drag(self, excluded_index: int = -1):
        for index in range(len(self.item_views)):
            if index != excluded_index:
                self.item_views[index].translateX = 0.0
                self.item_views[index].translateY = 0.0
        self.drag_simulator = None
        self.drag_session = None
        self.drag_decision = None
        self.drag_updated_at = 0
        if self.drag_clipping_disabled:
            self.set_drag_clipping(True)

    def index_at(self, x: float, y: float, excluded_index: int = -1) -> int:
        nearest_index = -1
        nearest_distance = -1.0
        for index in range(len(self.item_views)):
            if index == excluded_index:
                continue
            view = self.item_views[index]
            location = view.getLocationRelativeTo(self.grid)
            if index < len(self.preview_locations):
                location = self.preview_locations[index]
            size = view.getActualSize()
            if (
                x >= location.x
                and x <= location.x + size.width
                and y >= location.y
                and y <= location.y + size.height
            ):
                return index
            center_x = location.x + size.width / 2
            center_y = location.y + size.height / 2
            delta_x = center_x - x
            delta_y = center_y - y
            distance = delta_x * delta_x + delta_y * delta_y
            if nearest_distance < 0 or distance < nearest_distance:
                nearest_index = index
                nearest_distance = distance
        return nearest_index

    def begin_preview(self):
        self.preview_locations = []
        for view in self.item_views:
            self.preview_locations.append(view.getLocationRelativeTo(self.grid))

    def preview_move(self, source_index: int, target_index: int):
        if len(self.preview_locations) != len(self.item_views):
            self.begin_preview()
        for index in range(len(self.item_views)):
            if index == source_index:
                continue
            target_x = self.preview_locations[index].x
            target_y = self.preview_locations[index].y
            if source_index < target_index:
                if index > source_index and index <= target_index:
                    target_x = self.preview_locations[index - 1].x
                    target_y = self.preview_locations[index - 1].y
            elif source_index > target_index:
                if index >= target_index and index < source_index:
                    target_x = self.preview_locations[index + 1].x
                    target_y = self.preview_locations[index + 1].y
            self.item_views[index].translateX = target_x - self.preview_locations[index].x
            self.item_views[index].translateY = target_y - self.preview_locations[index].y

    def clear_preview(self, excluded_index: int = -1):
        for index in range(len(self.item_views)):
            if index != excluded_index:
                self.item_views[index].translateX = 0.0
                self.item_views[index].translateY = 0.0
        self.preview_locations = []


__all__ = [
    "MasonryLayout",
    "masonry_column_count",
    "set_android_descendant_clipping",
]
