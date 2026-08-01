import asyncio
import importlib
import json
import secrets
import sys
import threading
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from websockets.asyncio.server import ServerConnection
from websockets.asyncio.server import serve as websocket_serve
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

from pyjs.transpiler import prepare_bundle
from pyjs.web.domx import HTMLElement, tag
from pyjs.web.ssr import render_document, write_html

SESSION_COOKIE_NAME = "pyjs-session"
MAX_REQUEST_BODY_SIZE = 64 * 1024


def _server_url(host, port):
    if not host or host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    elif ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}/"


def _module_name(module):
    path = Path(module)
    if not path.is_file():
        return module

    source = path.resolve()
    for loaded_module in tuple(sys.modules.values()):
        spec = getattr(loaded_module, "__spec__", None)
        loaded_file = getattr(loaded_module, "__file__", None)
        if spec is not None and loaded_file is not None and Path(loaded_file).resolve() == source:
            return spec.name
    return path.stem


class ServerRequest:
    def __init__(self, method, path, headers, body, session, session_id, new_session):
        self.method = method
        self.path = path
        self.headers = headers
        self.body = body
        self.session = session
        self.session_id = session_id
        self.new_session = new_session

    def json(self):
        return json.loads(self.body.decode("utf-8"))


class ServerResponse:
    def __init__(self, body="", status=200, content_type="text/plain", headers=None):
        self.body = body
        self.status = status
        self.content_type = content_type
        self.headers = headers or {}


def websocket_response(response, request=None):
    body = response.body
    if isinstance(body, str):
        body = body.encode("utf-8")
    headers = Headers()
    if response.content_type is not None:
        headers["Content-Type"] = response.content_type
    headers["Content-Length"] = str(len(body))
    if request is not None and request.new_session:
        headers["Set-Cookie"] = (
            f"{SESSION_COOKIE_NAME}={request.session_id}; HttpOnly; Path=/; SameSite=Lax"
        )
    for name, value in response.headers.items():
        headers[name] = value
    status = HTTPStatus(response.status)
    return Response(status.value, status.phrase, headers, body)


def html(body, js, css, script_type):
    return tag(
        "html",
        tag(
            "head",
            tag("meta", {"charset": "utf-8"}),
            tag("link", {"rel": "stylesheet", "href": css}),
        ),
        tag("body", body),
        tag("script", {"type": script_type, "src": js}, " "),
    )


def page(body, js, css, script_type="module"):
    return render_document(html(body, js, css, script_type))


def write(parent: HTMLElement, src):
    write_html(parent, src)


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        server: PyjsServer = self.server
        server.refresh()
        path = urlsplit(self.path).path
        if path == "/":
            request = server.create_request("GET", path, self.headers, b"")
            response = ServerResponse(
                page(
                    server.get_html(request),
                    f"{server.entry_point.container.name}.js",
                    "index.css",
                ),
                content_type="text/html",
            )
            self.send_server_response(response, request)
        elif path == "/index.css":
            self.send_server_response(ServerResponse(server.get_css(), content_type="text/css"))
        elif path.endswith(".js"):
            module_name = Path(path).stem
            if module_name not in server.package:
                self.send_error(404)
                return
            self.send_server_response(
                ServerResponse(server.package[module_name], content_type="application/javascript")
            )
        else:
            self.send_error(404)

    def do_POST(self):
        server: PyjsServer = self.server
        server.refresh()
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return
        if content_length < 0:
            self.send_error(400, "Invalid Content-Length")
            return
        if content_length > MAX_REQUEST_BODY_SIZE:
            self.send_error(413, "Request body is too large")
            return

        path = urlsplit(self.path).path
        request = server.create_request(
            "POST",
            path,
            self.headers,
            self.rfile.read(content_length),
        )
        try:
            response = server.dispatch(request)
        except ValueError as error:
            response = ServerResponse(str(error), status=400)
        self.send_server_response(response, request)

    def send_server_response(self, response, request=None):
        body = response.body
        if isinstance(body, str):
            body = body.encode("utf-8")

        self.send_response(response.status)
        if response.content_type is not None:
            self.send_header("Content-Type", response.content_type)
        if body:
            self.send_header("Content-Length", str(len(body)))
        if request is not None and request.new_session:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE_NAME}={request.session_id}; HttpOnly; Path=/; SameSite=Lax",
            )
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        if body:
            self.wfile.write(body)


