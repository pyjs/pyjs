import pytest

from pyjs.web.ssr import render_html
from pyjs.web.ui.streaming_log import StreamingLog


def lines(log: StreamingLog) -> list[str | None]:
    return [
        child.childNodes[0].textContent
        for child in log.scroller.content.children
        if len(child.childNodes) > 0
    ]


def test_streaming_log_converts_text_to_bounded_follow_tail_rows():
    log = StreamingLog("starting", "ready", max_lines=3)

    log.append_live("request one", "request two")

    assert lines(log) == ["ready", "request one", "request two"]
    assert log.getAttribute("data-slot") == "streaming-log"
    assert log.scroller.viewport.getAttribute("role") == "region"
    assert log.scroller.content.getAttribute("role") == "log"
    assert log.scroller.viewport.getAttribute("aria-label") == "Live log output"


def test_streaming_log_preserves_history_pause_and_wrapping():
    log = StreamingLog("current", max_lines=3, wrap=True)

    log.add_history("older")
    log.set_paused(True)
    log.append_live("waiting")

    assert lines(log) == ["older", "current"]
    assert log.status.textContent == "1 waiting"
    assert "whitespace-pre-wrap" in (
        log.scroller.content.children[0].getAttribute("class") or ""
    )
    assert "min-w-max" not in (
        log.scroller.content.children[0].getAttribute("class") or ""
    )

    log.set_paused(False)

    assert lines(log) == ["older", "current", "waiting"]


def test_streaming_log_escapes_untrusted_text_during_server_rendering():
    source = render_html(
        StreamingLog('<script>alert("log")</script>'),
    )

    assert "<script>" not in source
    assert '&lt;script&gt;alert("log")&lt;/script&gt;' in source


def test_streaming_log_requires_a_positive_retention_limit():
    with pytest.raises(
        ValueError,
        match=r"^A streaming list must retain at least one item\.$",
    ):
        StreamingLog(max_lines=0)
