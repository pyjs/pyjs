import asyncio
import json
import socket
from http.client import HTTPConnection
from urllib.parse import urlsplit

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from pyjs.server.dev import Application, JsonSnapshot, Server


def request(server, method, path, body=None, headers=None):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


def raw_request(server, source):
    with socket.create_connection(("127.0.0.1", server.server_port), timeout=2) as client:
        client.sendall(source)
        client.shutdown(socket.SHUT_WR)
        response = bytearray()
        while chunk := client.recv(4096):
            response.extend(chunk)
    return bytes(response)


def test_routes_sessions_files_state_and_development_ui(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "example.txt").write_text("served file", encoding="utf-8")
    app = Application(name="Example")
    app.mount_files("/assets", assets)

    @app.post("/items/{item_id}")
    async def update(request, item_id):
        value = request.json()["value"]
        app.state.namespace("items")[item_id] = value
        request.session["last_item"] = item_id
        await asyncio.sleep(0)
        return {"id": item_id, "value": value}

    @app.get("/session")
    def session(request):
        return request.session.get("last_item", "none")

    with Server(app, port=0, quiet=True) as server:
        status, headers, body = request(
            server,
            "POST",
            "/items/example?ignored=true",
            json.dumps({"value": 42}),
            {"Content-Type": "application/json"},
        )
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        assert status == 200
        assert json.loads(body) == {"id": "example", "value": 42}

        status, _, body = request(
            server,
            "GET",
            "/session",
            headers={"Cookie": cookie},
        )
        assert status == 200
        assert body == b"example"

        status, headers, body = request(server, "GET", "/assets/example.txt")
        assert status == 200
        assert headers["Content-Type"] == "text/plain"
        assert body == b"served file"

        assert request(server, "POST", "/assets/example.txt")[0] == 404

        status, _, body = request(server, "GET", "/_pyjs/")
        assert status == 200
        assert b"Development server" in body
        assert b"POST" in body
        assert b"/items/{item_id}" in body
        assert request(server, "POST", "/_pyjs/state.json")[0] == 404

        status, _, body = request(server, "GET", "/_pyjs/state.json")
        assert status == 200
        assert json.loads(body) == {"items": {"example": 42}}


def test_memory_namespace_preserves_mapping_pop_semantics():
    namespace = Application().state.namespace("example")
    namespace["value"] = 42

    assert namespace.pop("value") == 42
    assert namespace.pop("missing", "fallback") == "fallback"
    with pytest.raises(KeyError, match="missing"):
        namespace.pop("missing")


def test_root_file_mount_serves_nested_indexes_and_redirects(tmp_path):
    nested = tmp_path / "guide"
    nested.mkdir()
    (tmp_path / "index.html").write_text("home", encoding="utf-8")
    (nested / "index.html").write_text("guide", encoding="utf-8")
    app = Application()
    app.mount_files("/", tmp_path, index=True)

    with Server(app, port=0, quiet=True) as server:
        assert request(server, "GET", "/")[2] == b"home"
        status, headers, _ = request(server, "GET", "/guide?mode=full")
        assert status == 308
        assert headers["Location"] == "/guide/?mode=full"
        assert request(server, "GET", "/guide/")[2] == b"guide"


def test_async_websocket_routes_share_the_application_lifecycle():
    app = Application(name="Sockets")
    events = []

    @app.on_startup
    async def started():
        events.append("started")

    @app.on_shutdown
    async def stopped():
        events.append("stopped")

    @app.websocket("/ws/{room}")
    async def echo(connection, room):
        message = await connection.recv()
        await connection.send(f"{room}: {message}")

    @app.get("/health")
    def health(request):
        return "ready"

    with Server(app, port=0, quiet=True) as server:
        assert urlsplit(app.websocket_url).port == server.server_port

        async def exchange():
            url = app.websocket_url.rstrip("/") + "/ws/main"
            async with connect(url, proxy=None) as connection:
                await connection.send(["hel", "lo"])
                message = await connection.recv()
                status, _, body = await asyncio.to_thread(
                    request,
                    server,
                    "GET",
                    "/health",
                )
                return message, status, body

        assert asyncio.run(exchange()) == ("main: hello", 200, b"ready")
        assert events == ["started"]

    assert events == ["started", "stopped"]


