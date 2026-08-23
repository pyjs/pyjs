from pyjs import js
from pyjs.javascript import Date
from pyjs.ui.interaction import (
    InteractionMeasurement,
    InteractionProjection,
    InteractionSample,
)

from . import GridLayout, Label, Point, Screen, ScrollView, StackLayout, View
from .simulator import (
    MasonryDragDecision,
    MasonryDragSession,
    MasonryDragSimulator,
    MasonryItemGeometry,
    MasonryLayoutSnapshot,
    MasonryTranslation,
    MasonryViewport,
    MasonryViewportAnchor,
    NativeRect,
)


@js
def _layout_margin(value: int | float | str) -> float:
    if isinstance(value, str):
        return 0.0
    return float(value)


@js.inline(
    "(() => {{ const nativeView = {view}.android; "
    "if (nativeView && nativeView.setClipChildren) {{ "
    "nativeView.setClipChildren({enabled}); "
    "nativeView.setClipToPadding({enabled}); }} }})()"
)
def set_android_descendant_clipping(view: View, enabled: bool) -> None: ...


@js
def android_visible_bounds(_view: View) -> list[float]:
    return []


@android_visible_bounds.client
@js.inline(
    "(() => {{ const nativeView = {view}.android; "
    "if (!nativeView || !nativeView.getGlobalVisibleRect) return []; "
    "const rect = new android.graphics.Rect(); "
    "if (!nativeView.getGlobalVisibleRect(rect)) "
    "return [0, 0, 0, 0]; "
    "const scale = Screen.mainScreen.scale; "
    "return [rect.left / scale, rect.top / scale, "
    "rect.width() / scale, rect.height() / scale]; }})()"
)
def android_visible_bounds(view: View) -> list[float]: ...


@js
def masonry_column_count(
    width: float,
    minimum_column_width: float = 190,
    maximum_column_count: int = 4,
) -> int:
    if maximum_column_count < 1:
        maximum_column_count = 1
    column_count = 4
    if width < minimum_column_width * 2:
        column_count = 1
    elif width < minimum_column_width * 3:
        column_count = 2
    elif width < minimum_column_width * 4:
        column_count = 3
    if column_count > maximum_column_count:
        return maximum_column_count
    return column_count


@js
class MasonryObserver:
    """Optional lifecycle observer for native masonry drag adapters."""

    __pyjs_structural__ = True

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
    ) -> None: ...

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
    ) -> None: ...

    def committed(
        self,
        decision: MasonryDragDecision,
        anchor: MasonryViewportAnchor | None = None,
        sample: InteractionSample | None = None,
    ) -> None: ...

    def cancelled(self, sample: InteractionSample | None = None) -> None: ...


