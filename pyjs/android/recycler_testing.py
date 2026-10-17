"""Native staggered-grid measurements for synchronized view assertions."""

from typing import cast

from pyjs import jvm
from pyjs.android import Rect
from pyjs.android.recyclerview import RecyclerView, StaggeredGridLayoutParams


@jvm.native("java/lang/Double", name="toString")
def _double_string(value: float) -> str:
    return str(value)


def _json_float(value: float) -> str:
    # Java's finite Double spelling is valid JSON, not Python float formatting.
    if value != value or value > 1.7976931348623157e308 or value < -1.7976931348623157e308:
        raise ValueError("Snapshot translations must be finite")
    return _double_string(value)


class RecyclerChildSnapshot:
    def __init__(self, recycler: RecyclerView, index: int) -> None:
        child = recycler.getChildAt(index)
        holder = recycler.getChildViewHolder(child)
        params = cast(StaggeredGridLayoutParams, child.getLayoutParams())
        bounds = Rect()
        recycler.getDecoratedBoundsWithMargins(child, bounds)
        self.item_id = holder.get_item_id()
        self.adapter_position = holder.get_binding_adapter_position()
        self.layout_position = holder.get_layout_position()
        self.span = params.get_span_index()
        self.full_span = params.is_full_span()
        self.left = child.getLeft()
        self.top = child.getTop()
        self.right = child.getRight()
        self.bottom = child.getBottom()
        self.decorated_left = bounds.left
        self.decorated_top = bounds.top
        self.decorated_right = bounds.right
        self.decorated_bottom = bounds.bottom
        self.translation_x = float(child.getTranslationX())
        self.translation_y = float(child.getTranslationY())

    def to_json(self) -> str:
        return (
            '{"id":"' + str(self.item_id) + '","adapter_position":'
            + str(self.adapter_position) + ',"layout_position":' + str(self.layout_position)
            + ',"span":' + str(self.span) + ',"full_span":'
            + ('true' if self.full_span else 'false')
            + ',"bounds":[' + str(self.left) + ',' + str(self.top) + ','
            + str(self.right) + ',' + str(self.bottom) + '],"decorated_bounds":['
            + str(self.decorated_left) + ',' + str(self.decorated_top) + ','
            + str(self.decorated_right) + ',' + str(self.decorated_bottom)
            + '],"translation":[' + _json_float(self.translation_x) + ','
            + _json_float(self.translation_y) + ']}'
        )


class StaggeredGridSnapshot:
    """Capture exposed attached children, without clipping or forcing layout.

    Call on the UI thread with a StaggeredGridLayoutManager. Bounds are local
    to the RecyclerView, in pixels. Translation is separate from layout.
    Pending/animating snapshots may have stale positions or duplicate IDs;
    unattached items and RecyclerView's hidden animation children are absent.
    """

    def __init__(self, recycler: RecyclerView) -> None:
        self.width = recycler.getWidth()
        self.height = recycler.getHeight()
        self.animating = recycler.isAnimating()
        self.pending_updates = recycler.hasPendingAdapterUpdates()
        adapter = recycler.get_adapter()
        self.stable_ids = adapter is not None and adapter.has_stable_ids()
        self.order: list[int] = []
        if adapter is not None:
            for index in range(adapter.get_item_count()):
                self.order.append(adapter.get_item_id(index))
        self.children: list[RecyclerChildSnapshot] = []
        for index in range(recycler.getChildCount()):
            self.children.append(RecyclerChildSnapshot(recycler, index))

    def to_json(self) -> str:
        """Export numeric geometry and IDs without note text or view references."""
        children: list[str] = []
        order: list[str] = []
        for child in self.children:
            children.append(child.to_json())
        for item_id in self.order:
            order.append('"' + str(item_id) + '"')
        return (
            '{"version":1,"coordinates":"recycler-local-pixels","width":'
            + str(self.width) + ',"height":' + str(self.height)
            + ',"animating":' + ('true' if self.animating else 'false')
            + ',"pending_updates":' + ('true' if self.pending_updates else 'false')
            + ',"stable_ids":' + ('true' if self.stable_ids else 'false')
            + ',"order":[' + ','.join(order) + '],"children":['
            + ','.join(children) + ']}'
        )
