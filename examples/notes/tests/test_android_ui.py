from typing import cast

import pytest
from pyjs import JS
from pyjs.android import View
from pyjs.android.recycler_testing import StaggeredGridSnapshot
from pyjs.android.recyclerview import RecyclerView
from pyjs.android.testing import (
    NoMatchingViewException,
    ViewAssertion,
    by_id,
    by_text,
    launch,
)
from pyjs.android.uiautomator import find_text
from pyjs_examples.notes.android import NotesActivity

pytestmark = [
    pytest.mark.pyjs_android_jvm,
    pytest.mark.pyjs_android_dependencies("androidx"),
]

LAUNCH_NOTE: JS = (
    "Launch checklist\n\n✓ Review the final build\n"
    "☐ Capture store screenshots\n☐ Publish the release notes"
)
WEEKEND_NOTE: JS = (
    "Weekend ideas\n\nWalk the river trail\nTry the new bakery\nCall Maya"
)


class NoteOrder(ViewAssertion):
    def __init__(self, expected: list[int]) -> None:
        self.expected = expected

    def check(
        self, view: View | None, error: NoMatchingViewException | None,
    ) -> None:
        assert error is None
        assert view is not None
        adapter = cast(RecyclerView, view).get_adapter()
        assert adapter is not None, "Notes grid has no adapter"
        if adapter is not None:
            assert adapter.get_item_count() == len(self.expected)
            for index in range(len(self.expected)):
                actual = adapter.get_item_id(index)
                expected = self.expected[index]
                assert actual == expected, (
                    f"Card {index}: expected ID {expected}, got {actual}"
                )
        snapshot = StaggeredGridSnapshot(cast(RecyclerView, view))
        assert snapshot.stable_ids
        assert not snapshot.pending_updates
        assert len(snapshot.children) > 0
        for child in snapshot.children:
            assert child.adapter_position >= 0
            assert child.item_id == self.expected[child.adapter_position]
            assert child.right > child.left and child.bottom > child.top


def test_grid_displays_sample_cards_in_adapter_order() -> None:
    launch(NotesActivity)
    by_id(100).assert_displayed()
    by_id(100).check(NoteOrder([1001, 1002, 1003, 1004, 1005, 1006, 1007]))
    by_text(LAUNCH_NOTE).assert_displayed()
    by_text(WEEKEND_NOTE).assert_displayed()


@pytest.mark.pyjs_android_device
def test_long_press_drag_reorders_cards_and_can_move_them_back() -> None:
    launch(NotesActivity)
    # ItemTouchHelper requires crossing the target edge, not just aligning it.
    find_text(LAUNCH_NOTE).drag_to(find_text(WEEKEND_NOTE), 1_000, 32, 0)

    by_id(100).check(NoteOrder([1002, 1001, 1003, 1004, 1005, 1006, 1007]))
    by_text(LAUNCH_NOTE).assert_displayed()
    by_text(WEEKEND_NOTE).assert_displayed()

    find_text(LAUNCH_NOTE).drag_to(find_text(WEEKEND_NOTE), 1_000, -32, 0)

    by_id(100).check(NoteOrder([1001, 1002, 1003, 1004, 1005, 1006, 1007]))
    by_text(LAUNCH_NOTE).assert_displayed()
    by_text(WEEKEND_NOTE).assert_displayed()
