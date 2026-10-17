from pyjs.web.domx import div
from pyjs.web.ui.streaming_list import StreamingList


def row(value: str):
    return div({"data-row": value}, value)


def values(stream: StreamingList) -> list[str | None]:
    return [
        child.getAttribute("data-row")
        for child in stream.scroller.item_elements()
    ]


def test_streaming_list_bounds_live_rows_and_flushes_its_pause_queue():
    stream = StreamingList(row("one"), row("two"), max_items=3)

    stream.set_paused(True)
    stream.append_live(row("three"), row("four"), row("five"), row("six"))

    assert values(stream) == ["one", "two"]
    assert stream.status.textContent == "3 waiting, 1 dropped"
    assert stream.pause_button.textContent == "Resume"
    assert stream.pause_button.getAttribute("aria-pressed") == "true"

    stream.set_paused(False)

    assert values(stream) == ["four", "five", "six"]
    assert stream.status.textContent == "Live, 1 dropped"
    assert stream.pause_button.textContent == "Pause"
    assert stream.pause_button.getAttribute("aria-pressed") == "false"


def test_streaming_list_adds_history_and_keeps_the_newest_bound():
    stream = StreamingList(row("three"), row("four"), max_items=4)

    stream.add_history(row("one"), row("two"))
    assert values(stream) == ["one", "two", "three", "four"]

    stream.append_live(row("five"), row("six"))
    assert values(stream) == ["three", "four", "five", "six"]

    stream.clear()
    assert values(stream) == []
    assert stream.status.textContent == "Live"


def test_newest_first_streams_prepend_live_rows_and_append_history():
    stream = StreamingList(
        row("four"),
        row("three"),
        newest_first=True,
        max_items=4,
    )

    stream.append_live(row("five"), row("six"))
    stream.add_history(row("two"), row("one"))

    assert values(stream) == ["six", "five", "four", "three"]
    assert stream.scroller.scroll_button.getAttribute("data-direction") == "start"


def test_streaming_list_requires_a_positive_retained_bound():
    try:
        StreamingList(max_items=0)
    except ValueError as error:
        assert str(error) == "A streaming list must retain at least one item."
    else:
        raise AssertionError("A zero retained bound was accepted.")
