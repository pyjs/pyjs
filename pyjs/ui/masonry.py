from pyjs import js
from pyjs.ui.reorderable import edge_scroll_offset


@js
def _minimum(left: float, right: float) -> float:
    if left < right:
        return left
    return right


@js
def _maximum(left: float, right: float) -> float:
    if left > right:
        return left
    return right


@js
class MasonryTranslation:
    def __init__(self, x: float = 0, y: float = 0):
        self.x = x
        self.y = y


@js
class NativeRect:
    def __init__(
        self,
        x: float = 0,
        y: float = 0,
        width: float = 0,
        height: float = 0,
    ):
        self.x = x
        self.y = y
        self.width = _maximum(0.0, width)
        self.height = _maximum(0.0, height)
        self.right = x + self.width
        self.bottom = y + self.height

    def translated(self, x: float, y: float) -> NativeRect:
        return NativeRect(self.x + x, self.y + y, self.width, self.height)

    def intersection(self, other: NativeRect) -> NativeRect:
        left = _maximum(self.x, other.x)
        top = _maximum(self.y, other.y)
        right = _minimum(self.right, other.right)
        bottom = _minimum(self.bottom, other.bottom)
        if right <= left or bottom <= top:
            return NativeRect()
        return NativeRect(
            left,
            top,
            right - left,
            bottom - top,
        )

    def contains(self, x: float, y: float) -> bool:
        return (
            self.width > 0
            and self.height > 0
            and x >= self.x
            and x <= self.right
            and y >= self.y
            and y <= self.bottom
        )


@js
class MasonryItemGeometry:
    def __init__(
        self,
        item_id: str,
        width: float,
        height: float,
        placement_height: float = -1,
        group: str = "default",
        margin_top: float = 0,
        margin_right: float = 0,
        margin_bottom: float = 0,
        margin_left: float = 0,
    ):
        self.id = item_id
        self.width = width
        self.height = height
        self.placement_height = height if placement_height < 0 else placement_height
        self.group = group
        self.margin_top = margin_top
        self.margin_right = margin_right
        self.margin_bottom = margin_bottom
        self.margin_left = margin_left


@js
class MasonryLayoutSnapshot:
    def __init__(
        self,
        item_ids: list[str],
        rects: list[NativeRect],
        columns: list[int],
        content_height: float,
    ):
        self.item_ids = item_ids
        self.rects = rects
        self.columns = columns
        self.content_height = content_height

    def index_of(self, item_id: str) -> int:
        for index in range(len(self.item_ids)):
            if self.item_ids[index] == item_id:
                return index
        return -1

    def rect_for(self, item_id: str) -> NativeRect | None:
        index = self.index_of(item_id)
        if index < 0:
            return None
        return self.rects[index]


@js
class MasonryViewport:
    def __init__(
        self,
        screen_x: float,
        screen_y: float,
        width: float,
        height: float,
        scroll_offset: float,
        maximum_scroll: float,
    ):
        self.screen_x = screen_x
        self.screen_y = screen_y
        self.width = width
        self.height = height
        self.scroll_offset = scroll_offset
        self.maximum_scroll = maximum_scroll


@js
class MasonryViewportAnchor:
    def __init__(self, item_id: str = "", screen_y: float = 0):
        self.item_id = item_id
        self.screen_y = screen_y


@js
class MasonryDropSlot:
    def __init__(
        self,
        destination_index: int,
        destination_column: int,
        destination_lane_index: int,
        insertion_index: int,
        source_rect: NativeRect,
    ):
        self.destination_index = destination_index
        self.destination_column = destination_column
        self.destination_lane_index = destination_lane_index
        self.insertion_index = insertion_index
        self.source_rect = source_rect


@js
class MasonryDragSession:
    def __init__(
        self,
        items: list[MasonryItemGeometry],
        source_index: int,
        original_layout: MasonryLayoutSnapshot,
        grab_x: float,
        grab_y: float,
        slots: list[MasonryDropSlot],
    ):
        self.items = items
        self.source_index = source_index
        self.source_id = items[source_index].id
        self.original_layout = original_layout
        self.grab_x = grab_x
        self.grab_y = grab_y
        self.slots = slots
        self.destination_index = source_index
        source_layout_index = original_layout.index_of(self.source_id)
        self.destination_column = 0
        self.destination_lane_index = 0
        self.preview_column = -1
        self.preview_lane_index = -1
        self.preview_layout = original_layout
        if source_layout_index >= 0:
            self.destination_column = original_layout.columns[source_layout_index]
            source_rect = original_layout.rects[source_layout_index]
            for slot in slots:
                if (
                    slot.destination_column == self.destination_column
                    and slot.source_rect.x == source_rect.x
                    and slot.source_rect.y == source_rect.y
                ):
                    self.destination_lane_index = slot.destination_lane_index


