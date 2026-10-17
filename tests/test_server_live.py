import asyncio
import threading

import pytest

from pyjs.server import InvalidationHub, api_topic, resource_topic


def test_invalidation_hub_delivers_each_event_once_per_subscription():
    hub = InvalidationHub()
    subscription = hub.subscribe("issues", "projects")

    invalidation = hub.publish("issues", "issues", "projects")

    assert subscription.receive_nowait() is invalidation
    assert subscription.empty() is True
    assert invalidation.payload() == {
        "sequence": 1,
        "topics": ["issues", "projects"],
        "type": "invalidate",
    }


def test_invalidation_hub_only_delivers_matching_topics():
    hub = InvalidationHub()
    issues = hub.subscribe("issues")
    projects = hub.subscribe("projects")

    hub.publish("issues")

    assert issues.receive_nowait().topics == ("issues",)
    assert projects.empty() is True


def test_closed_subscription_stops_receiving_invalidations():
    hub = InvalidationHub()
    subscription = hub.subscribe("issues")

    hub.publish("issues")
    subscription.close()
    subscription.close()
    hub.publish("issues")

    assert subscription.empty() is True

    async def receive():
        await subscription.receive()

    with pytest.raises(
        RuntimeError,
        match=r"^The invalidation subscription is closed\.$",
    ):
        asyncio.run(receive())


def test_closing_a_subscription_wakes_a_pending_receiver():
    async def scenario():
        hub = InvalidationHub()
        subscription = hub.subscribe("issues")
        pending = asyncio.create_task(subscription.receive())
        await asyncio.sleep(0)

        subscription.close()

        with pytest.raises(
            RuntimeError,
            match=r"^The invalidation subscription is closed\.$",
        ):
            await pending

    asyncio.run(scenario())


def test_slow_subscription_coalesces_pending_topics():
    hub = InvalidationHub()
    subscription = hub.subscribe("issues", "projects")

    hub.publish("issues")
    hub.publish("projects")
    hub.publish("issues")

    invalidation = subscription.receive_nowait()
    assert invalidation.sequence == 3
    assert invalidation.topics == ("issues", "projects")
    assert subscription.empty() is True


def test_invalidation_hub_replays_retained_matching_events():
    hub = InvalidationHub(replay_limit=2)
    first = hub.publish("issues")
    hub.publish("projects")

    assert hub.replay(0, "issues") == (first,)
    assert hub.replay(1, "issues") == ()
    assert hub.replay(2, "issues") == ()


def test_invalidation_hub_reports_when_a_cursor_is_outside_retained_history():
    hub = InvalidationHub(replay_limit=2)
    hub.publish("issues")
    second = hub.publish("issues")
    third = hub.publish("issues")

    assert hub.replay(0, "issues") is None
    assert hub.replay(1, "issues") == (second, third)
    assert hub.replay(4, "issues") is None


def test_invalidation_hub_can_disable_replay():
    hub = InvalidationHub(replay_limit=0)
    hub.publish("issues")

    assert hub.replay(0, "issues") is None

    with pytest.raises(
        ValueError,
        match=r"^The invalidation replay limit cannot be negative\.$",
    ):
        InvalidationHub(replay_limit=-1)


def test_invalidation_can_cross_threads_into_an_async_subscriber():
    async def scenario():
        hub = InvalidationHub()
        subscription = hub.subscribe("issues")
        pending = asyncio.create_task(subscription.receive())
        await asyncio.sleep(0)

        thread = threading.Thread(target=lambda: hub.publish("issues"))
        thread.start()
        thread.join()

        invalidation = await asyncio.wait_for(pending, 1)
        assert invalidation.sequence == 1
        assert invalidation.topics == ("issues",)

    asyncio.run(scenario())


def test_concurrent_publishers_deliver_in_sequence_order():
    hub = InvalidationHub()
    subscription = hub.subscribe("issues")
    first_started = threading.Event()
    release_first = threading.Event()
    deliver = subscription._deliver

    def blocking_deliver(invalidation):
        if invalidation.sequence == 1:
            first_started.set()
            release_first.wait(1)
        deliver(invalidation)

    subscription._deliver = blocking_deliver
    first = threading.Thread(target=lambda: hub.publish("issues"))
    second = threading.Thread(target=lambda: hub.publish("issues"))

    first.start()
    assert first_started.wait(1) is True
    try:
        second.start()
        second.join(0.05)
        assert second.is_alive() is True
        assert hub._sequence == 1
    finally:
        release_first.set()
    first.join()
    second.join()

    assert hub.sequence == 2
    assert subscription.receive_nowait().sequence == 2


def test_invalidation_hub_requires_topics():
    hub = InvalidationHub()

    with pytest.raises(
        ValueError,
        match=r"^An invalidation subscription requires a topic\.$",
    ):
        hub.subscribe()
    with pytest.raises(
        ValueError,
        match=r"^An invalidation requires a topic\.$",
    ):
        hub.publish()


def test_api_and_resource_topics_are_stable_and_distinct():
    class ExampleAPI:
        pass

    base = f"{__name__}.test_api_and_resource_topics_are_stable_and_distinct"
    expected_api = base + ".<locals>.ExampleAPI"

    assert api_topic(ExampleAPI) == expected_api
    assert api_topic(ExampleAPI()) == expected_api
    assert resource_topic(ExampleAPI, ("issues", "comments")) == (
        expected_api + ":issues.comments"
    )
