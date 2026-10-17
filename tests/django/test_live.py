import asyncio
import json

import pytest
from django.db import transaction
from django.test import RequestFactory
from pydantic import BaseModel

from pyjs.server import API, InvalidationHub, Resource, api_topic, mutation, query
from pyjs.server.django import live as django_live
from pyjs.server.django import publish_after_commit, urls_for
from pyjs.server.live import resource_topic


class Note(BaseModel):
    id: int
    title: str


class NoteResource(Resource[Note]):
    @query
    async def get(self, identifier: int) -> Note:
        return Note(id=identifier, title="Read invalidations")

    @query
    async def viewer(self) -> str:
        return self.request.headers.get("X-Viewer", "anonymous")

    @query
    async def broken(self) -> str:
        raise ValueError("live query failed")

    @query
    async def invalid_result(self) -> Note:
        return {"title": "Missing an ID"}

    @mutation
    async def save(self, note: Note) -> Note:
        return note

    @mutation
    async def fail(self, note: Note) -> Note:
        raise ValueError("save failed")


class LiveAPI(API):
    notes: NoteResource


def operation_pattern(patterns, name):
    return next(pattern for pattern in patterns if pattern.callback.__name__ == name)


def named_pattern(patterns, name):
    return next(pattern for pattern in patterns if pattern.name == name)


def call(pattern, payload):
    request = RequestFactory().post(
        "/api/" + str(pattern.pattern),
        data=json.dumps(payload),
        content_type="application/json",
    )
    return asyncio.run(pattern.callback(request))


def test_publish_after_commit_defers_and_coalesces_topics():
    hub = InvalidationHub()
    subscription = hub.subscribe("notes", "all")

    with transaction.atomic():
        publish_after_commit(hub, ("notes", "notes", "all"))
        assert subscription.empty() is True

    invalidation = subscription.receive_nowait()
    assert invalidation.topics == ("notes", "all")
    assert subscription.empty() is True


def test_publish_after_commit_emits_nothing_after_rollback():
    hub = InvalidationHub()
    subscription = hub.subscribe("notes")

    with pytest.raises(RuntimeError, match="rollback"):
        with transaction.atomic():
            publish_after_commit(hub, ("notes",))
            raise RuntimeError("rollback")

    assert subscription.empty() is True


def test_successful_mutation_invalidates_the_api_and_resource():
    hub = InvalidationHub()
    topics = (
        api_topic(LiveAPI),
        resource_topic(LiveAPI, ("notes",)),
    )
    subscription = hub.subscribe(*topics)
    pattern = operation_pattern(urls_for(LiveAPI(), hub), "notes_save")

    response = call(
        pattern,
        {"note": {"id": 1, "title": "Publish after commit"}},
    )

    assert response.status_code == 200
    assert subscription.receive_nowait().topics == topics
    assert subscription.empty() is True


def test_separate_django_adapters_share_a_replaceable_backend():
    class TestBackend:
        def __init__(self, shared):
            self.shared = shared

        @property
        def sequence(self):
            return self.shared.sequence

        def subscribe(self, *topics):
            return self.shared.subscribe(*topics)

        def publish(self, *topics):
            return self.shared.publish(*topics)

    async def scenario():
        shared = InvalidationHub()
        reader = TestBackend(shared)
        writer = TestBackend(shared)
        poll = named_pattern(
            urls_for(LiveAPI(), reader),
            "pyjs_live_poll",
        )
        pending = asyncio.create_task(
            poll.callback(RequestFactory().get("/api/_live/poll"))
        )
        await asyncio.sleep(0)

        save = operation_pattern(urls_for(LiveAPI(), writer), "notes_save")
        response = await save.callback(
            RequestFactory().post(
                "/api/notes/save",
                data=json.dumps(
                    {"note": {"id": 1, "title": "Cross adapters"}}
                ),
                content_type="application/json",
            )
        )
        live_response = await pending

        assert response.status_code == 200
        assert json.loads(live_response.content) == {
            "sequence": 1,
            "topics": ["*", "notes"],
            "type": "invalidate",
        }

    asyncio.run(scenario())


