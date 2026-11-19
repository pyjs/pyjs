from typing import cast

import pytest

from pyjs import jvm
from pyjs.android import TextView, View, ViewGroup
from pyjs.android.gestures import view_configuration
from pyjs.android.recyclerview import (
    ItemTouchCallback,
    ItemTouchHelper,
    RecyclerView,
    RecyclerViewAdapter,
    RecyclerViewLayoutParams,
    RecyclerViewViewHolder,
    StaggeredGridLayoutManager,
    StaggeredGridLayoutParams,
)
from pyjs.android.reorder import StaggeredGridDragCallback
from pyjs.android.testing import NoMatchingViewException, ViewAssertion, by_text, launch
from pyjs.java import i32
from pyjs.java.collections import JavaArrayList, JavaList

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


class ContinueForward(ViewAssertion):
    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert error is None and view is not None
        context = view.getContext()
        recycler = RecyclerView(context)
        recycler.set_layout_manager(StaggeredGridLayoutManager(2, 1))
        source = Holder(TextView(context))
        previous = Holder(TextView(context))
        following = Holder(TextView(context))
        source.item_view.layout(0, 200, 100, 300)
        previous.item_view.layout(0, 100, 100, 200)
        following.item_view.layout(0, 0, 100, 100)
        drag = Drag()
        drag.on_selected_changed(source, ItemTouchHelper.ACTION_STATE_DRAG)
        assert drag.choose_drop_target(source, candidate_list(previous), 0, 90) is previous
        drag.on_moved(recycler, source, 2, previous, 1, 0, 90)
        for reverse in [False, True]:
            candidates = JavaArrayList()
            candidates.add(following if reverse else previous)
            candidates.add(previous if reverse else following)
            native = NativeDrag()
            assert native.choose_drop_target(source, candidates, 0, -50) is previous
            assert drag.choose_drop_target(source, candidates, 0, -50) is following
            assert candidates.size() == 2
            assert candidates.get(0) is (following if reverse else previous)
            assert candidates.get(1) is (previous if reverse else following)


def test_guarded_partner_does_not_hide_another_forward_drop_target() -> None:
    launch(GreetingActivity)
    by_text("Hello from Python").check(ContinueForward())


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


@jvm.native("androidx/recyclerview/widget/RecyclerView")
class MeasuredGrid(RecyclerView):
    def measure(self, width: i32, height: i32) -> None: ...


class VariableCards(RecyclerViewAdapter):
    def __init__(self):
        super().__init__()
        self.ids: list[int] = []
        for index in range(80):
            self.ids.append(index)
        self.set_has_stable_ids(True)

    def get_item_count(self) -> i32:
        return i32(len(self.ids))

    def get_item_id(self, position: i32) -> int:
        return self.ids[position]

    def on_create_view_holder(self, parent: ViewGroup, kind: i32) -> RecyclerViewViewHolder:
        return Holder(TextView(parent.getContext()))

    def on_bind_view_holder(self, holder: RecyclerViewViewHolder, position: i32) -> None:
        number = self.ids[position]
        holder.item_view.setLayoutParams(StaggeredGridLayoutParams(-1, i32(80 + number % 5 * 40)))
        cast(TextView, holder.item_view).setText(str(number))

    def move(self, source: i32, destination: i32) -> None:
        value = self.ids.pop(source)
        self.ids.insert(destination, value)
        self.notify_item_moved(source, destination)


def layout_grid(grid: MeasuredGrid) -> None:
    # EXACTLY measure specs keep this real native layout independent of device size.
    grid.measure(0x40000000 | 720, 0x40000000 | 800)
    grid.layout(0, 0, 720, 800)


def holder_at(grid: RecyclerView, position: i32) -> RecyclerViewViewHolder:
    found: RecyclerViewViewHolder | None = None
    for index in range(grid.getChildCount()):
        holder = grid.getChildViewHolder(grid.getChildAt(i32(index)))
        if holder.get_binding_adapter_position() == position:
            found = holder
    assert found is not None, "Missing position " + str(position)
    return found


class ReplayNativeLayout(ViewAssertion):
    def check(self, view: View | None, error: NoMatchingViewException | None) -> None:
        assert view is not None and error is None
        for columns in [1, 2, 3, 4]:
            for start in [0, 20]:
                self.replay(view, columns, start)

    def replay(self, view: View, columns: int, start: int) -> None:
        grid = MeasuredGrid(view.getContext())
        manager = StaggeredGridLayoutManager(i32(columns), 1)
        adapter = VariableCards()
        grid.set_layout_manager(manager)
        grid.set_adapter(adapter)
        layout_grid(grid)
        manager.scroll_to_position_with_offset(i32(start), 0)
        layout_grid(grid)
        source = holder_at(grid, i32(start))
        before = source.item_view.getTop()
        destination = i32(start + columns * 3)
        target = holder_at(grid, destination)
        drag = Drag()
        drag.on_selected_changed(source, ItemTouchHelper.ACTION_STATE_DRAG)
        x, y = target.item_view.getLeft(), target.item_view.getBottom()
        adapter.move(i32(start), destination)
        drag.on_moved(grid, source, i32(start), target, destination, x, y)
        layout_grid(grid)
        assert source.get_binding_adapter_position() == destination
        assert source.item_view.getTop() > before + 80, str(columns) + " columns: source did not move"
        target = holder_at(grid, i32(start))
        adapter.move(destination, i32(start))
        drag.on_moved(grid, source, destination, target, i32(start), 0, before)
        layout_grid(grid)
        assert source.get_binding_adapter_position() == start
        assert source.item_view.getTop() == before, (str(columns) + " columns: return "
                                                    + str(source.item_view.getTop()) + " before " + str(before))


def test_adapter_moves_relayout_cards_instead_of_scrolling_the_viewport() -> None:
    launch(GreetingActivity)
    by_text("Hello from Python").check(ReplayNativeLayout())
