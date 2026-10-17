import asyncio
import json
import threading

from django.db import transaction
from django.test import RequestFactory
from pydantic import BaseModel

from pyjs.server import API, Stream, StreamFeed, StreamHub, stream
from pyjs.server.django import publish_stream_after_commit, stream_view


def test_stream_view_replays_then_delivers_the_live_tail():
    async def scenario():
        hub = StreamHub[dict[str, object]]()
        hub.publish("build:7", {"line": "one"})
        view = stream_view(
            hub,
            lambda request, build_id: "build:" + build_id,
        )
        response = await view(
            RequestFactory().get("/streams/7", {"after": "0"}),
            build_id="7",
        )
        stream = response.streaming_content

        assert response.status_code == 200
        assert response["Content-Type"] == "text/event-stream"
        assert response["Cache-Control"] == "no-cache, no-store, no-transform"
        assert response["X-Accel-Buffering"] == "no"
        assert response["Vary"] == "Cookie"
        assert await anext(stream) == b"retry: 3000\n\n"
        assert await anext(stream) == (
            b'id: 1\nevent: event\ndata: {"scope":"build:7",'
            b'"sequence":1,"type":"event","value":{"line":"one"}}\n\n'
        )

        hub.publish("build:7", {"line": "two"})

        assert await anext(stream) == (
            b'id: 2\nevent: event\ndata: {"scope":"build:7",'
            b'"sequence":2,"type":"event","value":{"line":"two"}}\n\n'
        )
        await stream.aclose()

    asyncio.run(scenario())


def test_stream_view_opens_backend_subscriptions_off_the_event_loop():
    class RecordingHub(StreamHub[str]):
        def __init__(self):
            super().__init__()
            self.subscribe_thread = None

        def subscribe(self, *args, **kwargs):
            self.subscribe_thread = threading.get_ident()
            return super().subscribe(*args, **kwargs)

    async def scenario():
        event_loop_thread = threading.get_ident()
        hub = RecordingHub()
        response = await stream_view(hub, "logs")(
            RequestFactory().get("/logs")
        )

        assert response.status_code == 200
        assert hub.subscribe_thread is not None
        assert hub.subscribe_thread != event_loop_thread
        await response.streaming_content.aclose()

    asyncio.run(scenario())


def test_stream_view_resyncs_expired_cursors_at_its_new_position():
    async def scenario():
        hub = StreamHub[str](replay_limit=1)
        hub.publish("logs", "one")
        hub.publish("logs", "two")
        response = await stream_view(hub, "logs")(
            RequestFactory().get("/logs", {"after": "0"})
        )
        stream = response.streaming_content

        assert await anext(stream) == b"retry: 3000\n\n"
        assert await anext(stream) == (
            b'id: 2\nevent: resync\ndata: {"scope":"logs",'
            b'"sequence":2,"type":"resync","value":null}\n\n'
        )

        hub.publish("logs", "three")

        assert await anext(stream) == (
            b'id: 3\nevent: event\ndata: {"scope":"logs",'
            b'"sequence":3,"type":"event","value":"three"}\n\n'
        )
        await stream.aclose()

    asyncio.run(scenario())


def test_stream_view_reports_slow_consumer_data_loss_and_closes():
    async def scenario():
        hub = StreamHub[str]()
        response = await stream_view(hub, "logs", buffer_limit=1)(
            RequestFactory().get("/logs")
        )
        stream = response.streaming_content
        hub.publish("logs", "one")
        hub.publish("logs", "two")

        assert await anext(stream) == b"retry: 3000\n\n"
        assert await anext(stream) == (
            b'id: 2\nevent: resync\ndata: {"scope":"logs",'
            b'"sequence":2,"type":"resync","value":null}\n\n'
        )
        try:
            await anext(stream)
        except StopAsyncIteration:
            pass
        else:
            raise AssertionError("The stream remained open after losing data.")

    asyncio.run(scenario())


