"""Generated Python declarations for the pinned AndroidX RecyclerView API."""

from typing import Annotated, ClassVar

from pyjs import jvm
from pyjs.android import Context, MarginLayoutParams, Parcelable, Rect, View, ViewGroup
from pyjs.java import JVMArray, f32, i32


@jvm.native("java/lang/Object")
class Object:
    pass


@jvm.native("androidx/recyclerview/widget/RecyclerView$ItemDecoration")
class RecyclerView_ItemDecoration(Object):
    pass


@jvm.native("androidx/recyclerview/widget/ItemTouchHelper")
class ItemTouchHelper(RecyclerView_ItemDecoration):
    ACTION_STATE_DRAG: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 2
    ACTION_STATE_IDLE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    ACTION_STATE_SWIPE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 1
    UP: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 1
    DOWN: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 2
    START: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 16
    END: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 32
    LEFT: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 4
    RIGHT: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 8

    def __init__(self, callback: ItemTouchCallback) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/ItemTouchHelper",
        name="attachToRecyclerView",
        invocation="virtual",
    )
    def attach_to_recycler_view(self, recycler_view: RecyclerView | None) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/ItemTouchHelper",
        name="startDrag",
        invocation="virtual",
    )
    def start_drag(self, view_holder: RecyclerViewViewHolder) -> None:
        pass


@jvm.native("androidx/recyclerview/widget/ItemTouchHelper$Callback")
class ItemTouchCallback(Object):
    def __init__(self) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/ItemTouchHelper$Callback",
        name="getMovementFlags",
        invocation="virtual",
    )
    def get_movement_flags(
        self,
        recycler_view: RecyclerView,
        view_holder: RecyclerViewViewHolder,
    ) -> i32:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/ItemTouchHelper$Callback",
        name="onMove",
        invocation="virtual",
    )
    def on_move(
        self,
        recycler_view: RecyclerView,
        view_holder: RecyclerViewViewHolder,
        target: RecyclerViewViewHolder,
    ) -> bool:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/ItemTouchHelper$Callback",
        name="onSwiped",
        invocation="virtual",
    )
    def on_swiped(
        self,
        view_holder: RecyclerViewViewHolder,
        direction: i32,
    ) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/ItemTouchHelper$Callback",
        name="onSelectedChanged",
        invocation="virtual",
    )
    def on_selected_changed(
        self,
        view_holder: RecyclerViewViewHolder | None,
        action_state: i32,
    ) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/ItemTouchHelper$Callback",
        name="isLongPressDragEnabled",
        invocation="virtual",
    )
    def is_long_press_drag_enabled(self) -> bool:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/ItemTouchHelper$Callback",
        name="isItemViewSwipeEnabled",
        invocation="virtual",
    )
    def is_item_view_swipe_enabled(self) -> bool:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/ItemTouchHelper$Callback",
        name="getMoveThreshold",
        invocation="virtual",
    )
    def get_move_threshold(self, view_holder: RecyclerViewViewHolder) -> f32:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/ItemTouchHelper$Callback",
        name="getSwipeThreshold",
        invocation="virtual",
    )
    def get_swipe_threshold(self, view_holder: RecyclerViewViewHolder) -> f32:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/ItemTouchHelper$Callback",
        name="canDropOver",
        invocation="virtual",
    )
    def can_drop_over(
        self,
        recycler_view: RecyclerView,
        current: RecyclerViewViewHolder,
        target: RecyclerViewViewHolder,
    ) -> bool:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/ItemTouchHelper$Callback",
        name="clearView",
        invocation="virtual",
    )
    def clear_view(
        self,
        recycler_view: RecyclerView,
        view_holder: RecyclerViewViewHolder,
    ) -> None:
        pass


