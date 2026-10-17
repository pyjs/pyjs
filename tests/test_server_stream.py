import asyncio
import threading

import pytest
from pydantic import BaseModel

from pyjs.server import (
    API,
    OperationResultError,
    Stream,
    StreamCursor,
    StreamEvent,
    StreamFeed,
    StreamHub,
    StreamResyncRequired,
    StreamSnapshot,
    dispatch_operation,
    resource_graph,
    stream,
)


class MessageHistory:
    def __init__(self, messages: list[str]):
        self.messages = messages
        self.calls: list[tuple[str, int]] = []

    async def load(self, scope: str, limit: int) -> list[str]:
        self.calls.append((scope, limit))
        return self.messages[-limit:]


def test_stream_feed_keeps_durable_history_independent_from_live_delivery():
    async def scenario():
        hub = StreamHub[str]()
        history = MessageHistory(["old", "current"])
        feed = StreamFeed(hub, history, "room:7")

        hub.publish("room:7", "already-live")
        snapshot = await feed.snapshot(1)
        event = feed.publish("new")
        binding = feed.events()

        assert snapshot == StreamSnapshot(value=["current"], sequence=1)
        assert history.calls == [("room:7", 1)]
        assert event == StreamEvent("room:7", 2, "new")
        assert binding.backend is hub
        assert binding.scope == "room:7"

    asyncio.run(scenario())


def test_stream_feed_reads_its_backend_off_the_event_loop():
    class RecordingHub(StreamHub[str]):
        def __init__(self):
            super().__init__()
            self.watermark_thread = None

        def watermark(self, scope: str) -> int:
            self.watermark_thread = threading.get_ident()
            return super().watermark(scope)

    async def scenario():
        event_loop_thread = threading.get_ident()
        hub = RecordingHub()
        feed = StreamFeed(hub, MessageHistory([]), "room:7")

        await feed.snapshot(1)

        assert hub.watermark_thread is not None
        assert hub.watermark_thread != event_loop_thread

    asyncio.run(scenario())


def test_stream_feed_replays_events_published_while_history_is_loading():
    class PublishingHistory:
        def __init__(self, hub: StreamHub[str]):
            self.hub = hub

        async def load(self, scope: str, _request: None) -> list[str]:
            self.hub.publish(scope, "during-snapshot")
            return ["durable-snapshot"]

    async def scenario():
        hub = StreamHub[str]()
        feed = StreamFeed(hub, PublishingHistory(hub), "room:7")

        snapshot = await feed.snapshot(None)
        subscription = feed.backend.subscribe(
            feed.scope,
            after=snapshot.sequence,
        )

        assert snapshot == StreamSnapshot(
            value=["durable-snapshot"],
            sequence=0,
        )
        assert subscription.receive_nowait() == StreamEvent(
            "room:7",
            1,
            "during-snapshot",
        )

    asyncio.run(scenario())


def test_stream_feed_requires_an_explicit_scope():
    with pytest.raises(ValueError, match=r"^A stream feed requires a scope\.$"):
        StreamFeed(StreamHub(), MessageHistory([]), "")


def test_stream_sequences_and_replay_are_isolated_by_scope():
    hub = StreamHub[str]()

    first_general = hub.publish("general", "hello")
    first_support = hub.publish("support", "help")
    second_general = hub.publish("general", "welcome")

    assert first_general.payload() == {
        "scope": "general",
        "sequence": 1,
        "type": "event",
        "value": "hello",
    }
    assert first_support.sequence == 1
    assert second_general.sequence == 2
    assert hub.watermark("general") == 2
    assert hub.watermark("support") == 1
    assert hub.replay("general", 0) == (first_general, second_general)
    assert hub.replay("support", 0) == (first_support,)


def test_subscribe_replays_then_receives_the_live_tail_without_a_race():
    hub = StreamHub[str]()
    first = hub.publish("general", "one")
    subscription = hub.subscribe("general", after=0)
    second = hub.publish("general", "two")

    assert subscription.sequence == 0
    assert subscription.receive_nowait() is first
    assert subscription.sequence == 1
    assert subscription.receive_nowait() is second
    assert subscription.sequence == 2
    assert subscription.empty() is True


