import pytest

from pyjs import js
from pyjs.web.events import KeyboardEvent
from pyjs.web.ui.message_scroller import MessageScroller
from tests.web.ui.browser import bubbling_click, mount
from tests.web.ui.scroller import constrain_scroller, dispatch_wheel, tall_item

pytestmark = pytest.mark.pyjs_web


@js
def test_message_scroller_opens_at_end_and_shows_jump_when_reader_leaves():
    scroller = MessageScroller(
        tall_item("First", 80),
        tall_item("Second", 80),
        tall_item("Third", 80),
        auto_scroll=True,
    )
    constrain_scroller(scroller, 90)
    mount(scroller)

    assert scroller.getAttribute("data-pending-scroll") is None
    assert scroller.is_at_latest()
    assert scroller.scroll_button.getAttribute("data-active") == "false"

    scroller.viewport.scrollTop = 0
    scroller.update_scroll_button()
    assert not scroller.is_at_latest()
    assert scroller.scroll_button.getAttribute("data-active") == "true"

    bubbling_click(scroller.scroll_button)
    assert scroller.is_at_latest()
    assert scroller.mode == "following-bottom"


@js
def test_message_scroller_wheel_releases_follow_and_preserves_append():
    scroller = MessageScroller(
        tall_item("First", 80),
        tall_item("Second", 80),
        auto_scroll=True,
    )
    constrain_scroller(scroller, 90)
    mount(scroller)
    scroller.scroll_to_latest()
    assert scroller.mode == "following-bottom"

    dispatch_wheel(scroller, -40)
    assert scroller.mode == "free-scrolling"

    previous = scroller.viewport.scrollTop
    scroller.append_messages(tall_item("Third", 80, message_id="m3"))
    assert scroller.mode == "free-scrolling"
    assert scroller.viewport.scrollTop == previous
    assert not scroller.is_at_latest()


@js
def test_message_scroller_keyboard_releases_follow():
    scroller = MessageScroller(
        tall_item("First", 80),
        tall_item("Second", 80),
        auto_scroll=True,
    )
    constrain_scroller(scroller, 90)
    mount(scroller)
    scroller.scroll_to_latest()
    scroller.viewport.dispatchEvent(
        KeyboardEvent("keydown", key="ArrowUp", bubbles=True, cancelable=True)
    )
    assert scroller.mode == "free-scrolling"


@js
def test_message_scroller_anchors_new_turns_near_the_top():
    scroller = MessageScroller(
        tall_item("Earlier", 80, message_id="m0"),
        auto_scroll=True,
    )
    constrain_scroller(scroller, 120)
    mount(scroller)
    scroller.scroll_to_latest()

    user = tall_item("Question", 40, scroll_anchor=True, message_id="user-1")
    scroller.append_messages(user)
    assert scroller.mode == "anchored-to-message"
    anchored = scroller._anchored_item()
    if anchored is None:
        raise RuntimeError("expected anchored item")
    assert anchored.getAttribute("data-message-id") == "user-1"
    assert scroller.viewport.scrollTop >= 0


@js
def test_message_scroller_last_anchor_restore_and_scroll_to_message():
    first = tall_item("One", 80, message_id="one")
    user = tall_item("Two", 40, scroll_anchor=True, message_id="user")
    reply = tall_item("Three", 80, message_id="reply")
    scroller = MessageScroller(
        first,
        user,
        reply,
        auto_scroll=True,
        default_scroll_position="last-anchor",
    )
    constrain_scroller(scroller, 100)
    mount(scroller)

    assert scroller.getAttribute("data-pending-scroll") is None
    assert scroller.scroll_to_message("one")
    assert scroller.mode == "free-scrolling"
    assert scroller.viewport.scrollTop >= 0


@js
def test_message_scroller_prepend_preserves_visible_offset():
    first = tall_item("Live", 40, message_id="live")
    scroller = MessageScroller(first, auto_scroll=True)
    constrain_scroller(scroller, 80)
    mount(scroller)
    scroller.viewport.scrollTop = 0
    previous = first.getBoundingClientRect().top
    scroller.prepend_messages(tall_item("History", 40, message_id="old"))
    assert abs(first.getBoundingClientRect().top - previous) < 2


@js
def test_reader_scroll_during_programmatic_guard_survives_resize():
    scroller = MessageScroller(tall_item("A", 160), tall_item("B", 160), auto_scroll=True)
    constrain_scroller(scroller, 90)
    mount(scroller)
    scroller.scroll_to_latest()
    assert scroller.autoscrolling
    scroller.viewport.scrollTop = 0
    # A resize can run before the browser dispatches the pending scroll event.
    scroller.content_resized(None, None)
    assert scroller.mode == "free-scrolling"
    assert scroller.viewport.scrollTop == 0


@js
def test_message_scroller_replace_follows_only_at_the_live_edge():
    scroller = MessageScroller(
        tall_item("A", 80),
        tall_item("B", 80),
        auto_scroll=True,
    )
    constrain_scroller(scroller, 90)
    mount(scroller)
    scroller.scroll_to_latest()
    dispatch_wheel(scroller, -80)
    scroller.viewport.scrollTop = 0
    scroller._set_mode("free-scrolling")
    previous = scroller.viewport.scrollTop
    scroller.replace_messages(tall_item("C", 80), tall_item("D", 80), tall_item("E", 80))
    assert scroller.viewport.scrollTop == previous
    assert not scroller.is_at_latest()