def test_stream_view_checks_authorization_before_and_during_delivery():
    async def scenario():
        allowed = True
        checks = []
        hub = StreamHub[str]()

        async def authorize(request, scope):
            checks.append(scope)
            return allowed

        view = stream_view(hub, "private", authorize=authorize)
        accepted = await view(RequestFactory().get("/private"))
        assert accepted.status_code == 200

        stream = accepted.streaming_content
        assert await anext(stream) == b"retry: 3000\n\n"
        allowed = False
        hub.publish("private", "secret")

        try:
            await anext(stream)
        except StopAsyncIteration:
            pass
        else:
            raise AssertionError("The stream remained open after access was lost.")
        assert checks == ["private", "private"]

        rejected = await view(RequestFactory().get("/private"))
        assert rejected.status_code == 403
        assert json.loads(rejected.content)["errors"][0]["code"] == (
            "permission_denied"
        )

    asyncio.run(scenario())


def test_stream_view_serializes_domain_values_at_the_http_boundary():
    async def scenario():
        hub = StreamHub[tuple[int, str]]()
        response = await stream_view(
            hub,
            "visitors",
            serialize=lambda value: {"id": value[0], "path": value[1]},
        )(RequestFactory().get("/visitors"))
        stream = response.streaming_content
        hub.publish("visitors", (4, "/checkout"))

        assert await anext(stream) == b"retry: 3000\n\n"
        assert await anext(stream) == (
            b'id: 1\nevent: event\ndata: {"scope":"visitors",'
            b'"sequence":1,"type":"event","value":{"id":4,'
            b'"path":"/checkout"}}\n\n'
        )
        await stream.aclose()

    asyncio.run(scenario())


def test_stream_publish_waits_for_the_database_transaction_to_commit():
    class EmptyHistory:
        async def load(self, scope: str, request: object) -> object:
            raise RuntimeError

    hub = StreamHub[str]()
    feed = StreamFeed(hub, EmptyHistory(), "orders")
    subscription = hub.subscribe("orders")
    try:
        with transaction.atomic():
            publish_stream_after_commit(feed, "paid")
            assert subscription.empty() is True
        assert subscription.receive_nowait().value == "paid"
    finally:
        subscription.close()


def test_stream_view_rejects_invalid_resource_bounds():
    hub = StreamHub[str]()

    for arguments, message in (
        ({"heartbeat": 0}, "heartbeat must be positive"),
        ({"buffer_limit": 0}, "buffer limit must be positive"),
    ):
        try:
            stream_view(hub, "logs", **arguments)
        except ValueError as error:
            assert message in str(error)
        else:
            raise AssertionError("Invalid stream bounds were accepted.")


class APILogLine(BaseModel):
    sequence: int
    text: str


def test_typed_api_stream_routes_validate_arguments_and_encode_values():
    async def scenario():
        hub = StreamHub[APILogLine]()

        class LogsAPI(API):
            @stream
            def output(self, job_id: int) -> Stream[APILogLine]:
                return Stream(hub, "job:" + str(job_id))

        pattern = next(
            pattern
            for pattern in LogsAPI().urls
            if pattern.callback.__name__ == "output"
        )
        response = await pattern.callback(
            RequestFactory().get(
                "/api/output",
                {"arguments": json.dumps({"job_id": "7"})},
            )
        )
        content = response.streaming_content
        hub.publish(
            "job:7",
            APILogLine(sequence=1, text="container started"),
        )

        assert response.status_code == 200
        assert await anext(content) == b"retry: 3000\n\n"
        assert await anext(content) == (
            b'id: 1\nevent: event\ndata: {"scope":"job:7",'
            b'"sequence":1,"type":"event","value":{"sequence":1,'
            b'"text":"container started"}}\n\n'
        )
        await content.aclose()

    asyncio.run(scenario())