def test_subscribe_without_a_cursor_starts_at_the_current_watermark():
    hub = StreamHub[str]()
    hub.publish("general", "history")
    subscription = hub.subscribe("general")

    assert subscription.sequence == 1
    current = hub.publish("general", "current")

    assert subscription.receive_nowait() is current


def test_replay_and_subscription_report_expired_or_invalid_cursors():
    hub = StreamHub[str](replay_limit=2)
    hub.publish("general", "one")
    second = hub.publish("general", "two")
    third = hub.publish("general", "three")

    assert hub.replay("general", 0) is None
    assert hub.replay("general", 1) == (second, third)
    assert hub.replay("general", 4) is None
    with pytest.raises(StreamResyncRequired) as caught:
        hub.subscribe("general", after=0)
    assert str(caught.value) == (
        "Stream 'general' cannot resume after sequence 0; "
        "available range is 2 through 3."
    )


def test_slow_subscriptions_fail_explicitly_instead_of_dropping_events():
    hub = StreamHub[str]()
    subscription = hub.subscribe("general", buffer_limit=2)
    hub.publish("general", "one")
    hub.publish("general", "two")
    hub.publish("general", "three")

    with pytest.raises(StreamResyncRequired) as caught:
        subscription.receive_nowait()
    assert caught.value.scope == "general"
    assert caught.value.after == 0
    assert subscription.empty() is True


def test_stream_cursor_ignores_duplicates_and_rejects_gaps_and_other_scopes():
    cursor = StreamCursor("general", after=2)

    assert cursor.accept(StreamEvent("general", 2, "duplicate")) is False
    assert cursor.accept(StreamEvent("general", 3, "next")) is True
    assert cursor.sequence == 3
    with pytest.raises(StreamResyncRequired):
        cursor.accept(StreamEvent("general", 5, "gap"))
    with pytest.raises(
        ValueError,
        match=r"^Expected stream scope 'general', got 'support'\.$",
    ):
        cursor.accept(StreamEvent("support", 4, "wrong"))


def test_stream_delivery_crosses_threads_into_an_async_subscriber():
    async def scenario():
        hub = StreamHub[str]()
        subscription = hub.subscribe("general")
        pending = asyncio.create_task(subscription.receive())
        await asyncio.sleep(0)

        publisher = threading.Thread(
            target=lambda: hub.publish("general", "hello")
        )
        publisher.start()
        publisher.join()

        event = await asyncio.wait_for(pending, 1)
        assert event.value == "hello"
        assert event.sequence == 1

    asyncio.run(scenario())


def test_stream_subscription_supports_async_iteration():
    async def scenario():
        hub = StreamHub[str]()
        subscription = hub.subscribe("general")
        hub.publish("general", "one")
        hub.publish("general", "two")

        values = []
        async for event in subscription:
            values.append(event.value)
            if len(values) == 2:
                subscription.close()

        assert values == ["one", "two"]

    asyncio.run(scenario())


def test_concurrent_stream_publishers_deliver_in_sequence_order():
    hub = StreamHub[str]()
    subscription = hub.subscribe("general")
    first_started = threading.Event()
    release_first = threading.Event()
    deliver = subscription._deliver

    def blocking_deliver(event):
        if event.sequence == 1:
            first_started.set()
            release_first.wait(1)
        deliver(event)

    subscription._deliver = blocking_deliver
    first = threading.Thread(target=lambda: hub.publish("general", "one"))
    second = threading.Thread(target=lambda: hub.publish("general", "two"))

    first.start()
    assert first_started.wait(1) is True
    try:
        second.start()
        second.join(0.05)
        assert second.is_alive() is True
        assert hub._sequences["general"] == 1
    finally:
        release_first.set()
    first.join()
    second.join()

    assert subscription.receive_nowait().value == "one"
    assert subscription.receive_nowait().value == "two"


