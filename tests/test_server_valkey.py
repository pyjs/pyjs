import asyncio
import json
from dataclasses import dataclass, field

import pytest

from pyjs.server import StreamEvent, StreamResyncRequired, ValkeyStreamBackend
from pyjs.server.valkey import PUBLISH_SCRIPT, _response_entries


@dataclass
class FakeValkeyState:
    values: dict[str, int] = field(default_factory=dict)
    streams: dict[str, list[tuple[bytes, dict[bytes, bytes]]]] = field(
        default_factory=dict
    )
    signals: dict[str, asyncio.Event] = field(default_factory=dict)


class FakeValkeyClient:
    def __init__(self, state: FakeValkeyState):
        self.state = state
        self.evaluations: list[tuple[str, int, tuple[object, ...]]] = []

    def eval(self, script: str, numkeys: int, *values: object) -> int:
        self.evaluations.append((script, numkeys, values))
        sequence_key, stream_key, replay_limit, encoded = values
        assert isinstance(sequence_key, str)
        assert isinstance(stream_key, str)
        assert isinstance(replay_limit, int)
        assert isinstance(encoded, str | bytes)
        sequence = self.state.values.get(sequence_key, 0) + 1
        self.state.values[sequence_key] = sequence
        encoded_bytes = encoded.encode() if isinstance(encoded, str) else encoded
        entries = self.state.streams.setdefault(stream_key, [])
        entries.append(
            (str(sequence).encode() + b"-0", {b"value": encoded_bytes})
        )
        del entries[:-replay_limit]
        self.state.signals.setdefault(stream_key, asyncio.Event()).set()
        return sequence

    def get(self, key: str) -> bytes | None:
        value = self.state.values.get(key)
        return None if value is None else str(value).encode()

    def xrange(
        self,
        key: str,
        minimum: str,
        maximum: str,
        *,
        count: int | None = None,
    ):
        after = -1
        if minimum.startswith("("):
            after = int(minimum[1:].split("-", 1)[0])
        latest = None if maximum == "+" else int(maximum.split("-", 1)[0])
        values = [
            entry
            for entry in self.state.streams.get(key, ())
            if int(entry[0].split(b"-", 1)[0]) > after
            and (
                latest is None
                or int(entry[0].split(b"-", 1)[0]) <= latest
            )
        ]
        return values if count is None else values[:count]


class FakeAsyncValkeyClient:
    def __init__(self, state: FakeValkeyState):
        self.state = state

    async def xread(
        self,
        streams: dict[str, str],
        *,
        count: int | None = None,
        block: int | None = None,
    ):
        key, entry_id = next(iter(streams.items()))
        signal = self.state.signals.setdefault(key, asyncio.Event())
        while True:
            signal.clear()
            after = int(entry_id.split("-", 1)[0])
            entries = [
                entry
                for entry in self.state.streams.get(key, ())
                if int(entry[0].split(b"-", 1)[0]) > after
            ]
            if entries:
                return [(key.encode(), entries[:count])]
            try:
                await asyncio.wait_for(signal.wait(), (block or 1000) / 1000)
            except TimeoutError:
                return []


def backend(
    state: FakeValkeyState,
    *,
    replay_limit: int = 3,
) -> ValkeyStreamBackend[dict[str, object]]:
    return ValkeyStreamBackend(
        FakeValkeyClient(state),
        FakeAsyncValkeyClient(state),
        encode=lambda value: json.dumps(value, separators=(",", ":")),
        decode=json.loads,
        replay_limit=replay_limit,
        read_block_milliseconds=10,
    )


def test_valkey_backend_publishes_and_replays_typed_values_by_scope():
    state = FakeValkeyState()
    streams = backend(state)

    first = streams.publish("build:7", {"line": "one"})
    second = streams.publish("build:7", {"line": "two"})
    other = streams.publish("build:8", {"line": "other"})

    assert first == StreamEvent("build:7", 1, {"line": "one"})
    assert second.sequence == 2
    assert other.sequence == 1
    assert streams.watermark("build:7") == 2
    assert streams.replay("build:7", 0) == (
        first,
        StreamEvent("build:7", 2, {"line": "two"}),
    )
    evaluation = streams.client.evaluations[0]
    assert evaluation[0] == PUBLISH_SCRIPT
    assert evaluation[1] == 2
    assert "{" in evaluation[2][0]
    assert evaluation[2][0].split(":")[-2] == evaluation[2][1].split(":")[-2]


def test_valkey_subscriptions_fan_out_across_backend_instances():
    async def scenario():
        state = FakeValkeyState()
        publisher = backend(state)
        first = backend(state)
        second = backend(state)
        first_subscription = first.subscribe("build:7")
        second_subscription = second.subscribe("build:7")

        first_pending = asyncio.create_task(first_subscription.receive())
        second_pending = asyncio.create_task(second_subscription.receive())
        await asyncio.sleep(0)
        event = publisher.publish("build:7", {"line": "ready"})

        assert await asyncio.wait_for(first_pending, 1) == event
        assert await asyncio.wait_for(second_pending, 1) == event

    asyncio.run(scenario())