@js
class MasonryDragDecision:
    def __init__(
        self,
        destination_index: int,
        destination_column: int,
        destination_lane_index: int,
        scroll_offset: float,
        preview_layout: MasonryLayoutSnapshot,
        translate_x: list[float],
        translate_y: list[float],
    ):
        self.destination_index = destination_index
        self.destination_column = destination_column
        self.destination_lane_index = destination_lane_index
        self.scroll_offset = scroll_offset
        self.preview_layout = preview_layout
        self.translate_x = translate_x
        self.translate_y = translate_y


@js
class MasonryProjectedItem:
    """A card's native projection after transforms and ancestor clipping."""

    def __init__(
        self,
        item_id: str,
        visual_rect: NativeRect,
        visible_rect: NativeRect,
        original_column: int,
        target_column: int,
    ):
        self.item_id = item_id
        self.visual_rect = visual_rect
        self.visible_rect = visible_rect
        self.original_column = original_column
        self.target_column = target_column
        self.crosses_columns = original_column != target_column
        self.is_visible = visible_rect.width > 0 and visible_rect.height > 0
        center_x = visual_rect.x + visual_rect.width / 2
        center_y = visual_rect.y + visual_rect.height / 2
        self.center_is_visible = visible_rect.contains(center_x, center_y)


@js
class MasonryProjectionSnapshot:
    def __init__(self, items: list[MasonryProjectedItem]):
        self.items = items

    def item_for(self, item_id: str) -> MasonryProjectedItem | None:
        for item in self.items:
            if item.item_id == item_id:
                return item
        return None

    def invisible_ids(self) -> list[str]:
        result: list[str] = []
        for item in self.items:
            if not item.is_visible:
                result.append(item.item_id)
        return result


@js
def _group_runs(items: list[MasonryItemGeometry]) -> list[int]:
    """Identify contiguous group runs without merging repeated names."""

    runs: list[int] = []
    run = -1
    previous = ""
    for item in items:
        if len(runs) == 0 or item.group != previous:
            run += 1
            previous = item.group
        runs.append(run)
    return runs


@js
def _clamp(value: float, minimum: float, maximum: float) -> float:
    if maximum < minimum:
        maximum = minimum
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