def test_closing_a_stream_subscription_wakes_a_pending_receiver():
    async def scenario():
        hub = StreamHub[str]()
        subscription = hub.subscribe("general")
        pending = asyncio.create_task(subscription.receive())
        await asyncio.sleep(0)

        subscription.close()
        subscription.close()

        with pytest.raises(
            RuntimeError,
            match=r"^The stream subscription is closed\.$",
        ):
            await pending

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: StreamHub(replay_limit=-1), "replay limit cannot be negative"),
        (lambda: StreamHub().watermark(""), "requires a scope"),
        (
            lambda: StreamHub().subscribe("general", buffer_limit=0),
            "subscription buffer must be positive",
        ),
        (lambda: StreamCursor("general", -1), "cursor cannot be negative"),
    ],
)
def test_stream_configuration_rejects_invalid_bounds(call, message):
    with pytest.raises(ValueError, match=message):
        call()


class LogLine(BaseModel):
    sequence: int
    text: str


def test_stream_operations_bind_validated_arguments_to_a_typed_scope():
    hub = StreamHub[LogLine]()

    class LogsAPI(API):
        @stream
        def output(self, job_id: int) -> Stream[LogLine]:
            return Stream(hub, "job:" + str(job_id))

    binding = asyncio.run(
        dispatch_operation(
            LogsAPI,
            "output",
            {"job_id": "7"},
            serialize=False,
        )
    )
    operation = resource_graph(LogsAPI).operations_by_identity["output"]

    assert isinstance(binding, Stream)
    assert binding.backend is hub
    assert binding.scope == "job:7"
    assert operation.kind == "stream"
    assert operation.operation.stream_value_type is LogLine


def test_stream_operations_require_a_sync_typed_binding():
    with pytest.raises(
        TypeError,
        match=r"^@stream requires a synchronous function$",
    ):

        @stream
        async def asynchronous(self) -> Stream[str]:
            raise RuntimeError

    with pytest.raises(
        TypeError,
        match=r"must return Stream\[T\]\.$",
    ):

        @stream
        def untyped(self) -> str:
            return "logs"


def test_stream_operation_overrides_preserve_the_client_contract():
    class ClientLogsAPI(API):
        @stream
        def output(self, job_id: int) -> Stream[str]:
            raise RuntimeError

    with pytest.raises(
        TypeError,
        match=r"^Stream override AsyncLogsAPI\.output must be synchronous\.$",
    ):

        class AsyncLogsAPI(ClientLogsAPI):
            async def output(self, job_id: int) -> Stream[str]:
                raise RuntimeError

    with pytest.raises(
        TypeError,
        match=(
            r"^Operation override MismatchedLogsAPI\.output must preserve "
            r"its inherited signature\.$"
        ),
    ):

        class MismatchedLogsAPI(ClientLogsAPI):
            def output(self) -> Stream[str]:
                raise RuntimeError


def test_stream_operations_reject_a_runtime_value_that_is_not_a_stream():
    class LogsAPI(API):
        @stream
        def output(self) -> Stream[str]:
            return "logs"

    with pytest.raises(
        OperationResultError,
        match=r"^Stream operation 'output' did not return Stream\[T\]\.$",
    ):
        asyncio.run(
            dispatch_operation(
                LogsAPI,
                "output",
                {},
                serialize=False,
            )
        )


def test_stream_snapshot_validates_its_resume_sequence():
    snapshot = StreamSnapshot(value=["one", "two"], sequence=4)

    assert snapshot.value == ["one", "two"]
    assert snapshot.sequence == 4
    with pytest.raises(ValueError):
        StreamSnapshot(value=[], sequence=-1)


@pytest.mark.parametrize(
    ("scope", "options", "message"),
    (
        ("", {}, "A stream requires a scope."),
        ("logs", {"heartbeat": 0}, "The stream heartbeat must be positive."),
        (
            "logs",
            {"buffer_limit": 0},
            "The stream buffer limit must be positive.",
        ),
    ),
)
def test_stream_bindings_reject_invalid_configuration(scope, options, message):
    hub = StreamHub[str]()

    with pytest.raises(ValueError, match=f"^{message}$"):
        Stream(hub, scope, **options)