def test_valkey_subscription_replays_before_following_the_live_tail():
    async def scenario():
        state = FakeValkeyState()
        streams = backend(state)
        first = streams.publish("build:7", {"line": "one"})
        subscription = streams.subscribe("build:7", after=0)
        second = streams.publish("build:7", {"line": "two"})

        assert await subscription.receive() == first
        assert await subscription.receive() == second
        assert subscription.sequence == 2

    asyncio.run(scenario())


def test_valkey_backend_requires_resync_after_retained_history_expires():
    state = FakeValkeyState()
    streams = backend(state, replay_limit=2)
    streams.publish("build:7", {"line": "one"})
    streams.publish("build:7", {"line": "two"})
    streams.publish("build:7", {"line": "three"})

    assert streams.replay("build:7", 0) is None
    with pytest.raises(StreamResyncRequired) as caught:
        streams.subscribe("build:7", after=0)
    assert caught.value.after == 0
    assert caught.value.oldest == 2
    assert caught.value.latest == 3


def test_valkey_replay_stops_at_its_captured_watermark():
    state = FakeValkeyState()
    streams = backend(state)
    first = streams.publish("build:7", {"line": "one"})
    original_xrange = streams.client.xrange

    def publish_during_replay(*args, **kwargs):
        streams.publish("build:7", {"line": "two"})
        return original_xrange(*args, **kwargs)

    streams.client.xrange = publish_during_replay

    assert streams.replay("build:7", 0) == (first,)
    assert streams.watermark("build:7") == 2


def test_slow_valkey_subscriptions_report_a_gap_instead_of_dropping_values():
    async def scenario():
        state = FakeValkeyState()
        streams = backend(state, replay_limit=2)
        subscription = streams.subscribe("build:7")
        streams.publish("build:7", {"line": "one"})
        streams.publish("build:7", {"line": "two"})
        streams.publish("build:7", {"line": "three"})

        with pytest.raises(StreamResyncRequired) as caught:
            await subscription.receive()
        assert caught.value.after == 0
        assert caught.value.oldest == 2
        assert caught.value.latest == 3

    asyncio.run(scenario())


def test_valkey_backend_encodes_before_mutating_the_stream():
    state = FakeValkeyState()

    def reject(_value: object) -> bytes:
        raise ValueError("invalid event")

    streams = ValkeyStreamBackend(
        FakeValkeyClient(state),
        FakeAsyncValkeyClient(state),
        encode=reject,
        decode=lambda value: value,
    )

    with pytest.raises(ValueError, match="invalid event"):
        streams.publish("build:7", object())
    assert streams.watermark("build:7") == 0
    assert state.streams == {}


def test_malformed_retained_values_require_resync_instead_of_reconnecting():
    async def scenario():
        state = FakeValkeyState()
        streams = backend(state)
        subscription = streams.subscribe("build:7")
        streams.client.eval(
            PUBLISH_SCRIPT,
            2,
            streams._sequence_key("build:7"),
            streams._stream_key("build:7"),
            streams.replay_limit,
            b"invalid JSON",
        )

        with pytest.raises(StreamResyncRequired) as live_error:
            await subscription.receive()
        assert live_error.value.latest == 1

        with pytest.raises(StreamResyncRequired) as replay_error:
            streams.subscribe("build:7", after=0)
        assert replay_error.value.latest == 1

    asyncio.run(scenario())


def test_valkey_backend_accepts_decoded_and_flat_stream_responses():
    state = FakeValkeyState()
    streams = backend(state)

    assert streams._decode_entries(
        "build:7",
        (
            ("1-0", {"value": '{"line":"one"}'}),
            ("2-0", ("value", '{"line":"two"}')),
        ),
    ) == (
        StreamEvent("build:7", 1, {"line": "one"}),
        StreamEvent("build:7", 2, {"line": "two"}),
    )

    assert _response_entries(
        {"build": {"3-0": {"value": '{"line":"three"}'}}}
    ) == [("3-0", {"value": '{"line":"three"}'})]


def test_valkey_subscription_closes_async_iteration_cleanly():
    async def scenario():
        state = FakeValkeyState()
        subscription = backend(state).subscribe("build:7")
        subscription.close()

        with pytest.raises(StopAsyncIteration):
            await anext(subscription)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"key_prefix": ""}, "key prefix cannot be empty"),
        ({"key_prefix": ":"}, "key prefix cannot be empty"),
        ({"replay_limit": 0}, "replay limit must be positive"),
        ({"read_block_milliseconds": 0}, "read block must be positive"),
    ],
)
def test_valkey_backend_rejects_invalid_configuration(arguments, message):
    state = FakeValkeyState()
    with pytest.raises(ValueError, match=message):
        ValkeyStreamBackend(
            FakeValkeyClient(state),
            FakeAsyncValkeyClient(state),
            encode=str,
            decode=str,
            **arguments,
        )