def test_async_server_runs_lifecycle_and_routes_on_callers_loop():
    application = Application()
    observed_loops = []

    @application.on_startup
    async def started():
        observed_loops.append(asyncio.get_running_loop())

    @application.get("/loop")
    async def route(request):
        observed_loops.append(asyncio.get_running_loop())
        return "same loop"

    async def exercise():
        expected_loop = asyncio.get_running_loop()
        server = Server(application, port=0, quiet=True)
        async with server:
            status, _, body = await asyncio.to_thread(
                request,
                server,
                "GET",
                "/loop",
            )
        return expected_loop, status, body

    expected_loop, status, body = asyncio.run(exercise())

    assert status == 200
    assert body == b"same loop"
    assert observed_loops == [expected_loop, expected_loop]


def test_active_websocket_is_closed_before_application_shutdown():
    application = Application()
    events = []

    @application.websocket("/ws")
    async def socket_handler(connection):
        events.append("connected")
        async for _ in connection:
            pass
        events.append("disconnected")

    @application.on_shutdown
    def stopped():
        events.append(f"shutdown:{application.websocket_connections}")

    async def exercise():
        server = Server(application, port=0, quiet=True)
        await server.start_async()
        connection = await connect(application.websocket_url + "ws", proxy=None)
        await asyncio.sleep(0)
        await asyncio.wait_for(server.close_async(), timeout=1)
        with pytest.raises(ConnectionClosed):
            await connection.recv()
        return connection.close_code

    assert asyncio.run(exercise()) == 1001
    assert events == ["connected", "disconnected", "shutdown:0"]


def test_in_flight_http_handler_finishes_before_application_shutdown():
    application = Application()
    events = []

    async def exercise():
        started = asyncio.Event()
        release = asyncio.Event()

        @application.get("/slow")
        async def slow(request):
            events.append("request started")
            started.set()
            await release.wait()
            events.append("request finished")
            return "done"

        @application.on_shutdown
        def stopped():
            events.append("shutdown")

        server = Server(application, port=0, quiet=True)
        await server.start_async()
        response = asyncio.create_task(asyncio.to_thread(request, server, "GET", "/slow"))
        await started.wait()
        closing = asyncio.create_task(server.close_async())
        await asyncio.sleep(0)
        assert events == ["request started"]
        release.set()
        await asyncio.wait_for(closing, timeout=1)
        await asyncio.gather(response, return_exceptions=True)

    asyncio.run(exercise())
    assert events == ["request started", "request finished", "shutdown"]


def test_failed_start_closes_the_server_and_remains_safe_to_close():
    application = Application()

    @application.on_startup
    def fail():
        raise RuntimeError("startup failed")

    server = Server(application, port=0, quiet=True)
    with pytest.raises(RuntimeError, match="application failed to start") as failed:
        server.start()

    assert str(failed.value.__cause__) == "startup failed"
    server.close()
    assert not server._thread.is_alive()
    with pytest.raises(RuntimeError, match="closed development server"):
        server.start()


