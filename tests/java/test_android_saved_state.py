import pytest

from pyjs.android import Bundle, Runnable, View
from pyjs.android.controls import ScrollView
from pyjs.android.testing import application_context, run_on_main, saved_state_size

pytestmark = pytest.mark.pyjs_android_jvm


def test_saved_state_size_counts_native_bytes_without_changing_the_bundle() -> None:
    state = Bundle()
    empty = saved_state_size(state)
    state.put_string("text", "a" * 1000)
    ascii_size = saved_state_size(state)
    assert ascii_size > empty + 2000
    assert state.get_string("text") == "a" * 1000
    state.put_string("text", "😀" * 1000)
    emoji_size = saved_state_size(state)
    assert emoji_size == ascii_size + 2000
    assert state.get_string("text") == "😀" * 1000
    nested = Bundle()
    nested.put_bundle("pending", state)
    assert saved_state_size(nested) > emoji_size
    assert saved_state_size(state) == emoji_size


def set_offset(view: View) -> None:
    view.scroll_to(12, 34)


class ScrollOffsets(Runnable):
    def run(self) -> None:
        view = View(application_context())
        set_offset(view)
        assert view.getScrollX() == 12 and view.getScrollY() == 34
        scroll = ScrollView(application_context())
        set_offset(scroll)
        assert scroll.getScrollX() == 0 and scroll.getScrollY() == 0


def test_view_scroll_offsets_dispatch_to_native_subclasses() -> None:
    run_on_main(ScrollOffsets())