def test_typed_api_stream_skips_a_poison_event_with_explicit_resync(caplog):
    async def scenario():
        hub = StreamHub[object]()

        class LogsAPI(API):
            @stream
            def output(self) -> Stream[APILogLine]:
                return Stream(hub, "logs")

        pattern = next(
            pattern
            for pattern in LogsAPI().urls
            if pattern.callback.__name__ == "output"
        )
        response = await pattern.callback(RequestFactory().get("/api/output"))
        content = response.streaming_content
        hub.publish("logs", "not a log line")

        assert await anext(content) == b"retry: 3000\n\n"
        assert await anext(content) == (
            b'id: 1\nevent: resync\ndata: {"scope":"logs",'
            b'"sequence":1,"type":"resync","value":null}\n\n'
        )
        try:
            await anext(content)
        except StopAsyncIteration:
            pass
        else:
            raise AssertionError("The poisoned stream remained open.")

        recovered = await pattern.callback(
            RequestFactory().get("/api/output", {"after": "1"})
        )
        recovered_content = recovered.streaming_content
        hub.publish("logs", APILogLine(sequence=2, text="recovered"))

        assert await anext(recovered_content) == b"retry: 3000\n\n"
        assert await anext(recovered_content) == (
            b'id: 2\nevent: event\ndata: {"scope":"logs",'
            b'"sequence":2,"type":"event","value":{"sequence":2,'
            b'"text":"recovered"}}\n\n'
        )
        await recovered_content.aclose()

    asyncio.run(scenario())

    assert [record.getMessage() for record in caplog.records] == [
        "Could not serialize stream 'logs' sequence 1; "
        "requiring resynchronization."
    ]


def test_typed_api_stream_routes_recheck_request_scoped_access():
    async def scenario():
        allowed = True
        checks = 0
        hub = StreamHub[str]()

        async def authorize():
            nonlocal checks
            checks += 1
            return allowed

        class LogsAPI(API):
            @stream
            def output(self) -> Stream[str]:
                return Stream(hub, "private", authorize=authorize)

        pattern = next(
            pattern
            for pattern in LogsAPI().urls
            if pattern.callback.__name__ == "output"
        )
        response = await pattern.callback(RequestFactory().get("/api/output"))
        content = response.streaming_content
        assert await anext(content) == b"retry: 3000\n\n"
        allowed = False
        hub.publish("private", "secret")

        try:
            await anext(content)
        except StopAsyncIteration:
            pass
        else:
            raise AssertionError("The stream remained open after access was lost.")
        assert checks == 2

    asyncio.run(scenario())


def test_typed_api_stream_routes_reject_initial_access():
    class LogsAPI(API):
        @stream
        def output(self) -> Stream[str]:
            return Stream(
                StreamHub(),
                "private",
                authorize=lambda: False,
            )

    pattern = next(
        pattern
        for pattern in LogsAPI().urls
        if pattern.callback.__name__ == "output"
    )

    response = asyncio.run(
        pattern.callback(RequestFactory().get("/api/output"))
    )

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


def test_typed_api_stream_routes_reject_invalid_requests():
    class LogsAPI(API):
        @stream
        def output(self, job_id: int) -> Stream[str]:
            return Stream(StreamHub(), "job:" + str(job_id))

    pattern = next(
        pattern
        for pattern in LogsAPI().urls
        if pattern.callback.__name__ == "output"
    )

    async def scenario():
        malformed = await pattern.callback(
            RequestFactory().get("/api/output", {"arguments": "{"})
        )
        wrong_shape = await pattern.callback(
            RequestFactory().get("/api/output", {"arguments": "[]"})
        )
        missing_argument = await pattern.callback(
            RequestFactory().get("/api/output")
        )
        wrong_method = await pattern.callback(
            RequestFactory().post("/api/output")
        )

        assert malformed.status_code == 400
        assert json.loads(malformed.content) == {
            "errors": [
                {
                    "code": "invalid",
                    "detail": "The stream arguments are not valid JSON.",
                    "status": "400",
                    "title": "Invalid request",
                }
            ]
        }
        assert wrong_shape.status_code == 400
        assert json.loads(wrong_shape.content) == {
            "errors": [
                {
                    "code": "invalid",
                    "detail": "Stream arguments must be a JSON object.",
                    "status": "400",
                    "title": "Invalid request",
                }
            ]
        }
        assert missing_argument.status_code == 400
        assert json.loads(missing_argument.content) == {
            "errors": [
                {
                    "code": "missing_argument",
                    "detail": "Missing argument: job_id.",
                    "source": {"pointer": "/job_id"},
                    "status": "400",
                    "title": "Invalid request",
                }
            ]
        }
        assert wrong_method.status_code == 405
        assert json.loads(wrong_method.content) == {
            "errors": [
                {
                    "code": "invalid",
                    "detail": "Stream operations require GET.",
                    "status": "405",
                    "title": "Invalid request",
                }
            ]
        }

    asyncio.run(scenario())