@js
class MasonryDragSimulator:
    """Deterministic masonry layout and drag mechanics in layout units.

    Native adapters provide measured item sizes and screen geometry. The
    simulator owns placement, legal insertion slots, previews, edge scrolling,
    and viewport anchoring without depending on a native renderer.
    """

    def __init__(
        self,
        column_lefts: list[float],
        content_top: float = 0,
        vertical_gap: float = 0,
        edge_size: float = 64,
        edge_step: float = 24,
        edge_interval_ms: float = 50,
        hysteresis: float = 12,
        group_gap: float = 0,
    ):
        self.column_lefts: list[float] = []
        for left in column_lefts:
            self.column_lefts.append(left)
        if len(self.column_lefts) == 0:
            self.column_lefts.append(0.0)
        self.content_top = content_top
        self.vertical_gap = vertical_gap
        self.group_gap = group_gap
        self.edge_size = edge_size
        self.edge_step = edge_step
        self.edge_interval_ms = edge_interval_ms
        self.hysteresis = hysteresis

    def layout(self, items: list[MasonryItemGeometry]) -> MasonryLayoutSnapshot:
        item_ids: list[str] = []
        rects: list[NativeRect] = []
        columns: list[int] = []
        placement_heights: list[float] = []
        actual_bottoms: list[float] = []
        for _column in self.column_lefts:
            placement_heights.append(0.0)
            actual_bottoms.append(self.content_top)

        content_height = self.content_top
        previous_group = ""
        for item in items:
            if previous_group != "" and item.group != previous_group:
                group_top = max(actual_bottoms) + self.group_gap
                placement_heights = []
                actual_bottoms = []
                for _column in self.column_lefts:
                    placement_heights.append(0.0)
                    actual_bottoms.append(group_top)
            target_column = 0
            for column in range(1, len(self.column_lefts)):
                if placement_heights[column] < placement_heights[target_column]:
                    target_column = column
            rect = NativeRect(
                self.column_lefts[target_column] + item.margin_left,
                actual_bottoms[target_column] + item.margin_top,
                item.width,
                item.height,
            )
            item_ids.append(item.id)
            rects.append(rect)
            columns.append(target_column)
            placement_heights[target_column] += item.placement_height
            actual_bottoms[target_column] = (
                rect.bottom + item.margin_bottom + self.vertical_gap
            )
            if rect.bottom > content_height:
                content_height = rect.bottom
            previous_group = item.group
        return MasonryLayoutSnapshot(item_ids, rects, columns, content_height)

    def layout_in_columns(
        self,
        items: list[MasonryItemGeometry],
        assigned_columns: list[int],
        group_runs: list[int] | None = None,
    ) -> MasonryLayoutSnapshot:
        """Lay out items in explicit columns while retaining natural heights."""

        item_ids: list[str] = []
        rects: list[NativeRect] = []
        columns: list[int] = []
        placement_heights: list[float] = []
        actual_bottoms: list[float] = []
        for _column in self.column_lefts:
            placement_heights.append(0.0)
            actual_bottoms.append(self.content_top)

        content_height = self.content_top
        previous_group = ""
        previous_run = -1
        for index in range(len(items)):
            item = items[index]
            run = -1
            if group_runs is not None and index < len(group_runs):
                run = group_runs[index]
            group_changed = previous_group != "" and item.group != previous_group
            if run >= 0 and previous_run >= 0:
                group_changed = run != previous_run
            if group_changed:
                group_top = max(actual_bottoms) + self.group_gap
                placement_heights = []
                actual_bottoms = []
                for _column in self.column_lefts:
                    placement_heights.append(0.0)
                    actual_bottoms.append(group_top)
            target_column = -1
            if index < len(assigned_columns):
                candidate = assigned_columns[index]
                if candidate >= 0 and candidate < len(self.column_lefts):
                    target_column = candidate
            if target_column < 0:
                target_column = 0
                for column in range(1, len(self.column_lefts)):
                    if placement_heights[column] < placement_heights[target_column]:
                        target_column = column
            rect = NativeRect(
                self.column_lefts[target_column] + item.margin_left,
                actual_bottoms[target_column] + item.margin_top,
                item.width,
                item.height,
            )
            item_ids.append(item.id)
            rects.append(rect)
            columns.append(target_column)
            placement_heights[target_column] += item.placement_height
            actual_bottoms[target_column] = (
                rect.bottom + item.margin_bottom + self.vertical_gap
            )
            if rect.bottom > content_height:
                content_height = rect.bottom
            previous_group = item.group
            previous_run = run
        return MasonryLayoutSnapshot(item_ids, rects, columns, content_height)

    def moved_items(
        self,
        items: list[MasonryItemGeometry],
        source_index: int,
        destination_index: int,
    ) -> list[MasonryItemGeometry]:
        result: list[MasonryItemGeometry] = []
        if source_index < 0 or source_index >= len(items):
            for item in items:
                result.append(item)
            return result
        if destination_index < 0:
            destination_index = 0
        elif destination_index >= len(items):
            destination_index = len(items) - 1
        source = items[source_index]
        for index in range(len(items)):
            if index != source_index:
                result.append(items[index])
        result.insert(destination_index, source)
        return result

    def _canonical_layout(
        self,
        items: list[MasonryItemGeometry],
        columns: list[int],
        group_runs: list[int],
        run_count: int,
    ) -> MasonryLayoutSnapshot:
        """Order persisted items by visual position without mixing groups."""

        initial = self.layout_in_columns(items, columns, group_runs)
        ordered_ids: list[str] = []
        ordered_rects: list[NativeRect] = []
        ordered_columns: list[int] = []
        for run in range(run_count):
            column_items: list[list[int]] = []
            column_positions: list[int] = []
            for _column in self.column_lefts:
                column_items.append([])
                column_positions.append(0)
            run_size = 0
            for index in range(len(items)):
                if group_runs[index] == run:
                    column_items[initial.columns[index]].append(index)
                    run_size += 1
            for _item in range(run_size):
                selected_index = -1
                selected_column = -1
                selected_rect: NativeRect | None = None
                for column in range(len(column_items)):
                    position = column_positions[column]
                    if position < len(column_items[column]):
                        index = column_items[column][position]
                        rect = initial.rects[index]
                        if (
                            selected_rect is None
                            or rect.y < selected_rect.y
                            or (
                                rect.y == selected_rect.y
                                and rect.x < selected_rect.x
                            )
                        ):
                            selected_index = index
                            selected_column = column
                            selected_rect = rect
                if selected_index >= 0 and selected_rect is not None:
                    column_positions[selected_column] += 1
                    ordered_ids.append(items[selected_index].id)
                    ordered_rects.append(selected_rect)
                    ordered_columns.append(initial.columns[selected_index])
        return MasonryLayoutSnapshot(
            ordered_ids,
            ordered_rects,
            ordered_columns,
            initial.content_height,
        )

    def _remaining_drag_items(
        self,
        items: list[MasonryItemGeometry],
        source_index: int,
        layout: MasonryLayoutSnapshot,
        item_runs: list[int],
    ) -> tuple[list[MasonryItemGeometry], list[int], list[int]]:
        remaining_items: list[MasonryItemGeometry] = []
        remaining_columns: list[int] = []
        remaining_runs: list[int] = []
        for index in range(len(items)):
            if index == source_index:
                continue
            item = items[index]
            layout_index = layout.index_of(item.id)
            column = 0
            if layout_index >= 0:
                column = layout.columns[layout_index]
            remaining_items.append(item)
            remaining_columns.append(column)
            remaining_runs.append(item_runs[index])
        return remaining_items, remaining_columns, remaining_runs

    def drop_slots(
        self,
        items: list[MasonryItemGeometry],
        source_index: int,
        original_layout: MasonryLayoutSnapshot | None = None,
    ) -> list[MasonryDropSlot]:
        """Return one legal insertion gap per lane within the source group."""

        slots: list[MasonryDropSlot] = []
        if source_index < 0 or source_index >= len(items):
            return slots
        layout = self.layout(items)
        if original_layout is not None:
            layout = original_layout
        source = items[source_index]
        item_runs = _group_runs(items)
        source_run = item_runs[source_index]
        remaining_items, remaining_columns, remaining_runs = (
            self._remaining_drag_items(
                items,
                source_index,
                layout,
                item_runs,
            )
        )

        remaining_layout = self.layout_in_columns(
            remaining_items,
            remaining_columns,
            remaining_runs,
        )
        group_top = self.content_top
        found_group_top = False
        for index in range(len(items)):
            if item_runs[index] != source_run:
                continue
            layout_index = layout.index_of(items[index].id)
            if layout_index < 0:
                continue
            rect = layout.rects[layout_index]
            candidate_top = rect.y - items[index].margin_top
            if not found_group_top or candidate_top < group_top:
                group_top = candidate_top
                found_group_top = True
        earlier_run_items = 0
        for run in remaining_runs:
            if run < source_run:
                earlier_run_items += 1
        seen_positions: set[str] = set()

        for target_column in range(len(self.column_lefts)):
            lane_positions: list[int] = []
            for index in range(len(remaining_items)):
                if (
                    remaining_runs[index] == source_run
                    and remaining_columns[index] == target_column
                ):
                    lane_positions.append(index)
            column_bottom = group_top
            scanned_index = 0
            for lane_index in range(len(lane_positions) + 1):
                insertion_index = source_index
                if lane_index < len(lane_positions):
                    insertion_index = lane_positions[lane_index]
                elif len(lane_positions) > 0:
                    insertion_index = lane_positions[-1] + 1
                else:
                    insertion_index = len(remaining_items)
                    for index in range(len(remaining_items)):
                        if remaining_runs[index] == source_run:
                            insertion_index = index
                            break
                    if insertion_index == len(remaining_items):
                        insertion_index = source_index
                insertion_index = int(
                    _clamp(insertion_index, 0, len(remaining_items))
                )

                while scanned_index < insertion_index:
                    if (
                        remaining_runs[scanned_index] == source_run
                        and remaining_columns[scanned_index] == target_column
                    ):
                        rect = remaining_layout.rects[scanned_index]
                        item = remaining_items[scanned_index]
                        column_bottom = (
                            rect.bottom + item.margin_bottom + self.vertical_gap
                        )
                    scanned_index += 1
                source_rect = NativeRect(
                    self.column_lefts[target_column] + source.margin_left,
                    column_bottom + source.margin_top,
                    source.width,
                    source.height,
                )
                position_key = str(source_rect.x) + ":" + str(source_rect.y)
                if position_key in seen_positions:
                    continue
                seen_positions.add(position_key)

                source_span = (
                    source.margin_top
                    + source.height
                    + source.margin_bottom
                    + self.vertical_gap
                )
                destination_index = earlier_run_items
                for index in range(len(remaining_items)):
                    if remaining_runs[index] != source_run:
                        continue
                    rect = remaining_layout.rects[index]
                    item_y = rect.y
                    if (
                        remaining_columns[index] == target_column
                        and index >= insertion_index
                    ):
                        item_y += source_span
                    item_before_source = item_y < source_rect.y
                    if item_y == source_rect.y:
                        if rect.x < source_rect.x:
                            item_before_source = True
                        elif rect.x == source_rect.x:
                            item_column = remaining_columns[index]
                            item_before_source = item_column < target_column or (
                                item_column == target_column
                                and index < insertion_index
                            )
                    if item_before_source:
                        destination_index += 1

                slots.append(
                    MasonryDropSlot(
                        destination_index,
                        target_column,
                        lane_index,
                        insertion_index,
                        source_rect,
                    )
                )
        return slots

    def layout_for_slot(
        self,
        items: list[MasonryItemGeometry],
        source_index: int,
        slot: MasonryDropSlot,
        original_layout: MasonryLayoutSnapshot | None = None,
    ) -> MasonryLayoutSnapshot:
        """Materialize the exact preview for one compact drop-slot recipe."""

        if source_index < 0 or source_index >= len(items):
            return self.layout(items)
        layout = self.layout(items)
        if original_layout is not None:
            layout = original_layout
        item_runs = _group_runs(items)
        source = items[source_index]
        source_run = item_runs[source_index]
        remaining_items, remaining_columns, remaining_runs = (
            self._remaining_drag_items(
                items,
                source_index,
                layout,
                item_runs,
            )
        )

        candidate_items: list[MasonryItemGeometry] = []
        candidate_columns: list[int] = []
        candidate_runs: list[int] = []
        insertion_index = int(
            _clamp(slot.insertion_index, 0, len(remaining_items))
        )
        for index in range(len(remaining_items) + 1):
            if index == insertion_index:
                candidate_items.append(source)
                candidate_columns.append(slot.destination_column)
                candidate_runs.append(source_run)
            if index < len(remaining_items):
                candidate_items.append(remaining_items[index])
                candidate_columns.append(remaining_columns[index])
                candidate_runs.append(remaining_runs[index])
        return self._canonical_layout(
            candidate_items,
            candidate_columns,
            candidate_runs,
            item_runs[-1] + 1,
        )

    def begin_drag(
        self,
        items: list[MasonryItemGeometry],
        source_index: int,
        viewport: MasonryViewport,
        pointer_screen_x: float,
        pointer_screen_y: float,
        original_layout: MasonryLayoutSnapshot | None = None,
    ) -> MasonryDragSession | None:
        if source_index < 0 or source_index >= len(items):
            return None
        layout = self.layout(items)
        if original_layout is not None:
            layout = original_layout
        maybe_source_rect = layout.rect_for(items[source_index].id)
        source_rect = NativeRect()
        if isinstance(maybe_source_rect, NativeRect):
            source_rect = maybe_source_rect
        pointer_content_x = pointer_screen_x - viewport.screen_x
        pointer_content_y = pointer_screen_y - viewport.screen_y + viewport.scroll_offset
        slots = self.drop_slots(items, source_index, layout)
        return MasonryDragSession(
            items,
            source_index,
            layout,
            pointer_content_x - source_rect.x,
            pointer_content_y - source_rect.y,
            slots,
        )

    def edge_scroll_offset(
        self,
        viewport: MasonryViewport,
        pointer_screen_y: float,
        elapsed_ms: float = -1,
    ) -> float:
        return edge_scroll_offset(
            pointer_screen_y,
            viewport.screen_y,
            viewport.height,
            viewport.scroll_offset,
            viewport.maximum_scroll,
            self.edge_size,
            self.edge_step,
            elapsed_ms,
            self.edge_interval_ms,
        )

    def column_clip(self, column: int, viewport: MasonryViewport) -> NativeRect:
        if column < 0 or column >= len(self.column_lefts):
            return NativeRect()
        left = self.column_lefts[column]
        right = viewport.width
        if column + 1 < len(self.column_lefts):
            right = self.column_lefts[column + 1]
        return NativeRect(
            left,
            viewport.scroll_offset,
            _maximum(0.0, right - left),
            _maximum(0.0, viewport.height),
        )

    def project_preview(
        self,
        session: MasonryDragSession,
        decision: MasonryDragDecision,
        viewport: MasonryViewport,
        clip_columns: bool = True,
    ) -> MasonryProjectionSnapshot:
        """Project a preview through the relevant native clipping hierarchy.

        Android column containers clip translated children by
        default. Adapters that disable column clipping during a drag pass
        ``clip_columns=False``; the viewport remains clipped in either mode.
        """

        projected: list[MasonryProjectedItem] = []
        projection_viewport = MasonryViewport(
            viewport.screen_x,
            viewport.screen_y,
            viewport.width,
            viewport.height,
            decision.scroll_offset,
            viewport.maximum_scroll,
        )
        viewport_clip = NativeRect(
            0,
            projection_viewport.scroll_offset,
            _maximum(0.0, viewport.width),
            _maximum(0.0, viewport.height),
        )
        for index in range(len(session.items)):
            item = session.items[index]
            original_index = session.original_layout.index_of(item.id)
            target_index = decision.preview_layout.index_of(item.id)
            if original_index < 0 or target_index < 0:
                projected.append(
                    MasonryProjectedItem(item.id, NativeRect(), NativeRect(), -1, -1)
                )
                continue
            original = session.original_layout.rects[original_index]
            visual = original.translated(
                decision.translate_x[index],
                decision.translate_y[index],
            )
            visible = visual.intersection(viewport_clip)
            original_column = session.original_layout.columns[original_index]
            target_column = decision.preview_layout.columns[target_index]
            if clip_columns:
                visible = visible.intersection(
                    self.column_clip(original_column, projection_viewport)
                )
            projected.append(
                MasonryProjectedItem(
                    item.id,
                    visual,
                    visible,
                    original_column,
                    target_column,
                )
            )
        return MasonryProjectionSnapshot(projected)

    def advance_drag(
        self,
        session: MasonryDragSession,
        viewport: MasonryViewport,
        pointer_screen_x: float,
        pointer_screen_y: float,
        elapsed_ms: float = -1,
    ) -> MasonryDragDecision:
        scroll_offset = self.edge_scroll_offset(
            viewport,
            pointer_screen_y,
            elapsed_ms,
        )
        desired_x = pointer_screen_x - viewport.screen_x - session.grab_x
        desired_y = pointer_screen_y - viewport.screen_y + scroll_offset - session.grab_y
        slots = session.slots
        selected_column = slots[0].destination_column
        best_column_distance = abs(slots[0].source_rect.x - desired_x)
        current_column_distance = -1.0
        for slot in slots:
            column_distance = abs(slot.source_rect.x - desired_x)
            if column_distance < best_column_distance:
                selected_column = slot.destination_column
                best_column_distance = column_distance
            if slot.destination_column == session.destination_column:
                current_column_distance = column_distance
        if (
            current_column_distance >= 0
            and current_column_distance <= best_column_distance + self.hysteresis
        ):
            selected_column = session.destination_column

        selected = slots[0]
        for slot in slots:
            if slot.destination_column == selected_column:
                selected = slot
                break
        best_distance = abs(selected.source_rect.y - desired_y)
        current_slot: MasonryDropSlot | None = None
        current_distance = -1.0
        for slot in slots:
            distance = abs(slot.source_rect.y - desired_y)
            if (
                slot.destination_column == selected_column
                and distance < best_distance
            ):
                selected = slot
                best_distance = distance
            if (
                slot.destination_column == session.destination_column
                and slot.destination_lane_index == session.destination_lane_index
            ):
                current_slot = slot
                current_distance = distance
        if (
            isinstance(current_slot, MasonryDropSlot)
            and current_slot.destination_column == selected_column
            and current_distance <= best_distance + self.hysteresis
        ):
            selected = current_slot
        session.destination_index = selected.destination_index
        session.destination_column = selected.destination_column
        session.destination_lane_index = selected.destination_lane_index
        if (
            session.preview_column != selected.destination_column
            or session.preview_lane_index != selected.destination_lane_index
        ):
            session.preview_layout = self.layout_for_slot(
                session.items,
                session.source_index,
                selected,
                session.original_layout,
            )
            session.preview_column = selected.destination_column
            session.preview_lane_index = selected.destination_lane_index
        preview_layout = session.preview_layout
        source_visual_y = desired_y
        minimum_source_y = -1.0
        for slot in slots:
            if slot.destination_column != selected_column:
                continue
            slot_y = slot.source_rect.y
            if minimum_source_y < 0 or slot_y < minimum_source_y:
                minimum_source_y = slot_y
        if minimum_source_y >= 0 and source_visual_y < minimum_source_y:
            source_visual_y = minimum_source_y

        translate_x: list[float] = []
        translate_y: list[float] = []
        for index in range(len(session.items)):
            item = session.items[index]
            original_rect = session.original_layout.rect_for(item.id)
            target_rect = preview_layout.rect_for(item.id)
            if not isinstance(original_rect, NativeRect) or not isinstance(
                target_rect, NativeRect
            ):
                translate_x.append(0.0)
                translate_y.append(0.0)
            elif index == session.source_index:
                translate_x.append(desired_x - original_rect.x)
                translate_y.append(source_visual_y - original_rect.y)
            else:
                translate_x.append(target_rect.x - original_rect.x)
                translate_y.append(target_rect.y - original_rect.y)
        return MasonryDragDecision(
            selected.destination_index,
            selected.destination_column,
            selected.destination_lane_index,
            scroll_offset,
            preview_layout,
            translate_x,
            translate_y,
        )

    def capture_anchor(
        self,
        layout: MasonryLayoutSnapshot,
        viewport: MasonryViewport,
        excluded_id: str = "",
    ) -> MasonryViewportAnchor:
        selected_id = ""
        selected_y = 0.0
        selected_distance = -1.0
        selected_visible_top = False
        viewport_bottom = viewport.scroll_offset + viewport.height
        for index in range(len(layout.item_ids)):
            item_id = layout.item_ids[index]
            rect = layout.rects[index]
            if (
                item_id != excluded_id
                and rect.bottom >= viewport.scroll_offset
                and rect.y <= viewport_bottom
            ):
                screen_y = viewport.screen_y + rect.y - viewport.scroll_offset
                visible_top = rect.y >= viewport.scroll_offset
                if not visible_top and screen_y < viewport.screen_y:
                    screen_y = viewport.screen_y
                distance = screen_y - viewport.screen_y
                if distance < 0:
                    distance = -distance
                if (
                    (visible_top and not selected_visible_top)
                    or (
                        visible_top == selected_visible_top
                        and (selected_distance < 0 or distance < selected_distance)
                    )
                ):
                    selected_id = item_id
                    selected_y = screen_y
                    selected_distance = distance
                    selected_visible_top = visible_top
        return MasonryViewportAnchor(selected_id, selected_y)

    def restore_anchor(
        self,
        layout: MasonryLayoutSnapshot,
        viewport: MasonryViewport,
        anchor: MasonryViewportAnchor,
    ) -> float:
        rect = layout.rect_for(anchor.item_id)
        if not isinstance(rect, NativeRect) or anchor.item_id == "":
            return _clamp(viewport.scroll_offset, 0, viewport.maximum_scroll)
        target = rect.y - (anchor.screen_y - viewport.screen_y)
        return _clamp(target, 0, viewport.maximum_scroll)


__all__ = [
    "MasonryDragDecision",
    "MasonryDragSession",
    "MasonryDragSimulator",
    "MasonryDropSlot",
    "MasonryItemGeometry",
    "MasonryLayoutSnapshot",
    "MasonryTranslation",
    "MasonryProjectedItem",
    "MasonryProjectionSnapshot",
    "MasonryViewport",
    "MasonryViewportAnchor",
    "NativeRect",
]