@pytest.mark.parametrize(
    ("source", "status"),
    [
        (b"GET / HTTP/2\r\n\r\n", 505),
        (b"GET / HTTP/1.1\r\n invalid\r\n\r\n", 400),
        (b"POST / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n", 501),
        (b"POST / HTTP/1.1\r\nContent-Length: -1\r\n\r\n", 400),
        (b"POST / HTTP/1.1\r\nContent-Length: 1\r\n\r\n", 400),
        (
            b"POST / HTTP/1.1\r\n"
            b"Content-Length: 0\r\n"
            b"content-length: 1\r\n\r\n",
            400,
        ),
        (b"POST / HTTP/1.1\r\nExpect: 100-continue\r\n\r\n", 417),
        (
            b"GET /ws HTTP/1.1\r\n"
            b"Connection: Upgrade\r\n"
            b"Upgrade: websocket\r\n"
            b"Sec-WebSocket-Version: 13\r\n"
            b"Sec-WebSocket-Key: invalid\r\n\r\n",
            400,
        ),
    ],
)
def test_malformed_requests_receive_an_explicit_error(source, status):
    application = Application()

    @application.websocket("/ws")
    async def socket_handler(connection):
        pass

    with Server(application, port=0, quiet=True) as server:
        response = raw_request(server, source)

    assert response.startswith(f"HTTP/1.1 {status} ".encode())


def test_json_snapshot_is_explicit_and_atomic(tmp_path):
    snapshot = JsonSnapshot(tmp_path / "state.json")
    first = Application(snapshot=snapshot)
    first.state.namespace("example")["value"] = 42

    with Server(first, port=0, quiet=True):
        pass

    assert json.loads(snapshot.path.read_text()) == {"example": {"value": 42}}

    second = Application(snapshot=snapshot)
    with Server(second, port=0, quiet=True):
        assert second.state.namespace("example")["value"] == 42


def test_shutdown_attempts_every_callback_and_saves_state(tmp_path):
    events = []
    snapshot = JsonSnapshot(tmp_path / "state.json")
    application = Application(snapshot=snapshot)
    application.state.namespace("example")["value"] = 42

    @application.on_shutdown
    def after_failure():
        events.append("after failure")

    @application.on_shutdown
    async def fail():
        events.append("failure")
        raise RuntimeError("cleanup failed")

    @application.on_shutdown
    def before_failure():
        events.append("before failure")

    with pytest.raises(RuntimeError, match="cleanup failed"):
        asyncio.run(application.shutdown())

    assert events == ["before failure", "failure", "after failure"]
    assert json.loads(snapshot.path.read_text()) == {"example": {"value": 42}}


def test_shutdown_reports_multiple_callback_failures():
    application = Application()

    @application.on_shutdown
    def fail_first():
        raise ValueError("first cleanup failed")

    @application.on_shutdown
    async def fail_second():
        raise RuntimeError("second cleanup failed")

    with pytest.raises(ExceptionGroup, match="application shutdown failed") as failed:
        asyncio.run(application.shutdown())

    assert [str(error) for error in failed.value.exceptions] == [
        "second cleanup failed",
        "first cleanup failed",
    ]


def test_background_server_reports_shutdown_callback_failures():
    application = Application()

    @application.on_shutdown
    def fail():
        raise RuntimeError("cleanup failed")

    server = Server(application, port=0, quiet=True).start()

    with pytest.raises(
        RuntimeError,
        match="failed while running or shutting down",
    ) as failed:
        server.close()

    assert str(failed.value.__cause__) == "cleanup failed"
    server.close()


def test_remote_binding_requires_an_explicit_override():
    with pytest.raises(ValueError, match="allow_remote"):
        Server(
            Application(),
            host="0.0.0.0",
            port=0,
        )


def test_wsgi_apps_can_use_the_shared_development_transport():
    def wsgi(environ, start_response):
        start_response("201 Created", [("Content-Type", "application/json")])
        return [
            json.dumps(
                {
                    "method": environ["REQUEST_METHOD"],
                    "path": environ["PATH_INFO"],
                    "body": environ["wsgi.input"].read().decode(),
                }
            ).encode()
        ]

    app = Application()
    app.mount_wsgi(wsgi, prefix="/gateway")
    with Server(app, port=0, quiet=True) as server:
        status, _, body = request(
            server,
            "POST",
            "/gateway/legacy",
            "payload",
        )

    assert status == 201
    assert json.loads(body) == {
        "method": "POST",
        "path": "/legacy",
        "body": "payload",
    }
