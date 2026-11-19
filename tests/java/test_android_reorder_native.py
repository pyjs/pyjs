import pytest

from pyjs import jvm
from pyjs.android import TextView, View
from pyjs.android.gestures import view_configuration
from pyjs.android.recyclerview import (
    ItemTouchCallback,
    ItemTouchHelper,
    RecyclerView,
    RecyclerViewLayoutParams,
    RecyclerViewViewHolder,
    StaggeredGridLayoutManager,
)
from pyjs.android.reorder import StaggeredGridDragCallback
from pyjs.android.testing import NoMatchingViewException, ViewAssertion, by_text, launch
from pyjs.java import i32
from pyjs.java.collections import JavaList

from .android_robolectric_app import GreetingActivity

pytestmark = [pytest.mark.pyjs_android_jvm,
              pytest.mark.pyjs_android_dependencies("androidx")]


@jvm.native("java/util/Collections", name="singletonList")
def candidate_list(value: object) -> JavaList: ...


class Holder(RecyclerViewViewHolder):
    def __init__(self, view: TextView):
        super().__init__(view)
        self.item_view.setLayoutParams(RecyclerViewLayoutParams(516, 409))


class Drag(StaggeredGridDragCallback):
    def __init__(self):
        super().__init__()

    def get_movement_flags(self, recycler: RecyclerView, holder: RecyclerViewViewHolder) -> i32:
        return i32(0)

    def on_move(self, recycler: RecyclerView, source: RecyclerViewViewHolder,
                target: RecyclerViewViewHolder) -> bool:
        return True

    def on_swiped(self, holder: RecyclerViewViewHolder, direction: i32) -> None:
        pass


class NativeDrag(ItemTouchCallback):
    def __init__(self):
        super().__init__()

    def get_movement_flags(self, recycler: RecyclerView, holder: RecyclerViewViewHolder) -> i32:
        return i32(0)

    def on_move(self, recycler: RecyclerView, source: RecyclerViewViewHolder,
                target: RecyclerViewViewHolder) -> bool:
        return True

    def on_swiped(self, holder: RecyclerViewViewHolder, direction: i32) -> None:
        pass


class ReplayRelayout(ViewAssertion):
    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        context = view.getContext()
        recycler = RecyclerView(context)
        recycler.set_layout_manager(StaggeredGridLayoutManager(2, 1))
        source = Holder(TextView(context))
        target = Holder(TextView(context))
        source.item_view.layout(552, 12, 1068, 421)
        target.item_view.layout(12, 12, 528, 309)
        candidates = candidate_list(target)
        drag = Drag()
        drag.on_selected_changed(source, ItemTouchHelper.ACTION_STATE_DRAG)
        assert drag._swap_guard.slop == int(view_configuration(context).getScaledTouchSlop())
        assert drag.choose_drop_target(source, candidates, 0, -40) is target
        # Selection alone must not arm the guard when on_move rejects the move.
        assert drag.choose_drop_target(source, candidates, 0, -40) is target
        drag.on_moved(recycler, source, 1, target, 0, 0, -40)
        source.item_view.layout(552, -68, 1068, 341)
        target.item_view.layout(12, 13, 528, 310)
        native = NativeDrag()
        assert native.choose_drop_target(source, candidates, -10, -42) is target
        assert drag.choose_drop_target(source, candidates, -10, -42) is None
        source.item_view.layout(12, 12, 528, 421)
        target.item_view.layout(552, 12, 1068, 309)
        assert drag.choose_drop_target(source, candidates, 560, 12) is target
        drag.on_selected_changed(None, ItemTouchHelper.ACTION_STATE_IDLE)
        assert drag._swap_guard.target is None
        assert drag.choose_drop_target(source, candidates, 560, 12) is target


def test_relayout_keeps_the_swap_but_allows_a_deliberate_return() -> None:
    launch(GreetingActivity)
    by_text("Hello from Python").check(ReplayRelayout())