@jvm.native("androidx/recyclerview/widget/RecyclerView")
class RecyclerView(ViewGroup):
    def __init__(self, context: Context) -> None:
        pass

    def getChildViewHolder(self, child: View) -> RecyclerViewViewHolder: ...

    def getDecoratedBoundsWithMargins(self, child: View, bounds: Rect) -> None: ...

    def isAnimating(self) -> bool: ...

    def hasPendingAdapterUpdates(self) -> bool: ...

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView",
        name="setAdapter",
        invocation="virtual",
    )
    def set_adapter(self, adapter: RecyclerViewAdapter) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView",
        name="getAdapter",
        invocation="virtual",
    )
    def get_adapter(self) -> RecyclerViewAdapter | None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView",
        name="setLayoutManager",
        invocation="virtual",
    )
    def set_layout_manager(self, layout: RecyclerViewLayoutManager) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView",
        name="setHasFixedSize",
        invocation="virtual",
    )
    def set_has_fixed_size(self, has_fixed_size: bool) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView",
        name="scrollToPosition",
        invocation="virtual",
    )
    def scroll_to_position(self, position: i32) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView",
        name="smoothScrollToPosition",
        invocation="virtual",
    )
    def smooth_scroll_to_position(self, position: i32) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView",
        name="suppressLayout",
        invocation="virtual",
    )
    def suppress_layout(self, suppress: bool) -> None:
        pass


@jvm.native("androidx/recyclerview/widget/RecyclerView$Adapter")
class RecyclerViewAdapter(Object):
    def __init__(self) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        name="onCreateViewHolder",
        invocation="virtual",
    )
    def on_create_view_holder(
        self,
        parent: ViewGroup,
        view_type: i32,
    ) -> RecyclerViewViewHolder:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        name="onBindViewHolder",
        invocation="virtual",
    )
    def on_bind_view_holder(
        self,
        holder: RecyclerViewViewHolder,
        position: i32,
    ) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        name="getItemCount",
        invocation="virtual",
    )
    def get_item_count(self) -> i32:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        name="getItemId",
        invocation="virtual",
    )
    def get_item_id(self, position: i32) -> int:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        name="getItemViewType",
        invocation="virtual",
    )
    def get_item_view_type(self, position: i32) -> i32:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        name="setHasStableIds",
        invocation="virtual",
    )
    def set_has_stable_ids(self, has_stable_ids: bool) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        name="hasStableIds",
        invocation="virtual",
    )
    def has_stable_ids(self) -> bool:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        name="notifyItemChanged",
        invocation="virtual",
    )
    def notify_item_changed(self, position: i32) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        name="notifyItemMoved",
        invocation="virtual",
    )
    def notify_item_moved(self, from_position: i32, to_position: i32) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        name="notifyItemInserted",
        invocation="virtual",
    )
    def notify_item_inserted(self, position: i32) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        name="notifyItemRemoved",
        invocation="virtual",
    )
    def notify_item_removed(self, position: i32) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        name="notifyItemRangeChanged",
        invocation="virtual",
    )
    def notify_item_range_changed(self, start: i32, count: i32) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        name="notifyItemRangeInserted",
        invocation="virtual",
    )
    def notify_item_range_inserted(self, start: i32, count: i32) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        name="notifyItemRangeRemoved",
        invocation="virtual",
    )
    def notify_item_range_removed(self, start: i32, count: i32) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$Adapter",
        name="notifyDataSetChanged",
        invocation="virtual",
    )
    def notify_data_set_changed(self) -> None:
        pass


@jvm.native("androidx/recyclerview/widget/RecyclerView$LayoutManager")
class RecyclerViewLayoutManager(Object):
    pass


@jvm.native("androidx/recyclerview/widget/RecyclerView$LayoutParams")
class RecyclerViewLayoutParams(MarginLayoutParams):
    def __init__(self, width: i32, height: i32) -> None:
        pass


@jvm.native("androidx/recyclerview/widget/StaggeredGridLayoutManager$LayoutParams")
class StaggeredGridLayoutParams(RecyclerViewLayoutParams):
    INVALID_SPAN_ID: ClassVar[
        Annotated[i32, jvm.field(writable=False)]
    ] = -1

    def __init__(self, width: i32, height: i32) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager$LayoutParams",
        name="setFullSpan",
        invocation="virtual",
    )
    def set_full_span(self, full_span: bool) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager$LayoutParams",
        name="isFullSpan",
        invocation="virtual",
    )
    def is_full_span(self) -> bool:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager$LayoutParams",
        name="getSpanIndex",
        invocation="virtual",
    )
    def get_span_index(self) -> i32:
        pass


