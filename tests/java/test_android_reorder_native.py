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
        # The target was to the left, not above: vertical wobble cannot return it.
        for y in [-40 + drag._swap_guard.slop, 0]:
            assert native.choose_drop_target(source, candidates, -10, i32(y)) is target
            assert drag.choose_drop_target(source, candidates, -10, i32(y)) is None
        source.item_view.layout(12, 12, 528, 421)
        target.item_view.layout(552, 12, 1068, 309)
        assert drag.choose_drop_target(source, candidates, 560, 12) is target
        drag.on_selected_changed(None, ItemTouchHelper.ACTION_STATE_IDLE)
        assert drag._swap_guard.target is None
        assert drag.choose_drop_target(source, candidates, 560, 12) is target


def test_relayout_keeps_the_swap_but_allows_a_deliberate_return() -> None:
    launch(GreetingActivity)
    by_text("Hello from Python").check(ReplayRelayout())


class ReplayDiagonalReturn(ViewAssertion):
    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        context = view.getContext()
        recycler = RecyclerView(context)
        recycler.set_layout_manager(StaggeredGridLayoutManager(2, 1))
        source = Holder(TextView(context))
        target = Holder(TextView(context))
        source.item_view.layout(12, 12, 528, 112)
        target.item_view.layout(12, 124, 528, 424)
        candidates = candidate_list(target)
        drag = Drag()
        drag.on_selected_changed(source, ItemTouchHelper.ACTION_STATE_DRAG)
        # AndroidX selects the lower card vertically despite greater x offset.
        assert drag.choose_drop_target(source, candidates, 400, 330) is target
        drag.on_moved(recycler, source, 0, target, 1, 400, 330)
        target.item_view.layout(12, 12, 528, 312)
        source.item_view.layout(12, 324, 528, 424)
        native = NativeDrag()
        for x in [400, 420]:
            assert native.choose_drop_target(source, candidates, i32(x), -100) is target
            assert drag.choose_drop_target(source, candidates, i32(x), -100) is target

        # A genuinely diagonal target permits a return on either target axis.
        source.item_view.layout(0, 0, 100, 100)
        target.item_view.layout(112, 112, 212, 212)
        drag.on_selected_changed(source, ItemTouchHelper.ACTION_STATE_DRAG)
        assert drag.choose_drop_target(source, candidates, 130, 130) is target
        drag.on_moved(recycler, source, 0, target, 1, 130, 130)
        source.item_view.layout(112, 112, 212, 212)
        target.item_view.layout(0, 0, 100, 100)
        assert native.choose_drop_target(source, candidates, -20, 130) is target
        assert drag.choose_drop_target(source, candidates, -20, 130) is target
        assert native.choose_drop_target(source, candidates, 130, -20) is target
        assert drag.choose_drop_target(source, candidates, 130, -20) is target


def test_diagonal_swap_allows_a_straight_vertical_return() -> None:
    launch(GreetingActivity)
    by_text("Hello from Python").check(ReplayDiagonalReturn())


class ReplayHorizontalNoise(ViewAssertion):
    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        context = view.getContext()
        recycler = RecyclerView(context)
        recycler.set_layout_manager(StaggeredGridLayoutManager(2, 1))
        source = Holder(TextView(context))
        target = Holder(TextView(context))
        source.item_view.layout(12, 12, 528, 112)
        target.item_view.layout(12, 124, 528, 424)
        candidates = candidate_list(target)
        native = NativeDrag()
        for x in [14, 400]:
            drag = Drag()
            drag.on_selected_changed(source, ItemTouchHelper.ACTION_STATE_DRAG)
            assert drag.choose_drop_target(source, candidates, i32(x), 330) is target
            drag.on_moved(recycler, source, 0, target, 1, i32(x), 330)
            returning_x = i32(x - drag._swap_guard.slop)
            assert native.choose_drop_target(source, candidates, returning_x, 340) is target
            assert drag.choose_drop_target(source, candidates, returning_x, 340) is None


def test_vertical_swap_ignores_unrelated_horizontal_reversal() -> None:
    launch(GreetingActivity)
    by_text("Hello from Python").check(ReplayHorizontalNoise())


class ReplayStaggeredOffsets(ViewAssertion):
    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        context = view.getContext()
        recycler = RecyclerView(context)
        recycler.set_layout_manager(StaggeredGridLayoutManager(2, 1))
        source = Holder(TextView(context))
        target = Holder(TextView(context))
        candidates = candidate_list(target)
        native = NativeDrag()
        for y in [195, 205, 150, 250]:
            source.item_view.layout(0, 200, 100, 500)
            target.item_view.layout(112, 150, 212, 550)
            drag = Drag()
            drag.on_selected_changed(source, ItemTouchHelper.ACTION_STATE_DRAG)
            # The taller neighboring card extends above and below the source.
            # Only the horizontal dragged edge passes it; equality is not past.
            assert drag.choose_drop_target(source, candidates, 130, i32(y)) is target
            drag.on_moved(recycler, source, 0, target, 1, 130, i32(y))
            reverse_y = y + drag._swap_guard.slop if y < 200 else y - drag._swap_guard.slop
            assert native.choose_drop_target(source, candidates, 130, i32(reverse_y)) is target
            assert drag.choose_drop_target(source, candidates, 130, i32(reverse_y)) is None
            source.item_view.layout(112, 200, 212, 500)
            target.item_view.layout(0, 150, 100, 550)
            assert native.choose_drop_target(source, candidates, -20, i32(y)) is target
            assert drag.choose_drop_target(source, candidates, -20, i32(y)) is target


def test_staggered_swap_ignores_reversal_on_an_uncrossed_axis() -> None:
    launch(GreetingActivity)
    by_text("Hello from Python").check(ReplayStaggeredOffsets())
