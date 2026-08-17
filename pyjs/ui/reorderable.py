from pyjs import js
from pyjs.ui.gesture import GestureScript


@js
class ReorderItem:
    """A stable item identifier and its zero-based outline depth."""

    def __init__(self, item_id: str, depth: int = 0):
        self.id = item_id
        self.depth = depth


@js
class ReorderRow:
    """Platform-measured geometry for one visible reorderable row."""

    def __init__(self, item_id: str, start: float, size: float):
        self.id = item_id
        self.start = start
        self.size = size


@js
class ReorderDecision:
    """A platform-neutral preview and its corresponding committed outline."""

    def __init__(
        self,
        source_id: str,
        hidden_item_ids: list[str],
        visible_items: list[ReorderItem],
        committed_items: list[ReorderItem],
        insertion_index: int,
        target_depth: int,
    ):
        self.source_id = source_id
        self.hidden_item_ids = hidden_item_ids
        self.visible_items = visible_items
        self.committed_items = committed_items
        self.insertion_index = insertion_index
        self.target_depth = target_depth

    def visible_item_ids(self):
        return [item.id for item in self.visible_items]

    def visible_depths(self):
        return [item.depth for item in self.visible_items]

    def committed_item_ids(self):
        return [item.id for item in self.committed_items]

    def committed_depths(self):
        return [item.depth for item in self.committed_items]


@js
class ReorderSession:
    """One drag of an item and its contiguous descendant subtree."""

    def __init__(
        self,
        items: list[ReorderItem],
        source_index: int,
        max_depth: int,
        indent_step: float,
    ):
        self.items = items
        self.source_index = source_index
        self.max_depth = max_depth
        self.indent_step = indent_step
        self.source = items[source_index]
        self.source_depth = self.source.depth

        subtree_end = source_index + 1
        while (
            subtree_end < len(items)
            and items[subtree_end].depth > self.source_depth
        ):
            subtree_end += 1
        self.subtree_end = subtree_end
        self.subtree = items[source_index:subtree_end]
        self.remaining_items: list[ReorderItem] = []
        for index in range(source_index):
            self.remaining_items.append(items[index])
        for index in range(subtree_end, len(items)):
            self.remaining_items.append(items[index])
        self.hidden_item_ids = [item.id for item in self.subtree[1:]]

        relative_max_depth = 0
        for item in self.subtree:
            relative_depth = item.depth - self.source_depth
            if relative_depth > relative_max_depth:
                relative_max_depth = relative_depth
        self.relative_max_depth = relative_max_depth

    def insertion_index_at(
        self,
        rows: list[ReorderRow],
        pointer: float,
    ) -> int:
        insertion_index = 0
        for row in rows:
            if row.id == self.source.id or row.id in self.hidden_item_ids:
                continue
            if pointer <= row.start + row.size / 2:
                return insertion_index
            insertion_index += 1
        return insertion_index

    def depth_for_delta(self, delta: float) -> int:
        change = 0
        if delta >= self.indent_step:
            change = int(delta / self.indent_step)
        elif delta <= -self.indent_step:
            change = -int(-delta / self.indent_step)
        return self.source_depth + change

    def preview(
        self,
        insertion_index: int,
        requested_depth: int,
    ) -> ReorderDecision:
        insertion_index = max(0, min(insertion_index, len(self.remaining_items)))
        maximum_depth = self.max_depth - self.relative_max_depth
        if insertion_index == 0:
            maximum_depth = 0
        else:
            previous_depth = self.remaining_items[insertion_index - 1].depth
            maximum_depth = min(maximum_depth, previous_depth + 1)
        target_depth = max(0, min(requested_depth, maximum_depth))

        source = ReorderItem(self.source.id, target_depth)
        visible_items: list[ReorderItem] = []
        for index in range(insertion_index):
            visible_items.append(self.remaining_items[index])
        visible_items.append(source)
        for index in range(insertion_index, len(self.remaining_items)):
            visible_items.append(self.remaining_items[index])

        depth_change = target_depth - self.source_depth
        moved_subtree: list[ReorderItem] = []
        for item in self.subtree:
            moved_subtree.append(ReorderItem(item.id, item.depth + depth_change))
        committed_items: list[ReorderItem] = []
        for index in range(insertion_index):
            committed_items.append(self.remaining_items[index])
        for item in moved_subtree:
            committed_items.append(item)
        for index in range(insertion_index, len(self.remaining_items)):
            committed_items.append(self.remaining_items[index])
        committed_items = _normalize_items(committed_items, self.max_depth)

        return ReorderDecision(
            self.source.id,
            self.hidden_item_ids,
            visible_items,
            committed_items,
            insertion_index,
            target_depth,
        )

    def update(
        self,
        rows: list[ReorderRow],
        pointer: float,
        horizontal_delta: float,
    ) -> ReorderDecision:
        return self.preview(
            self.insertion_index_at(rows, pointer),
            self.depth_for_delta(horizontal_delta),
        )


@js
class HierarchicalReorder:
    """Configurable outline reordering shared by web and native adapters.

    Depth is zero-based: a ``max_depth`` of 2 allows three visible levels.
    Descendants collapse during a drag but move with their parent on commit.
    """

    def __init__(self, max_depth: int = 5, indent_step: float = 36):
        self.max_depth = max(0, max_depth)
        self.indent_step = max(1.0, indent_step)

    def begin(
        self,
        items: list[ReorderItem],
        source_index: int,
    ) -> ReorderSession | None:
        if source_index < 0 or source_index >= len(items):
            return None
        normalized = _normalize_items(items, self.max_depth)
        return ReorderSession(
            normalized,
            source_index,
            self.max_depth,
            self.indent_step,
        )


@js
def replay_reorder_gesture(
    session: ReorderSession,
    rows: list[ReorderRow],
    script: GestureScript,
) -> list[ReorderDecision]:
    decisions: list[ReorderDecision] = []
    start_x = 0.0
    active = False
    for sample in script.samples:
        if sample.phase == "down":
            start_x = sample.x
            active = True
        elif active and (sample.phase == "hold" or sample.phase == "move"):
            decisions.append(
                session.update(
                    rows,
                    sample.y,
                    sample.x - start_x,
                )
            )
        elif sample.phase == "up" or sample.phase == "cancel":
            active = False
    return decisions


@js
def _normalize_items(
    items: list[ReorderItem],
    max_depth: int,
) -> list[ReorderItem]:
    normalized: list[ReorderItem] = []
    previous_depth = 0
    for index in range(len(items)):
        item = items[index]
        depth = max(0, min(item.depth, max_depth))
        if index == 0:
            depth = 0
        else:
            depth = min(depth, previous_depth + 1)
        normalized.append(ReorderItem(item.id, depth))
        previous_depth = depth
    return normalized


__all__ = [
    "HierarchicalReorder",
    "ReorderDecision",
    "ReorderItem",
    "ReorderRow",
    "ReorderSession",
    "replay_reorder_gesture",
]