@jvm.native("androidx/recyclerview/widget/RecyclerView$ViewHolder")
class RecyclerViewViewHolder(Object):
    item_view: Annotated[
        View,
        jvm.field(name="itemView", writable=False),
    ]

    def __init__(self, item_view: View) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$ViewHolder",
        name="getBindingAdapterPosition",
        invocation="virtual",
    )
    def get_binding_adapter_position(self) -> i32:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$ViewHolder",
        name="getAbsoluteAdapterPosition",
        invocation="virtual",
    )
    def get_absolute_adapter_position(self) -> i32:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$ViewHolder",
        name="getItemId",
        invocation="virtual",
    )
    def get_item_id(self) -> int:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$ViewHolder",
        name="getLayoutPosition",
        invocation="virtual",
    )
    def get_layout_position(self) -> i32:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/RecyclerView$ViewHolder",
        name="getOldPosition",
        invocation="virtual",
    )
    def get_old_position(self) -> i32:
        pass


@jvm.native("androidx/recyclerview/widget/StaggeredGridLayoutManager")
class StaggeredGridLayoutManager(RecyclerViewLayoutManager):
    GAP_HANDLING_NONE: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    GAP_HANDLING_LAZY: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 1
    GAP_HANDLING_MOVE_ITEMS_BETWEEN_SPANS: ClassVar[
        Annotated[i32, jvm.field(writable=False)]
    ] = 2
    HORIZONTAL: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 0
    VERTICAL: ClassVar[Annotated[i32, jvm.field(writable=False)]] = 1

    def __init__(self, span_count: i32, orientation: i32) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager",
        name="getGapStrategy",
        invocation="virtual",
    )
    def get_gap_strategy(self) -> i32:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager",
        name="getReverseLayout",
        invocation="virtual",
    )
    def get_reverse_layout(self) -> bool:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager",
        name="getSpanCount",
        invocation="virtual",
    )
    def get_span_count(self) -> i32:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager",
        name="findFirstVisibleItemPositions",
        invocation="virtual",
    )
    def find_first_visible_item_positions(
        self,
        into: JVMArray[i32] | None,
    ) -> JVMArray[i32]:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager",
        name="findLastVisibleItemPositions",
        invocation="virtual",
    )
    def find_last_visible_item_positions(
        self,
        into: JVMArray[i32] | None,
    ) -> JVMArray[i32]:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager",
        name="findFirstCompletelyVisibleItemPositions",
        invocation="virtual",
    )
    def find_first_completely_visible_item_positions(
        self,
        into: JVMArray[i32] | None,
    ) -> JVMArray[i32]:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager",
        name="findLastCompletelyVisibleItemPositions",
        invocation="virtual",
    )
    def find_last_completely_visible_item_positions(
        self,
        into: JVMArray[i32] | None,
    ) -> JVMArray[i32]:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager",
        name="onSaveInstanceState",
        invocation="virtual",
    )
    def on_save_instance_state(self) -> Parcelable | None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager",
        name="onRestoreInstanceState",
        invocation="virtual",
    )
    def on_restore_instance_state(self, state: Parcelable | None) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager",
        name="invalidateSpanAssignments",
        invocation="virtual",
    )
    def invalidate_span_assignments(self) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager",
        name="scrollToPositionWithOffset",
        invocation="virtual",
    )
    def scroll_to_position_with_offset(
        self,
        position: i32,
        offset: i32,
    ) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager",
        name="setGapStrategy",
        invocation="virtual",
    )
    def set_gap_strategy(self, strategy: i32) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager",
        name="setReverseLayout",
        invocation="virtual",
    )
    def set_reverse_layout(self, reverse: bool) -> None:
        pass

    @jvm.native(
        "androidx/recyclerview/widget/StaggeredGridLayoutManager",
        name="setSpanCount",
        invocation="virtual",
    )
    def set_span_count(self, span_count: i32) -> None:
        pass


@jvm.native(
    "androidx/recyclerview/widget/ItemTouchHelper$Callback",
    name="makeMovementFlags",
)
def make_movement_flags(drag_flags: i32, swipe_flags: i32) -> i32:
    pass


__all__ = [
    "ItemTouchCallback",
    "ItemTouchHelper",
    "RecyclerView",
    "RecyclerViewAdapter",
    "RecyclerViewLayoutManager",
    "RecyclerViewLayoutParams",
    "RecyclerViewViewHolder",
    "StaggeredGridLayoutManager",
    "StaggeredGridLayoutParams",
    "make_movement_flags",
]