def test_queries_and_failed_mutations_do_not_publish_invalidations():
    hub = InvalidationHub()
    subscription = hub.subscribe(api_topic(LiveAPI))
    patterns = urls_for(LiveAPI(), hub)

    query_response = call(
        operation_pattern(patterns, "notes_get"),
        {"identifier": 1},
    )
    failure_response = call(
        operation_pattern(patterns, "notes_fail"),
        {"note": {"id": 1, "title": "Do not publish"}},
    )

    assert query_response.status_code == 200
    assert failure_response.status_code == 500
    assert json.loads(failure_response.content) == {
        "errors": [
            {
                "code": "server_error",
                "detail": "The server could not complete the operation.",
                "status": "500",
                "title": "Server error",
            }
        ]
    }
    assert subscription.empty() is True


def test_sse_stream_uses_the_shared_invalidation_payload():
    async def scenario():
        hub = InvalidationHub()
        patterns = urls_for(LiveAPI(), hub)
        pattern = named_pattern(patterns, "pyjs_live_events")
        request = RequestFactory().get("/api/_live/events")
        response = await pattern.callback(request)
        stream = response.streaming_content

        assert response.status_code == 200
        assert response["Content-Type"] == "text/event-stream"
        assert response["Cache-Control"] == "no-cache, no-store, no-transform"
        assert response["X-Accel-Buffering"] == "no"
        assert response["Vary"] == "Cookie"
        assert await anext(stream) == b"retry: 3000\n\n"

        save = operation_pattern(patterns, "notes_save")
        save_request = RequestFactory().post(
            "/api/notes/save",
            data=json.dumps(
                {"note": {"id": 1, "title": "Send through SSE"}}
            ),
            content_type="application/json",
        )
        save_response = await save.callback(save_request)

        assert save_response.status_code == 200
        assert await anext(stream) == (
            b'id: 1\nevent: invalidate\ndata: {"sequence":1,"topics":'
            b'["*","notes"],"type":"invalidate"}\n\n'
        )
        await stream.aclose()

    asyncio.run(scenario())


def test_sse_stream_includes_registered_typed_query_results():
    async def scenario():
        hub = InvalidationHub()
        patterns = urls_for(LiveAPI(), hub)
        subscribe = named_pattern(patterns, "pyjs_live_subscribe")
        subscribe_request = RequestFactory().post(
            "/api/_live/subscribe",
            data=json.dumps(
                {
                    "queries": [
                        {
                            "arguments": {"identifier": 3},
                            "generation": 4,
                            "id": 1,
                            "operation": "notes.get",
                            "topics": ["notes"],
                        },
                        {
                            "arguments": {},
                            "generation": 2,
                            "id": 2,
                            "operation": "notes.viewer",
                            "topics": ["viewers"],
                        },
                    ],
                    "subscription": "",
                }
            ),
            content_type="application/json",
        )
        subscribe_response = await subscribe.callback(subscribe_request)
        token = json.loads(subscribe_response.content)["subscription"]

        events = named_pattern(patterns, "pyjs_live_events")
        event_request = RequestFactory().get(
            "/api/_live/events",
            {"subscription": token},
            headers={"X-Viewer": "Ada"},
        )
        event_response = await events.callback(event_request)
        stream = event_response.streaming_content
        assert await anext(stream) == b"retry: 3000\n\n"

        hub.publish(
            api_topic(LiveAPI),
            resource_topic(LiveAPI, ("notes",)),
        )

        assert await anext(stream) == (
            b'id: 1\nevent: result\ndata: {"results":[{"generation":4,'
            b'"id":1,"value":{"data":{"type":"notes","id":"3",'
            b'"attributes":{"title":"Read invalidations"}}}},'
            b'{"generation":2,"id":2,"value":"Ada"}],'
            b'"sequence":1,"topics":["*","notes"],"type":"result"}\n\n'
        )
        await stream.aclose()

    asyncio.run(scenario())


def test_unknown_live_subscription_retains_invalidation_delivery():
    async def scenario():
        hub = InvalidationHub()
        patterns = urls_for(LiveAPI(), hub)
        events = named_pattern(patterns, "pyjs_live_events")
        request = RequestFactory().get(
            "/api/_live/events",
            {"subscription": "unknown"},
        )
        response = await events.callback(request)
        stream = response.streaming_content
        assert await anext(stream) == b"retry: 3000\n\n"

        hub.publish(api_topic(LiveAPI))

        assert await anext(stream) == (
            b'id: 1\nevent: invalidate\ndata: {"sequence":1,"topics":'
            b'["*"],"type":"invalidate"}\n\n'
        )
        await stream.aclose()

    asyncio.run(scenario())


