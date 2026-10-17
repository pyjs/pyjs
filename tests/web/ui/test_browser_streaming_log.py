import pytest

from pyjs import js
from pyjs.web.ui.streaming_log import StreamingLog
from tests.web.ui.browser import bubbling_click, mount, require_element

pytestmark = pytest.mark.pyjs_web


@js
def test_streaming_log_follows_pauses_and_flushes_live_lines():
    log = StreamingLog("booting", "ready", max_lines=3)
    log.setAttribute("style", "height: 140px")
    mount(log)

    log.append_live("request one", "request two")

    assert log.querySelectorAll("[data-slot=streaming-log-line]").length == 3
    assert require_element(log, "[data-slot=streaming-log-line]").textContent == (
        "ready"
    )

    bubbling_click(log.pause_button)
    log.append_live("waiting one", "waiting two", "waiting three", "waiting four")

    assert log.status.textContent == "3 waiting, 1 dropped"
    assert log.querySelectorAll("[data-slot=streaming-log-line]").length == 3

    bubbling_click(log.pause_button)

    rows = log.querySelectorAll("[data-slot=streaming-log-line]")
    assert rows.length == 3
    assert rows[0].textContent == "waiting two"
    assert rows[2].textContent == "waiting four"
    assert log.status.textContent == "Live, 1 dropped"

    log.replace("recovered snapshot")

    assert log.status.textContent == "Live"
    assert log.dropped_count == 0


@js
def test_streaming_log_wrap_mode_allows_rows_to_shrink():
    log = StreamingLog("a long log line", wrap=True)
    mount(log)

    row = require_element(log, "[data-slot=streaming-log-line]")

    assert row.classList.contains("whitespace-pre-wrap")
    assert row.classList.contains("min-w-0")
    assert not row.classList.contains("min-w-max")