class PyjsApplication:
    def __init__(
        self,
        module: str,
        css: str,
        entry_point: str,
        *entry_point_args,
        render=None,
        routes=None,
    ):
        self.module_name = _module_name(module)
        self.module = importlib.import_module(self.module_name)
        self.module_path = Path(self.module.__file__)
        self.module_last_modified = None
        self.package = None
        self.css_provided = bool(css)
        self.css = css
        self.entry_point = None
        self.entry_point_name = entry_point or "main"
        self.entry_point_args = entry_point_args
        self.render_name = self.callback_name(render) if render is not None else None
        self.routes = {
            (method.upper(), path): self.callback_name(callback)
            for (method, path), callback in (routes or {}).items()
        }
        self.sessions = {}
        self.refresh()

    def callback_name(self, callback):
        if isinstance(callback, str):
            return callback
        name = callback.__name__
        if not hasattr(self.module, name):
            raise ValueError("server callbacks must be module-level functions in the served module")
        return name

    def resolve_callback(self, name):
        return getattr(self.module, name)

    def create_request(self, method, path, headers, body):
        cookies = SimpleCookie(headers.get("Cookie", ""))
        session_cookie = cookies.get(SESSION_COOKIE_NAME)
        session_id = session_cookie.value if session_cookie is not None else None
        new_session = session_id not in self.sessions
        if new_session:
            session_id = secrets.token_urlsafe(24)
            self.sessions[session_id] = {}
        return ServerRequest(
            method,
            path,
            headers,
            body,
            self.sessions[session_id],
            session_id,
            new_session,
        )

    def dispatch(self, request):
        callback_name = self.routes.get((request.method, request.path))
        if callback_name is None:
            return ServerResponse("Not found", status=404)
        response = self.resolve_callback(callback_name)(request)
        if response is None:
            return ServerResponse(status=204, content_type=None)
        if not isinstance(response, ServerResponse):
            raise TypeError("server route callbacks must return ServerResponse or None")
        return response

    def refresh(self):
        last_modified = self.module_path.stat().st_mtime
        if self.module_last_modified != last_modified:
            self.module_last_modified = last_modified
            importlib.reload(self.module)
            entry_point_py_func = getattr(self.module, self.entry_point_name)
            self.package, self.entry_point, css = prepare_bundle(entry_point_py_func)
            if not self.css_provided:
                self.css = css
            for package_name, js in self.package.items():
                self.package[package_name] = js.encode("utf-8")

    def get_html(self, request=None):
        if self.render_name is not None:
            return self.resolve_callback(self.render_name)(request)
        return self.entry_point.py_func(*self.entry_point_args)

    def get_css(self):
        return self.css


class PyjsServer(HTTPServer, PyjsApplication):
    def __init__(
        self,
        module: str,
        css: str,
        entry_point: str,
        *entry_point_args,
        render=None,
        routes=None,
        host="",
        port=8000,
    ):
        HTTPServer.__init__(self, (host, port), RequestHandler)
        PyjsApplication.__init__(
            self,
            module,
            css,
            entry_point,
            *entry_point_args,
            render=render,
            routes=routes,
        )

    def serve_forever(self, poll_interval=0.5):
        print(f"Serving at {_server_url(self.server_address[0], self.server_port)}")
        super().serve_forever(poll_interval)


class WebSocketPyjsServer(PyjsApplication):
    def __init__(
        self,
        module: str,
        css: str,
        entry_point: str,
        *entry_point_args,
        render=None,
        routes=None,
        websocket_routes=None,
        host="",
        port=8000,
    ):
        super().__init__(
            module,
            css,
            entry_point,
            *entry_point_args,
            render=render,
            routes=routes,
        )
        self.websocket_routes = {
            path: self.callback_name(callback)
            for path, callback in (websocket_routes or {}).items()
        }
        self.host = host
        self.server_port = port
        self.started = threading.Event()
        self._loop = None
        self._shutdown_event = None
        self._shutdown_requested = False

    async def process_request(
        self,
        connection: ServerConnection,
        request: Request,
    ) -> Response | None:
        self.refresh()
        path = urlsplit(request.path).path
        if path in self.websocket_routes:
            return None
        if path == "/":
            server_request = self.create_request("GET", path, request.headers, b"")
            response = ServerResponse(
                page(
                    self.get_html(server_request),
                    f"{self.entry_point.container.name}.js",
                    "index.css",
                ),
                content_type="text/html",
            )
            return websocket_response(response, server_request)
        if path == "/index.css":
            return websocket_response(ServerResponse(self.get_css(), content_type="text/css"))
        if path.endswith(".js"):
            module_name = Path(path).stem
            if module_name not in self.package:
                return websocket_response(ServerResponse("Not found", status=404))
            return websocket_response(
                ServerResponse(self.package[module_name], content_type="application/javascript")
            )

        server_request = self.create_request("GET", path, request.headers, b"")
        return websocket_response(self.dispatch(server_request), server_request)

    async def handle_websocket(self, connection: ServerConnection):
        path = urlsplit(connection.request.path).path
        callback_name = self.websocket_routes.get(path)
        if callback_name is None:
            await connection.close(1008, "Unknown WebSocket route")
            return
        await self.resolve_callback(callback_name)(connection)

    async def run(self):
        self._loop = asyncio.get_running_loop()
        self._shutdown_event = asyncio.Event()
        if self._shutdown_requested:
            self._shutdown_event.set()
        async with websocket_serve(
            self.handle_websocket,
            self.host,
            self.server_port,
            process_request=self.process_request,
        ) as server:
            self.server_port = server.sockets[0].getsockname()[1]
            self.started.set()
            print(f"Serving at {_server_url(self.host, self.server_port)}")
            await self._shutdown_event.wait()

    def serve_forever(self):
        asyncio.run(self.run())

    def shutdown(self):
        self._shutdown_requested = True
        if self._loop is not None and self._shutdown_event is not None:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)

    def server_close(self):
        pass


def create_server(
    module,
    css="",
    entry_point=None,
    *args,
    render=None,
    routes=None,
    websocket_routes=None,
    host="",
    port=8000,
):
    if websocket_routes:
        return WebSocketPyjsServer(
            module,
            css,
            entry_point,
            *args,
            render=render,
            routes=routes,
            websocket_routes=websocket_routes,
            host=host,
            port=port,
        )
    return PyjsServer(
        module,
        css,
        entry_point,
        *args,
        render=render,
        routes=routes,
        host=host,
        port=port,
    )


def serve(
    module,
    css="",
    entry_point=None,
    *args,
    render=None,
    routes=None,
    websocket_routes=None,
    host="",
    port=8000,
):
    httpd = create_server(
        module,
        css,
        entry_point,
        *args,
        render=render,
        routes=routes,
        websocket_routes=websocket_routes,
        host=host,
        port=port,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        httpd.server_close()