def test_failed_registered_query_falls_back_to_invalidation():
    async def scenario():
        hub = InvalidationHub()
        patterns = urls_for(LiveAPI(), hub)
        subscribe = named_pattern(patterns, "pyjs_live_subscribe")
        response = await subscribe.callback(
            RequestFactory().post(
                "/api/_live/subscribe",
                data=json.dumps(
                    {
                        "queries": [
                            {
                                "arguments": {},
                                "generation": 0,
                                "id": 1,
                                "operation": "notes.broken",
                                "topics": ["*"],
                            }
                        ],
                        "subscription": "",
                    }
                ),
                content_type="application/json",
            )
        )
        token = json.loads(response.content)["subscription"]
        events = named_pattern(patterns, "pyjs_live_events")
        event_response = await events.callback(
            RequestFactory().get(
                "/api/_live/events",
                {"subscription": token},
            )
        )
        stream = event_response.streaming_content
        assert await anext(stream) == b"retry: 3000\n\n"

        hub.publish(api_topic(LiveAPI))

        assert await anext(stream) == (
            b'id: 1\nevent: invalidate\ndata: {"sequence":1,"topics":'
            b'["*"],"type":"invalidate"}\n\n'
        )
        await stream.aclose()

    asyncio.run(scenario())


def test_sse_cursor_replays_a_retained_invalidation():
    async def scenario():
        hub = InvalidationHub()
        hub.publish(api_topic(LiveAPI))
        pattern = named_pattern(urls_for(LiveAPI(), hub), "pyjs_live_events")
        request = RequestFactory().get(
            "/api/_live/events",
            headers={"Last-Event-ID": "0"},
        )
        response = await pattern.callback(request)
        stream = response.streaming_content

        assert await anext(stream) == b"retry: 3000\n\n"
        assert await anext(stream) == (
            b'id: 1\nevent: invalidate\ndata: {"sequence":1,"topics":'
            b'["*"],"type":"invalidate"}\n\n'
        )
        await stream.aclose()

    asyncio.run(scenario())


def test_sse_cursor_requests_resync_when_replay_is_unavailable():
    async def scenario():
        hub = InvalidationHub(replay_limit=0)
        hub.publish(api_topic(LiveAPI))
        pattern = named_pattern(urls_for(LiveAPI(), hub), "pyjs_live_events")
        request = RequestFactory().get(
            "/api/_live/events",
            headers={"Last-Event-ID": "0"},
        )
        response = await pattern.callback(request)
        stream = response.streaming_content

        assert await anext(stream) == b"retry: 3000\n\n"
        assert await anext(stream) == (
            b'id: 1\nevent: resync\ndata: {"sequence":1,"topics":'
            b'["*"],"type":"resync"}\n\n'
        )
        await stream.aclose()

    asyncio.run(scenario())


def test_long_poll_returns_the_same_invalidation_payload():
    async def scenario():
        hub = InvalidationHub()
        pattern = named_pattern(urls_for(LiveAPI(), hub), "pyjs_live_poll")
        request = RequestFactory().get("/api/_live/poll")
        pending = asyncio.create_task(pattern.callback(request))
        await asyncio.sleep(0)

        hub.publish(api_topic(LiveAPI))
        response = await pending

        assert response.status_code == 200
        assert response["Cache-Control"] == "no-cache, no-store"
        assert response["Vary"] == "Cookie"
        assert json.loads(response.content) == {
            "sequence": 1,
            "topics": ["*"],
            "type": "invalidate",
        }

    asyncio.run(scenario())


def test_long_poll_times_out_without_an_event(monkeypatch):
    monkeypatch.setattr(django_live, "LONG_POLL_SECONDS", 0.001)
    hub = InvalidationHub()
    pattern = named_pattern(urls_for(LiveAPI(), hub), "pyjs_live_poll")
    request = RequestFactory().get("/api/_live/poll")

    response = asyncio.run(pattern.callback(request))

    assert response.status_code == 204
    assert response["Cache-Control"] == "no-cache, no-store"
    assert response["Vary"] == "Cookie"