@js
class MasonryLayout(ScrollView):
    """Natural-height columns composed from NativeScript core views.

    This layout deliberately does not virtualize its children. It is useful for
    modest collections and as a behavior reference for a future native recycler.
    """

    def __init__(
        self,
        minimum_column_width: float = 190,
        maximum_column_count: int = 4,
        group_spacing: float = 0,
        group_separator_color: str = "",
        observer: MasonryObserver | None = None,
    ):
        super().__init__()
        self.minimum_column_width = minimum_column_width
        self.maximum_column_count = maximum_column_count
        self.group_spacing = group_spacing
        self.group_separator_color = group_separator_color
        self.column_count = masonry_column_count(
            Screen.mainScreen.widthDIPs,
            minimum_column_width,
            maximum_column_count,
        )
        self.item_views: list[View] = []
        self.estimated_heights: list[float] = []
        self.item_groups: list[str] = []
        self.preview_locations: list[Point] = []
        self.drag_simulator: MasonryDragSimulator | None = None
        self.drag_session: MasonryDragSession | None = None
        self.drag_decision: MasonryDragDecision | None = None
        self.drag_viewport: MasonryViewport | None = None
        self.drag_translate_x: list[float] = []
        self.drag_translate_y: list[float] = []
        self.drag_source_column = -1
        self.drag_source_container: StackLayout | None = None
        self.masonry_observer = observer
        self.drag_clipping_disabled = False
        self.drag_updated_at = 0
        self.grid = StackLayout()
        self.sections: list[GridLayout] = []
        self.section_columns: list[list[StackLayout]] = []
        self.columns: list[StackLayout] = []
        self.item_columns: list[StackLayout] = []
        self.item_section_columns: list[list[StackLayout]] = []
        self.group_separators: list[GridLayout] = []
        self.content = self.grid
        self.rebuild_columns()

    def append_section(self) -> list[StackLayout]:
        section = GridLayout()
        if self.column_count == 1:
            section.columns = "*"
        elif self.column_count == 2:
            section.columns = "*,*"
        elif self.column_count == 3:
            section.columns = "*,*,*"
        else:
            section.columns = "*,*,*,*"
        columns: list[StackLayout] = []
        for index in range(self.column_count):
            column = StackLayout()
            column.column = index
            columns.append(column)
            section.addChild(column)
        self.sections.append(section)
        self.section_columns.append(columns)
        self.grid.addChild(section)
        if len(self.columns) == 0:
            self.columns = columns
        return columns

    def append_group_separator(self):
        separator = GridLayout()
        separator.height = self.group_spacing
        separator.id = "masonry-group-separator-" + str(
            len(self.group_separators)
        )
        separator.testID = separator.id
        if self.group_separator_color != "" and self.group_spacing > 0:
            line = Label()
            line.height = 1
            line.verticalAlignment = "middle"
            line.backgroundColor = self.group_separator_color
            separator.addChild(line)
        self.group_separators.append(separator)
        self.grid.addChild(separator)

    def rebuild_columns(self):
        for columns in self.section_columns:
            for column in columns:
                column.removeChildren()
        self.grid.removeChildren()
        self.sections = []
        self.section_columns = []
        self.columns = []
        self.item_columns = []
        self.item_section_columns = []
        self.group_separators = []
        self.append_section()

    def set_items(
        self,
        views: list[View],
        estimated_heights: list[float],
        groups: list[str] | None = None,
        assigned_columns: list[int] | None = None,
    ):
        if self.drag_session is not None:
            self.clear_simulated_drag()
        # Removing a column from the grid does not detach the views it owns.
        # Detach them explicitly so reordered items can reuse the same views.
        for columns in self.section_columns:
            for column in columns:
                column.removeChildren()
        self.item_views = views
        self.estimated_heights = estimated_heights
        self.item_groups = []
        for index in range(len(views)):
            group = "default"
            if groups is not None and index < len(groups):
                group = groups[index]
            self.item_groups.append(group)
        self.grid.removeChildren()
        self.sections = []
        self.section_columns = []
        self.columns = []
        self.item_columns = []
        self.item_section_columns = []
        self.group_separators = []
        active_columns = self.append_section()
        column_heights: list[float] = []
        for _index in range(self.column_count):
            column_heights.append(0.0)
        previous_group = ""
        for index in range(len(views)):
            group = self.item_groups[index]
            if previous_group != "" and group != previous_group:
                self.append_group_separator()
                active_columns = self.append_section()
                column_heights = []
                for _column in range(self.column_count):
                    column_heights.append(0.0)
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
            active_columns[target_column].addChild(views[index])
            self.item_columns.append(active_columns[target_column])
            self.item_section_columns.append(active_columns)
            height = 1.0
            if index < len(estimated_heights):
                height = estimated_heights[index]
            column_heights[target_column] += height
            previous_group = group

    def measured_items(
        self,
        layout: MasonryLayoutSnapshot | None = None,
    ) -> list[MasonryItemGeometry]:
        items: list[MasonryItemGeometry] = []
        for index in range(len(self.item_views)):
            view = self.item_views[index]
            width = 0.0
            height = 0.0
            if (
                layout is not None
                and index < len(layout.item_ids)
                and index < len(layout.rects)
                and layout.item_ids[index] == view.id
            ):
                width = layout.rects[index].width
                height = layout.rects[index].height
            else:
                size = self.item_views[index].getActualSize()
                width = size.width
                height = size.height
            placement_height = height
            if index < len(self.estimated_heights):
                placement_height = self.estimated_heights[index]
            group = "default"
            if index < len(self.item_groups):
                group = self.item_groups[index]
            items.append(
                MasonryItemGeometry(
                    view.id,
                    width,
                    height,
                    placement_height,
                    group,
                    _layout_margin(view.marginTop),
                    _layout_margin(view.marginRight),
                    _layout_margin(view.marginBottom),
                    _layout_margin(view.marginLeft),
                )
            )
        return items

    def measured_layout(
        self,
        column_lefts: list[float] | None = None,
    ) -> MasonryLayoutSnapshot:
        item_ids: list[str] = []
        rects: list[NativeRect] = []
        columns: list[int] = []
        content_height = 0.0
        if column_lefts is None:
            column_lefts = []
            for column in self.columns:
                location = column.getLocationRelativeTo(self.grid)
                column_lefts.append(location.x)
        for index in range(len(self.item_views)):
            view = self.item_views[index]
            location = view.getLocationRelativeTo(self.grid)
            size = view.getActualSize()
            item_ids.append(view.id)
            rects.append(NativeRect(location.x, location.y, size.width, size.height))
            column = 0
            nearest = -1.0
            for column_index in range(len(column_lefts)):
                distance = abs(column_lefts[column_index] - location.x)
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
        return MasonryDragSimulator(
            column_lefts,
            content_top,
            group_gap=self.group_spacing,
        )

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

    def refresh_drag_viewport(self) -> MasonryViewport:
        """Remeasure the viewport after a platform layout change mid-drag."""

        viewport = self.viewport()
        self.drag_viewport = viewport
        return viewport

    def start_simulated_drag(
        self,
        source_index: int,
        pointer_screen_x: float,
        pointer_screen_y: float,
        samples: list[InteractionSample] | None = None,
    ):
        simulator = self.simulator()
        original_layout = self.measured_layout(simulator.column_lefts)
        items = self.measured_items(original_layout)
        viewport = self.viewport()
        session = simulator.begin_drag(
            items,
            source_index,
            viewport,
            pointer_screen_x,
            pointer_screen_y,
            original_layout,
        )
        observer = self.masonry_observer
        if observer is not None:
            start_elapsed_ms = 0.0
            if samples is not None and len(samples) > 0:
                start_elapsed_ms = samples[-1].elapsed_ms
            observer.started(
                simulator,
                items,
                source_index,
                viewport,
                pointer_screen_x,
                pointer_screen_y,
                session,
                original_layout,
                start_elapsed_ms=start_elapsed_ms,
                clip_columns=False,
                samples=samples,
            )
        if session is None:
            return
        self.drag_simulator = simulator
        self.drag_session = session
        self.drag_decision = None
        self.drag_viewport = viewport
        self.drag_translate_x = []
        self.drag_translate_y = []
        for view in self.item_views:
            self.drag_translate_x.append(view.translateX)
            self.drag_translate_y.append(view.translateY)
        self.drag_updated_at = Date.now()
        self.drag_source_column = original_layout.columns[source_index]
        if source_index < len(self.item_section_columns):
            source_columns = self.item_section_columns[source_index]
            source_container = source_columns[self.drag_source_column]
            self.drag_source_container = source_container
            source_container.zIndex = 1
            source_container.androidElevation = 24
        self.set_drag_clipping(False)

    def set_drag_clipping(self, enabled: bool):
        set_android_descendant_clipping(self.grid, enabled)
        for section in self.sections:
            set_android_descendant_clipping(section, enabled)
        for columns in self.section_columns:
            for column in columns:
                set_android_descendant_clipping(column, enabled)
        self.drag_clipping_disabled = not enabled

    def update_simulated_drag(
        self,
        pointer_screen_x: float,
        pointer_screen_y: float,
        elapsed_ms: float = -1,
        sample: InteractionSample | None = None,
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
        viewport = self.drag_viewport
        if viewport is None:
            viewport = self.viewport()
            self.drag_viewport = viewport
        viewport = MasonryViewport(
            viewport.screen_x,
            viewport.screen_y,
            viewport.width,
            viewport.height,
            self.verticalOffset,
            viewport.maximum_scroll,
        )
        decision = self.drag_simulator.advance_drag(
            self.drag_session,
            viewport,
            pointer_screen_x,
            pointer_screen_y,
            elapsed_ms,
        )
        self.drag_decision = decision
        if decision.scroll_offset != self.verticalOffset:
            self.scroll_to_offset(decision.scroll_offset)
        for index in range(len(self.item_views)):
            target_x = decision.translate_x[index]
            target_y = decision.translate_y[index]
            if self.drag_translate_x[index] != target_x:
                self.item_views[index].translateX = target_x
                self.drag_translate_x[index] = target_x
            if self.drag_translate_y[index] != target_y:
                self.item_views[index].translateY = target_y
                self.drag_translate_y[index] = target_y
        observer = self.masonry_observer
        if observer is not None:
            projections = self.applied_drag_projections(
                self.drag_simulator,
                self.drag_session,
                decision,
                viewport,
            )
            observer.updated(
                self.drag_simulator,
                self.drag_session,
                viewport,
                pointer_screen_x,
                pointer_screen_y,
                elapsed_ms,
                decision,
                sample=sample,
                projections=projections,
            )
        return decision

    def applied_drag_projections(
        self,
        simulator: MasonryDragSimulator,
        session: MasonryDragSession,
        decision: MasonryDragDecision,
        viewport: MasonryViewport,
    ) -> list[InteractionProjection]:
        predicted = simulator.project_preview(
            session,
            decision,
            viewport,
            False,
        )
        result: list[InteractionProjection] = []
        for index in range(len(session.items)):
            item = session.items[index]
            projected = predicted.item_for(item.id)
            if projected is None:
                continue
            visible = projected.visible_rect
            bounds = android_visible_bounds(self.item_views[index])
            is_visible = projected.is_visible
            if len(bounds) == 4:
                visible = NativeRect(
                    bounds[0] - viewport.screen_x,
                    bounds[1] - viewport.screen_y + decision.scroll_offset,
                    bounds[2],
                    bounds[3],
                )
                is_visible = visible.width > 0 and visible.height > 0
                if not is_visible:
                    visible = NativeRect()
            view = self.item_views[index]
            result.append(
                InteractionProjection(
                    item.id,
                    view.translateX,
                    view.translateY,
                    is_visible and view.visibility == "visible",
                    visible.x,
                    visible.y,
                    visible.width,
                    visible.height,
                )
            )
        return result

    def commit_simulated_drag(
        self,
        anchor: MasonryViewportAnchor | None = None,
        sample: InteractionSample | None = None,
    ) -> MasonryDragDecision | None:
        decision = self.drag_decision
        if not isinstance(decision, MasonryDragDecision):
            return None
        observer = self.masonry_observer
        if observer is not None:
            observer.committed(decision, anchor, sample)
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

    def simulated_drop_translation(self, item_id: str) -> MasonryTranslation:
        """Return an item's translation into the active preview layout."""

        session = self.drag_session
        decision = self.drag_decision
        if not isinstance(session, MasonryDragSession) or not isinstance(
            decision,
            MasonryDragDecision,
        ):
            return MasonryTranslation()
        original = session.original_layout.rect_for(item_id)
        preview = decision.preview_layout.rect_for(item_id)
        if not isinstance(original, NativeRect) or not isinstance(
            preview,
            NativeRect,
        ):
            return MasonryTranslation()
        return MasonryTranslation(preview.x - original.x, preview.y - original.y)

    def capture_viewport_anchor(self, excluded_id: str = "") -> MasonryViewportAnchor:
        if isinstance(self.drag_session, MasonryDragSession):
            if isinstance(self.drag_simulator, MasonryDragSimulator):
                simulator = self.drag_simulator
            else:
                simulator = self.simulator()
            layout = self.drag_session.original_layout
            drag_viewport = self.drag_viewport
            if isinstance(drag_viewport, MasonryViewport):
                active_viewport = MasonryViewport(
                    drag_viewport.screen_x,
                    drag_viewport.screen_y,
                    drag_viewport.width,
                    drag_viewport.height,
                    self.verticalOffset,
                    drag_viewport.maximum_scroll,
                )
            else:
                active_viewport = self.viewport()
        else:
            simulator = self.simulator()
            layout = self.measured_layout(simulator.column_lefts)
            active_viewport = self.viewport()
        return simulator.capture_anchor(
            layout,
            active_viewport,
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

    def clear_simulated_drag(
        self,
        excluded_index: int = -1,
        sample: InteractionSample | None = None,
    ):
        observer = self.masonry_observer
        if observer is not None:
            observer.cancelled(sample)
        for index in range(len(self.item_views)):
            if index != excluded_index:
                if (
                    index >= len(self.drag_translate_x)
                    or self.drag_translate_x[index] != 0
                ):
                    self.item_views[index].translateX = 0.0
                if (
                    index >= len(self.drag_translate_y)
                    or self.drag_translate_y[index] != 0
                ):
                    self.item_views[index].translateY = 0.0
        self.drag_simulator = None
        self.drag_session = None
        self.drag_decision = None
        self.drag_viewport = None
        self.drag_translate_x = []
        self.drag_translate_y = []
        self.drag_updated_at = 0
        source_container = self.drag_source_container
        if isinstance(source_container, StackLayout):
            source_container.zIndex = 0
            source_container.androidElevation = 0
        self.drag_source_container = None
        self.drag_source_column = -1
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
    "MasonryObserver",
    "android_visible_bounds",
    "masonry_column_count",
    "set_android_descendant_clipping",
]
