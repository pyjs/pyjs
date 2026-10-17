import asyncio

import pytest

from pyjs.server import stream_client
from pyjs.server.stream_client import StreamMessage, StreamSession


def message(
    sequence: int,
    value: object,
    *,
    scope: str = "logs",
    event_type: str = "event",
) -> StreamMessage:
    return {
        "scope": scope,
        "sequence": sequence,
        "type": event_type,
        "value": value,
    }


def test_stream_session_decodes_ordered_values_and_ignores_duplicates():
    received = []
    session = StreamSession(
        "/streams/logs",
        lambda value: int(value),
        autostart=False,
    ).on_event(received.append)

    async def receive():
        await session._receive(message(4, "12"))
        await session._receive(message(4, "99"))
        await session._receive(message(5, "13"))

    asyncio.run(receive())

    assert received == [12, 13]
    assert session.scope == "logs"
    assert session.sequence == 5


def test_stream_session_reports_gaps_resyncs_and_scope_changes():
    received = []
    resyncs = []
    async def resync(sequence: int):
        resyncs.append(sequence)

    session = (
        StreamSession(
            "/streams/logs",
            lambda value: str(value),
            after=2,
            autostart=False,
        )
        .on_event(received.append)
        .on_resync(resync)
    )

    async def receive():
        await session._receive(message(4, "gap"))
        await session._receive(
            message(7, None, scope="logs", event_type="resync")
        )
        await session._receive(message(8, "wrong scope", scope="other"))

    asyncio.run(receive())

    assert received == []
    assert resyncs == [4, 7, 8]
    assert session.scope == "logs"
    assert session.sequence == 8
    assert session.status == "resync"


def test_stream_session_resumes_with_a_cursor_and_closes_cleanly(monkeypatch):
    class Source:
        def __init__(self, url):
            self.url = url
            self.listeners = {}
            self.closed = False

        def addEventListener(self, name, callback):
            self.listeners[name] = callback

        def close(self):
            self.closed = True

    monkeypatch.setattr(stream_client, "EventSource", Source)
    session = StreamSession(
        "/logs?scope=build",
        lambda value: str(value),
        after=7,
    )

    session.start()

    source = session._source
    assert source.url == "/logs?scope=build&after=7"
    assert set(source.listeners) == {"open", "event", "resync", "error"}
    assert session.status == "connecting"

    session.close()

    assert source.closed is True
    assert session._source is None
    assert session.status == "stopped"


def test_stream_session_distinguishes_live_tail_from_sequence_zero(monkeypatch):
    paths = []

    class Source:
        def __init__(self, url):
            paths.append(url)

        def addEventListener(self, name, callback):
            pass

        def close(self):
            pass

    monkeypatch.setattr(stream_client, "EventSource", Source)
    StreamSession("/logs", lambda value: value).start()
    StreamSession("/logs", lambda value: value, after=0).start()

    assert paths == ["/logs", "/logs?after=0"]


def test_stream_session_can_adopt_a_snapshot_cursor_before_start(monkeypatch):
    paths = []

    class Source:
        def __init__(self, url):
            paths.append(url)

        def addEventListener(self, name, callback):
            pass

        def close(self):
            pass

    monkeypatch.setattr(stream_client, "EventSource", Source)
    session = StreamSession("/logs", lambda value: value)

    assert session.resume_after(0) is session
    session.start()

    assert paths == ["/logs?after=0"]
    with pytest.raises(
        RuntimeError,
        match=r"^Close the stream before changing its cursor\.$",
    ):
        session.resume_after(2)


def test_stream_session_resync_can_adopt_a_new_snapshot_watermark(monkeypatch):
    paths = []

    class Source:
        def __init__(self, url):
            paths.append(url)

        def addEventListener(self, name, callback):
            pass

        def close(self):
            pass

    monkeypatch.setattr(stream_client, "EventSource", Source)
    session = StreamSession("/logs", lambda value: value, after=2)

    async def replace_snapshot(_expired_sequence: int):
        session.resume_after(9).start()

    session.on_resync(replace_snapshot).start()
    asyncio.run(session._receive(message(4, "gap")))

    assert paths == ["/logs?after=2", "/logs?after=9"]
    assert session.sequence == 9
    assert session.status == "connecting"


def test_stream_session_rejects_a_negative_cursor():
    with pytest.raises(
        ValueError,
        match=r"^A stream session cursor cannot be negative\.$",
    ):
        StreamSession("/logs", lambda value: value, after=-1)