def test_long_poll_cursor_replays_a_retained_invalidation():
    hub = InvalidationHub()
    hub.publish(api_topic(LiveAPI))
    pattern = named_pattern(urls_for(LiveAPI(), hub), "pyjs_live_poll")
    request = RequestFactory().get("/api/_live/poll", {"after": "0"})

    response = asyncio.run(pattern.callback(request))

    assert response.status_code == 200
    assert json.loads(response.content) == {
        "sequence": 1,
        "topics": ["*"],
        "type": "invalidate",
    }


def test_long_poll_cursor_requests_resync_when_replay_is_unavailable():
    hub = InvalidationHub(replay_limit=0)
    hub.publish(api_topic(LiveAPI))
    pattern = named_pattern(urls_for(LiveAPI(), hub), "pyjs_live_poll")
    request = RequestFactory().get("/api/_live/poll", {"after": "0"})

    response = asyncio.run(pattern.callback(request))

    assert response.status_code == 200
    assert json.loads(response.content) == {
        "sequence": 1,
        "topics": ["*"],
        "type": "resync",
    }


def test_live_refresh_batches_typed_query_results():
    pattern = named_pattern(
        urls_for(LiveAPI(), InvalidationHub()),
        "pyjs_live_refresh",
    )
    request = RequestFactory().post(
        "/api/_live/refresh",
        data=json.dumps(
            {
                "queries": [
                    {
                        "arguments": {"identifier": 3},
                        "generation": 4,
                        "id": 1,
                        "operation": "notes.get",
                    },
                    {
                        "arguments": {"identifier": 7},
                        "generation": 9,
                        "id": 2,
                        "operation": "notes.get",
                    },
                    {
                        "arguments": {},
                        "generation": 2,
                        "id": 3,
                        "operation": "notes.viewer",
                    },
                ]
            }
        ),
        content_type="application/json",
        headers={"X-Viewer": "Ada"},
    )

    response = asyncio.run(pattern.callback(request))

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-cache, no-store"
    assert response["Vary"] == "Cookie"
    assert json.loads(response.content) == {
        "results": [
            {
                "generation": 4,
                "id": 1,
                "value": {
                    "data": {
                        "attributes": {"title": "Read invalidations"},
                        "id": "3",
                        "type": "notes",
                    }
                },
            },
            {
                "generation": 9,
                "id": 2,
                "value": {
                    "data": {
                        "attributes": {"title": "Read invalidations"},
                        "id": "7",
                        "type": "notes",
                    }
                },
            },
            {
                "generation": 2,
                "id": 3,
                "value": "Ada",
            },
        ]
    }


def test_live_refresh_sanitizes_invalid_query_results():
    pattern = named_pattern(
        urls_for(LiveAPI(), InvalidationHub()),
        "pyjs_live_refresh",
    )
    request = RequestFactory().post(
        "/api/_live/refresh",
        data=json.dumps(
            {
                "queries": [
                    {
                        "arguments": {},
                        "generation": 1,
                        "id": 1,
                        "operation": "notes.invalid_result",
                    }
                ]
            }
        ),
        content_type="application/json",
    )

    response = asyncio.run(pattern.callback(request))

    assert response.status_code == 500
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": "server_error",
                "detail": "The server could not complete the operation.",
                "status": "500",
                "title": "Server error",
            }
        ]
    }


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ([], "The live refresh body must be an object."),
        ({}, "Live refresh queries must be a list."),
        (
            {"queries": [{}] * 101},
            "A live refresh can contain at most 100 queries.",
        ),
        (
            {
                "queries": [
                    {
                        "arguments": {},
                        "generation": 1,
                        "id": 1,
                        "operation": "notes.save",
                    }
                ]
            },
            "Live refresh requires a known query operation.",
        ),
    ],
)
def test_live_refresh_rejects_invalid_or_mutating_operations(payload, error):
    pattern = named_pattern(
        urls_for(LiveAPI(), InvalidationHub()),
        "pyjs_live_refresh",
    )
    request = RequestFactory().post(
        "/api/_live/refresh",
        data=json.dumps(payload),
        content_type="application/json",
    )

    response = asyncio.run(pattern.callback(request))

    assert response.status_code == 400
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": "invalid",
                "detail": error,
                "status": "400",
                "title": "Invalid request",
            }
        ]
    }


@pytest.mark.parametrize("name", ["pyjs_live_events", "pyjs_live_poll"])
def test_live_transports_only_accept_get(name):
    pattern = named_pattern(urls_for(LiveAPI(), InvalidationHub()), name)
    request = RequestFactory().post("/api/_live")

    response = asyncio.run(pattern.callback(request))

    assert response.status_code == 405
    assert response["Allow"] == "GET"


