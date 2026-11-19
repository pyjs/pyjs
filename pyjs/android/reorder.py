"""Drag stabilization for native staggered grids."""

from pyjs.android.gestures import view_configuration
from pyjs.android.recyclerview import (
    ItemTouchCallback,
    RecyclerView,
    RecyclerViewViewHolder,
)
from pyjs.java import i32
from pyjs.java.collections import JavaList


class _SwapGuard:
    def __init__(self):
        self.target: object | None = None
        self.x = 0
        self.y = 0
        self.dx = 0
        self.dy = 0
        self.slop = 1

    def reset(self) -> None:
        self.target = None

    def record(self, target: object, start_x: int, start_y: int, x: int, y: int,
               horizontal: bool = True, vertical: bool = True) -> None:
        dx = x - start_x if horizontal else 0
        dy = y - start_y if vertical else 0
        if dx == 0 and dy == 0:
            self.reset()
            return
        self.target = target
        self.x = x
        self.y = y
        self.dx = dx
        self.dy = dy

    def allows(self, target: object, x: int, y: int) -> bool:
        if self.target is None or target is not self.target:
            return True
        dx = x - self.x
        dy = y - self.y
        # Either qualifying axis can select a swap, regardless of which
        # pointer displacement is larger. Ignore motion on unrelated axes.
        return ((self.dx > 0 and dx <= -self.slop)
                or (self.dx < 0 and dx >= self.slop)
                or (self.dy > 0 and dy <= -self.slop)
                or (self.dy < 0 and dy >= self.slop))


class StaggeredGridDragCallback(ItemTouchCallback):
    """Keep a completed swap from bouncing back during staggered relayout.

    Subclasses provide movement flags, on_move and on_swiped as with
    ItemTouchCallback. Preserve super calls when overriding selection,
    target selection or post-move hooks. Another swap with the same holder
    requires a touch-slop reversal along an axis that passed the target edge.
    Other targets still use native ItemTouchHelper selection immediately.
    """

    def __init__(self):
        super().__init__()
        self._swap_guard = _SwapGuard()

    def on_selected_changed(self, view_holder: RecyclerViewViewHolder | None,
                            action_state: i32) -> None:
        self._swap_guard.reset()
        if view_holder is not None:
            config = view_configuration(view_holder.item_view.getContext())
            self._swap_guard.slop = max(1, int(config.getScaledTouchSlop()))
        super().on_selected_changed(view_holder, action_state)

    def choose_drop_target(self, selected: RecyclerViewViewHolder,
                           targets: JavaList, x: i32, y: i32) -> RecyclerViewViewHolder | None:
        target = super().choose_drop_target(selected, targets, x, y)
        if target is not None and not self._swap_guard.allows(target, int(x), int(y)):
            return None
        return target

    def on_moved(self, recycler_view: RecyclerView,
                 view_holder: RecyclerViewViewHolder, from_position: i32,
                 target: RecyclerViewViewHolder, to_position: i32,
                 x: i32, y: i32) -> None:
        # on_move may reject a target; only this successful-move hook arms the
        # guard. Staggered layout can retain the old column after notifyItemMoved.
        view = view_holder.item_view
        other = target.item_view
        left, top = int(view.getLeft()), int(view.getTop())
        horizontal = ((x > left and other.getRight() > view.getRight()
                       and x + view.getWidth() > other.getRight())
                      or (x < left and other.getLeft() < left and x < other.getLeft()))
        vertical = ((y > top and other.getBottom() > view.getBottom()
                     and y + view.getHeight() > other.getBottom())
                    or (y < top and other.getTop() < top and y < other.getTop()))
        self._swap_guard.record(target, left, top, int(x), int(y), horizontal, vertical)
        super().on_moved(recycler_view, view_holder, from_position, target, to_position, x, y)