@pytest.mark.parametrize(
    "name",
    ["pyjs_live_refresh", "pyjs_live_subscribe"],
)
def test_live_write_endpoints_only_accept_post(name):
    pattern = named_pattern(
        urls_for(LiveAPI(), InvalidationHub()),
        name,
    )
    request = RequestFactory().get("/api/_live")

    response = asyncio.run(pattern.callback(request))

    assert response.status_code == 405
    assert response["Allow"] == "POST"


@pytest.mark.parametrize(
    ("name", "method"),
    [
        ("pyjs_live_events", "get"),
        ("pyjs_live_poll", "get"),
        ("pyjs_live_refresh", "post"),
        ("pyjs_live_subscribe", "post"),
    ],
)
def test_live_endpoints_enforce_the_mount_authorizer(name, method):
    def authorize(request):
        return request.headers.get("X-Live-Access") == "allowed"

    pattern = named_pattern(
        urls_for(
            LiveAPI(),
            InvalidationHub(),
            live_authorize=authorize,
        ),
        name,
    )
    request = getattr(RequestFactory(), method)("/api/_live")

    response = asyncio.run(pattern.callback(request))

    assert response.status_code == 403
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": "permission_denied",
                "detail": (
                    "You do not have permission to perform this operation."
                ),
                "status": "403",
                "title": "Permission denied",
            }
        ]
    }


def test_sse_closes_after_live_authorization_changes():
    async def scenario():
        allowed = True
        hub = InvalidationHub()

        async def authorize(request):
            return allowed

        pattern = named_pattern(
            urls_for(
                LiveAPI(),
                hub,
                live_authorize=authorize,
            ),
            "pyjs_live_events",
        )
        response = await pattern.callback(RequestFactory().get("/api/_live/events"))
        stream = response.streaming_content

        assert await anext(stream) == b"retry: 3000\n\n"

        allowed = False
        hub.publish(api_topic(LiveAPI))

        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    asyncio.run(scenario())


def test_long_poll_rechecks_live_authorization_before_delivery():
    async def scenario():
        allowed = True
        hub = InvalidationHub()

        def authorize(request):
            return allowed

        pattern = named_pattern(
            urls_for(
                LiveAPI(),
                hub,
                live_authorize=authorize,
            ),
            "pyjs_live_poll",
        )
        pending = asyncio.create_task(
            pattern.callback(RequestFactory().get("/api/_live/poll"))
        )
        await asyncio.sleep(0)

        allowed = False
        hub.publish(api_topic(LiveAPI))
        response = await pending

        assert response.status_code == 403
        assert json.loads(response.content) == {
            "errors": [
                {
                    "code": "permission_denied",
                    "detail": (
                        "You do not have permission to perform this operation."
                    ),
                    "status": "403",
                    "title": "Permission denied",
                }
            ]
        }

    asyncio.run(scenario())


def test_live_subscription_reuses_its_opaque_identifier():
    patterns = urls_for(LiveAPI(), InvalidationHub())
    pattern = named_pattern(patterns, "pyjs_live_subscribe")
    query = {
        "arguments": {"identifier": 1},
        "generation": 0,
        "id": 1,
        "operation": "notes.get",
        "topics": ["notes", "notes"],
    }

    first = call(pattern, {"queries": [query], "subscription": ""})
    token = json.loads(first.content)["subscription"]
    query["arguments"] = {"identifier": 2}
    second = call(pattern, {"queries": [query], "subscription": token})

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(token) >= 24
    assert json.loads(second.content) == {"subscription": token}


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({}, "Live subscription queries must be a list."),
        (
            {
                "queries": [
                    {
                        "arguments": {},
                        "generation": 0,
                        "id": 1,
                        "operation": "notes.get",
                        "topics": [],
                    }
                ]
            },
            "Live subscription topics must be strings.",
        ),
    ],
)
def test_live_subscription_rejects_invalid_queries(payload, error):
    pattern = named_pattern(
        urls_for(LiveAPI(), InvalidationHub()),
        "pyjs_live_subscribe",
    )

    response = call(pattern, payload)

    assert response.status_code == 400
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": "invalid",
                "detail": error,
                "status": "400",
                "title": "Invalid request",
            }
        ]
    }
