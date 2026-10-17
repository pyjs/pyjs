"""Local development server for PyJS applications and test services."""

import asyncio
import base64
import contextlib
import hashlib
import html
import importlib
import inspect
import io
import json
import mimetypes
import os
import re
import secrets
import socket
import struct
import sys
import tempfile
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path
from types import MappingProxyType
from typing import Any, Self
from urllib.parse import parse_qs, unquote, urlsplit

from pyjs.analysis.analyzer import release_compilation
from pyjs.javascript.sourcemap import TranspiledJavaScript
from pyjs.javascript.transpiler import prepare_bundle_with_source_maps
from pyjs.server.build import BuildStats
from pyjs.server.rendering import NavigationPage, navigation_fragment, page
from pyjs.tooling.npm import ManagedNpmProject, collect_npm_imports
from pyjs.web.navigation import NAVIGATION_HEADER

DEFAULT_BODY_LIMIT = 1024 * 1024
MAX_REQUEST_BODY_SIZE = 64 * 1024
SESSION_COOKIE = "pyjs-session"
DEVTOOLS_PREFIX = "/_pyjs"
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MISSING = object()


class MemoryNamespace(MutableMapping[str, Any]):
    """Thread-safe mutable namespace owned by a :class:`MemoryStore`."""

    def __init__(self, store: MemoryStore, name: str):
        self.store = store
        self.name = name

    @property
    def _values(self) -> dict[str, Any]:
        return self.store._values.setdefault(self.name, {})

    def __getitem__(self, key: str) -> Any:
        with self.store.lock:
            return self._values[key]

    def __iter__(self) -> Iterator[str]:
        with self.store.lock:
            return iter(tuple(self._values))

    def __len__(self) -> int:
        with self.store.lock:
            return len(self._values)

    def __setitem__(self, key: str, value: Any) -> None:
        with self.store.lock:
            self._values[key] = value

    def __delitem__(self, key: str) -> None:
        with self.store.lock:
            del self._values[key]

    def get(self, key: str, default: Any = None) -> Any:
        with self.store.lock:
            return self._values.get(key, default)

    def setdefault(self, key: str, default: Any = None) -> Any:
        with self.store.lock:
            return self._values.setdefault(key, default)

    def pop(self, key: str, default: Any = _MISSING) -> Any:
        with self.store.lock:
            if default is _MISSING:
                return self._values.pop(key)
            return self._values.pop(key, default)

    def clear(self) -> None:
        with self.store.lock:
            self._values.clear()

    def snapshot(self) -> dict[str, Any]:
        with self.store.lock:
            return dict(self._values)


class MemoryStore:
    """Namespaced in-memory state without persistence or model semantics."""

    def __init__(self, values: Mapping[str, Mapping[str, Any]] | None = None):
        self.lock = threading.RLock()
        self._values = {
            name: dict(namespace) for name, namespace in (values or {}).items()
        }

    def namespace(self, name: str = "default") -> MemoryNamespace:
        if not name:
            raise ValueError("a state namespace requires a name")
        with self.lock:
            self._values.setdefault(name, {})
        return MemoryNamespace(self, name)

    def reset(self, name: str | None = None) -> None:
        with self.lock:
            if name is None:
                self._values.clear()
            else:
                self._values.pop(name, None)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self.lock:
            return {name: dict(namespace) for name, namespace in self._values.items()}

    def restore(self, values: Mapping[str, Mapping[str, Any]]) -> None:
        with self.lock:
            self._values = {name: dict(namespace) for name, namespace in values.items()}


class JsonSnapshot:
    """Explicit, atomic JSON serialization for development state."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict[str, dict[str, Any]] | None:
        try:
            source = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        value = json.loads(source)
        if not isinstance(value, dict) or not all(
            isinstance(name, str) and isinstance(namespace, dict)
            for name, namespace in value.items()
        ):
            raise ValueError("a PyJS state snapshot must contain JSON namespaces")
        return value

    def save(self, values: Mapping[str, Mapping[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(values, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise


class _Headers(Mapping[str, str]):
    """Read-only HTTP headers with case-insensitive lookup."""

    def __init__(self, values: Mapping[str, str]):
        self._values = {name.lower(): (name, value) for name, value in values.items()}

    def __getitem__(self, name: str) -> str:
        return self._values[name.lower()][1]

    def __iter__(self) -> Iterator[str]:
        return (name for name, _ in self._values.values())

    def __len__(self) -> int:
        return len(self._values)


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    raw_path: str
    query: Mapping[str, tuple[str, ...]]
    headers: Mapping[str, str]
    body: bytes
    path_params: Mapping[str, str] = field(default_factory=dict)
    session: MemoryNamespace | None = None
    session_id: str = ""
    new_session: bool = False

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    def form(self) -> dict[str, str]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("application/x-www-form-urlencoded"):
            raise ValueError("request body is not URL-encoded form data")
        return {
            name: values[-1]
            for name, values in parse_qs(
                self.body.decode("utf-8"), keep_blank_values=True
            ).items()
        }

    def query_value(self, name: str, default: str = "") -> str:
        values = self.query.get(name)
        return values[-1] if values else default


@dataclass
class Response:
    body: bytes | str = b""
    status: int = 200
    content_type: str | None = "text/plain; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def text(
        cls,
        value: str,
        *,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return cls(value, status, "text/plain; charset=utf-8", dict(headers or {}))

    @classmethod
    def html(
        cls,
        value: str,
        *,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return cls(value, status, "text/html; charset=utf-8", dict(headers or {}))

    @classmethod
    def json(
        cls,
        value: Any,
        *,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        return cls(
            json.dumps(value, separators=(",", ":")),
            status,
            "application/json",
            dict(headers or {}),
        )

    @classmethod
    def redirect(cls, url: str, *, status: int = 303) -> Response:
        return cls(b"", status, None, {"Location": url})


class WebSocketClosed(Exception):
    """Raised when receiving from a WebSocket after its close frame."""

    def __init__(self, code: int = 1000, reason: str = ""):
        self.code = code
        self.reason = reason
        super().__init__(f"WebSocket closed with code {code}: {reason}")


class WebSocket:
    """Async message interface over a local HTTP connection."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        request: Request,
        *,
        max_size: int = DEFAULT_BODY_LIMIT,
    ):
        self.reader = reader
        self.writer = writer
        self.request = request
        self.max_size = max_size
        self.closed = False
        self.close_code = 1000
        self.close_reason = ""
        self._write_lock = asyncio.Lock()
        self._fragment_opcode: int | None = None
        self._fragments = bytearray()

    async def recv(self) -> str | bytes:
        return await self._receive_message()

    async def send(self, value: str | bytes) -> None:
        if isinstance(value, str):
            payload = value.encode("utf-8")
            opcode = 0x1
        elif isinstance(value, bytes):
            payload = value
            opcode = 0x2
        else:
            raise TypeError("WebSocket messages must be str or bytes")
        await self._send_frame(opcode, payload)

    async def send_json(self, value: Any) -> None:
        await self.send(json.dumps(value, separators=(",", ":")))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed:
            return
        reason_bytes = reason.encode("utf-8")
        while len(reason_bytes) > 123:
            reason = reason[:-1]
            reason_bytes = reason.encode("utf-8")
        try:
            await self._send_frame(0x8, struct.pack("!H", code) + reason_bytes)
        except WebSocketClosed:
            pass
        finally:
            self.closed = True
            self.close_code = code
            self.close_reason = reason

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> str | bytes:
        try:
            return await self.recv()
        except WebSocketClosed:
            raise StopAsyncIteration from None

    async def _read_exact(self, size: int) -> bytes:
        try:
            return await self.reader.readexactly(size)
        except asyncio.IncompleteReadError:
            self.closed = True
            raise WebSocketClosed(1006, "connection ended") from None

    async def _receive_message(self) -> str | bytes:
        while not self.closed:
            first, second = await self._read_exact(2)
            final = bool(first & 0x80)
            if first & 0x70:
                await self._protocol_error("reserved frame bits are unsupported")
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if not masked:
                await self._protocol_error("client frames must be masked")
            if length == 126:
                length = struct.unpack("!H", await self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", await self._read_exact(8))[0]
                if length & (1 << 63):
                    await self._protocol_error("invalid frame length")
            control = opcode >= 0x8
            if control and (not final or length > 125):
                await self._protocol_error("invalid WebSocket control frame")
            if length > self.max_size:
                await self.close(1009, "message is too large")
                raise WebSocketClosed(1009, "message is too large")
            mask = await self._read_exact(4)
            encoded = await self._read_exact(length)
            payload = bytes(
                value ^ mask[index % 4] for index, value in enumerate(encoded)
            )

            if opcode == 0x8:
                code, reason = await self._parse_close(payload)
                if not self.closed:
                    await self._send_frame(0x8, payload)
                self.closed = True
                self.close_code = code
                self.close_reason = reason
                raise WebSocketClosed(code, reason)
            if opcode == 0x9:
                await self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in {0x1, 0x2}:
                if self._fragment_opcode is not None:
                    await self._protocol_error(
                        "started a message before finishing one"
                    )
                if final:
                    return await self._decode_message(opcode, payload)
                self._fragment_opcode = opcode
                self._fragments.extend(payload)
                continue
            if opcode == 0x0:
                if self._fragment_opcode is None:
                    await self._protocol_error("unexpected continuation frame")
                self._fragments.extend(payload)
                if len(self._fragments) > self.max_size:
                    await self.close(1009, "message is too large")
                    raise WebSocketClosed(1009, "message is too large")
                if final:
                    message_opcode = self._fragment_opcode
                    message = bytes(self._fragments)
                    self._fragment_opcode = None
                    self._fragments.clear()
                    return await self._decode_message(message_opcode, message)
                continue
            await self._protocol_error("unknown WebSocket opcode")
        raise WebSocketClosed(self.close_code, self.close_reason)

    async def _decode_message(self, opcode: int, payload: bytes) -> str | bytes:
        if opcode == 0x2:
            return payload
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            await self._protocol_error("text message is not valid UTF-8")

    async def _parse_close(self, payload: bytes) -> tuple[int, str]:
        if not payload:
            return 1000, ""
        if len(payload) == 1:
            await self._protocol_error("invalid close frame")
        code = struct.unpack("!H", payload[:2])[0]
        try:
            reason = payload[2:].decode("utf-8")
        except UnicodeDecodeError:
            await self._protocol_error("close reason is not valid UTF-8")
        return code, reason

    async def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self.closed and opcode != 0x8:
            raise WebSocketClosed(self.close_code, self.close_reason)
        length = len(payload)
        if length < 126:
            header = bytes((0x80 | opcode, length))
        elif length <= 0xFFFF:
            header = bytes((0x80 | opcode, 126)) + struct.pack("!H", length)
        else:
            header = bytes((0x80 | opcode, 127)) + struct.pack("!Q", length)
        try:
            async with self._write_lock:
                self.writer.write(header + payload)
                await self.writer.drain()
        except (ConnectionError, OSError) as exception:
            self.closed = True
            self.close_code = 1006
            self.close_reason = "connection ended"
            raise WebSocketClosed(1006, "connection ended") from exception

    async def _protocol_error(self, reason: str):
        await self.close(1002, reason)
        raise WebSocketClosed(1002, reason)

    async def _finish(self) -> None:
        self.writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await self.writer.wait_closed()


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    callback: Callable[..., Any]
    pattern: re.Pattern[str]
    parameters: tuple[str, ...]

    def match(self, method: str, path: str) -> Mapping[str, str] | None:
        if self.method != method:
            return None
        match = self.pattern.fullmatch(path)
        if match is None:
            return None
        return MappingProxyType(match.groupdict())


@dataclass(frozen=True)
class FileMount:
    prefix: str
    directory: Path
    index: bool = False


@dataclass(frozen=True)
class RequestRecord:
    method: str
    path: str
    status: int
    duration_ms: float
    timestamp: str
    error: str = ""


def _route_pattern(path: str) -> tuple[re.Pattern[str], tuple[str, ...]]:
    if not path.startswith("/"):
        raise ValueError("route paths must start with '/'")
    names: list[str] = []
    parts: list[str] = []
    cursor = 0
    for match in re.finditer(r"\{([A-Za-z_]\w*)(?::(path))?\}", path):
        parts.append(re.escape(path[cursor : match.start()]))
        name, converter = match.groups()
        if name in names:
            raise ValueError(f"duplicate route parameter: {name}")
        names.append(name)
        parts.append(f"(?P<{name}>{'.+' if converter == 'path' else '[^/]+'})")
        cursor = match.end()
    parts.append(re.escape(path[cursor:]))
    return re.compile("".join(parts)), tuple(names)


def _coerce_response(value: Any) -> Response:
    if isinstance(value, Response):
        return value
    if value is None:
        return Response(b"", 204, None)
    if isinstance(value, bytes):
        return Response(value, content_type="application/octet-stream")
    if isinstance(value, str):
        return Response.text(value)
    if isinstance(value, Mapping | list | tuple):
        return Response.json(value)
    raise TypeError(
        "development routes must return a response, JSON value, string, bytes, or None"
    )


class Application:
    """Transport-independent routes and in-memory development state."""

    def __init__(
        self,
        *,
        name: str = "PyJS application",
        state: MemoryStore | None = None,
        snapshot: JsonSnapshot | None = None,
        devtools: bool = True,
        body_limit: int = DEFAULT_BODY_LIMIT,
        request_history: int = 100,
    ):
        self.name = name
        self.state = state or MemoryStore()
        self.snapshot = snapshot
        self.devtools = devtools
        self.body_limit = body_limit
        self.routes: list[Route] = []
        self.websocket_routes: list[Route] = []
        self.file_mounts: list[FileMount] = []
        self.startup_callbacks: list[Callable[[], Any]] = []
        self.shutdown_callbacks: list[Callable[[], Any]] = []
        self.sessions = MemoryStore()
        self.request_records: deque[RequestRecord] = deque(maxlen=request_history)
        self.websocket_connections = 0
        self._websocket_connections: set[WebSocket] = set()
        self.http_url = ""
        self.websocket_url = ""
        self._wsgi_app: Callable[..., Any] | None = None
        self._wsgi_prefix = "/"

    def route(
        self,
        method: str,
        path: str,
        callback: Callable[..., Any] | None = None,
    ):
        def register(function: Callable[..., Any]):
            pattern, parameters = _route_pattern(path)
            self.routes.append(Route(method.upper(), path, function, pattern, parameters))
            return function

        return register(callback) if callback is not None else register

    def get(self, path: str, callback: Callable[..., Any] | None = None):
        return self.route("GET", path, callback)

    def post(self, path: str, callback: Callable[..., Any] | None = None):
        return self.route("POST", path, callback)

    def put(self, path: str, callback: Callable[..., Any] | None = None):
        return self.route("PUT", path, callback)

    def patch(self, path: str, callback: Callable[..., Any] | None = None):
        return self.route("PATCH", path, callback)

    def delete(self, path: str, callback: Callable[..., Any] | None = None):
        return self.route("DELETE", path, callback)

    def websocket(
        self,
        path: str,
        callback: Callable[..., Any] | None = None,
    ):
        def register(function: Callable[..., Any]):
            pattern, parameters = _route_pattern(path)
            self.websocket_routes.append(
                Route("WEBSOCKET", path, function, pattern, parameters)
            )
            return function

        return register(callback) if callback is not None else register

    def mount_files(
        self,
        prefix: str,
        directory: str | Path,
        *,
        index: bool = False,
    ) -> None:
        prefix = "/" + prefix.strip("/")
        self.file_mounts.append(FileMount(prefix, Path(directory).resolve(), index))

    def mount_wsgi(self, application: Callable[..., Any], prefix: str = "/") -> None:
        self._wsgi_app = application
        self._wsgi_prefix = "/" + prefix.strip("/") if prefix != "/" else "/"

    def on_startup(self, callback: Callable[[], Any]):
        self.startup_callbacks.append(callback)
        return callback

    def on_shutdown(self, callback: Callable[[], Any]):
        self.shutdown_callbacks.append(callback)
        return callback

    async def startup(self) -> None:
        if self.snapshot is not None:
            values = await asyncio.to_thread(self.snapshot.load)
            if values is not None:
                self.state.restore(values)
        for callback in self.startup_callbacks:
            await _invoke(callback)

    async def shutdown(self) -> None:
        errors: list[BaseException] = []
        for callback in reversed(self.shutdown_callbacks):
            try:
                await _invoke(callback)
            except BaseException as error:
                errors.append(error)
        if self.snapshot is not None:
            try:
                values = self.state.snapshot()
                await asyncio.to_thread(self.snapshot.save, values)
            except BaseException as error:
                errors.append(error)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("application shutdown failed", errors)

    def create_request(
        self,
        method: str,
        raw_path: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> Request:
        parsed = urlsplit(raw_path)
        query = MappingProxyType(
            {
                name: tuple(values)
                for name, values in parse_qs(parsed.query, keep_blank_values=True).items()
            }
        )
        cookies = SimpleCookie(headers.get("Cookie", ""))
        cookie = cookies.get(SESSION_COOKIE)
        session_id = cookie.value if cookie is not None else ""
        sessions = self.sessions.namespace("sessions")
        new_session = not session_id or sessions.get(session_id) is None
        if new_session:
            session_id = secrets.token_urlsafe(24)
            sessions[session_id] = {}
        session_store = _SessionNamespace(sessions, session_id)
        return Request(
            method,
            unquote(parsed.path) or "/",
            raw_path,
            query,
            _Headers(headers),
            body,
            session=session_store,
            session_id=session_id,
            new_session=new_session,
        )

    async def dispatch(self, request: Request) -> Response:
        started = time.monotonic()
        error = ""
        try:
            response = await self._dispatch(request)
        except (ValueError, json.JSONDecodeError) as exception:
            response = Response.text(str(exception), status=400)
        except Exception as exception:
            error = f"{type(exception).__name__}: {exception}"
            traceback.print_exc()
            response = Response.html(
                self._error_page(exception),
                status=500,
            )
        duration = (time.monotonic() - started) * 1000
        if not request.path.startswith(DEVTOOLS_PREFIX + "/"):
            self.request_records.append(
                RequestRecord(
                    request.method,
                    request.path,
                    response.status,
                    duration,
                    datetime.now(UTC).isoformat(),
                    error,
                )
            )
        if request.new_session:
            response.headers.setdefault(
                "Set-Cookie",
                f"{SESSION_COOKIE}={request.session_id}; HttpOnly; Path=/; SameSite=Lax",
            )
        return response

    async def _dispatch(self, request: Request) -> Response:
        method = "GET" if request.method == "HEAD" else request.method
        if self.devtools and method == "GET":
            if request.path == DEVTOOLS_PREFIX:
                return Response.redirect(DEVTOOLS_PREFIX + "/")
            if request.path == DEVTOOLS_PREFIX + "/":
                return Response.html(self._devtools_page())
            if request.path == DEVTOOLS_PREFIX + "/config.json":
                return Response.json(
                    {
                        "http_url": self.http_url,
                        "websocket_url": self.websocket_url,
                    }
                )
            if request.path == DEVTOOLS_PREFIX + "/state.json":
                return Response.json(self.state.snapshot())
            if request.path == DEVTOOLS_PREFIX + "/requests.json":
                return Response.json(
                    [record.__dict__ for record in self.request_records]
                )

        for route in self.routes:
            params = route.match(method, request.path)
            if params is None:
                continue
            routed_request = replace(request, path_params=params)
            value = await _invoke(route.callback, routed_request, **params)
            return _coerce_response(value)

        if method == "GET":
            file_response = await self._file_response(request)
            if file_response is not None:
                return file_response
        if self._wsgi_app is not None and (
            self._wsgi_prefix == "/"
            or request.path == self._wsgi_prefix
            or request.path.startswith(self._wsgi_prefix + "/")
        ):
            return await asyncio.to_thread(self._dispatch_wsgi, request)
        return Response.text("Not found", status=404)

    async def _file_response(
        self,
        request: Request,
    ) -> Response | None:
        for mount in self.file_mounts:
            matches = (
                mount.prefix == "/"
                or request.path == mount.prefix
                or request.path.startswith(mount.prefix + "/")
            )
            if not matches:
                continue
            relative = (
                request.path.lstrip("/")
                if mount.prefix == "/"
                else request.path.removeprefix(mount.prefix).lstrip("/")
            )
            target = (mount.directory / relative).resolve()
            if target != mount.directory and mount.directory not in target.parents:
                return Response.text("Not found", status=404)
            if target.is_dir() and mount.index:
                if not request.path.endswith("/"):
                    query = urlsplit(request.raw_path).query
                    location = request.path + "/"
                    if query:
                        location += "?" + query
                    return Response.redirect(location, status=308)
                target = target / "index.html"
            if not target.is_file():
                return Response.text("Not found", status=404)
            body = await asyncio.to_thread(target.read_bytes)
            content_type, encoding = mimetypes.guess_type(target.name)
            headers = {}
            if encoding:
                headers["Content-Encoding"] = encoding
            return Response(
                body,
                200,
                content_type or "application/octet-stream",
                headers,
            )
        return None

    def _dispatch_wsgi(self, request: Request) -> Response:
        status = "500 Internal Server Error"
        response_headers: list[tuple[str, str]] = []

        def start_response(value, headers, exc_info=None):
            nonlocal status, response_headers
            status = value
            response_headers = list(headers)

        parsed = urlsplit(request.raw_path)
        environ: dict[str, Any] = {
            "REQUEST_METHOD": request.method,
            "SCRIPT_NAME": "" if self._wsgi_prefix == "/" else self._wsgi_prefix,
            "PATH_INFO": (
                request.path
                if self._wsgi_prefix == "/"
                else request.path.removeprefix(self._wsgi_prefix) or "/"
            ),
            "QUERY_STRING": parsed.query,
            "SERVER_NAME": "localhost",
            "SERVER_PORT": "0",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "CONTENT_LENGTH": str(len(request.body)),
            "CONTENT_TYPE": request.headers.get("Content-Type", ""),
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.input": io.BytesIO(request.body),
            "wsgi.errors": io.StringIO(),
            "wsgi.multithread": True,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
        }
        for name, value in request.headers.items():
            normalized = "HTTP_" + name.upper().replace("-", "_")
            if normalized not in {"HTTP_CONTENT_LENGTH", "HTTP_CONTENT_TYPE"}:
                environ[normalized] = value
        iterable = self._wsgi_app(environ, start_response)
        try:
            body = b"".join(iterable)
        finally:
            close = getattr(iterable, "close", None)
            if close is not None:
                close()
        code = int(status.split(" ", 1)[0])
        headers = dict(response_headers)
        content_type = headers.pop("Content-Type", None)
        headers.pop("Content-Length", None)
        return Response(body, code, content_type, headers)

    def match_websocket(
        self,
        path: str,
    ) -> tuple[Route, Mapping[str, str]] | None:
        for route in self.websocket_routes:
            params = route.match("WEBSOCKET", path)
            if params is not None:
                return route, params
        return None

    async def dispatch_websocket(
        self,
        connection: WebSocket,
        route: Route,
        params: Mapping[str, str],
    ) -> None:
        started = time.monotonic()
        error = ""
        self._websocket_connections.add(connection)
        self.websocket_connections = len(self._websocket_connections)
        try:
            await _invoke(route.callback, connection, **params)
        except WebSocketClosed:
            pass
        except Exception as exception:
            error = f"{type(exception).__name__}: {exception}"
            traceback.print_exc()
            await connection.close(1011, "WebSocket handler failed")
        finally:
            if not connection.closed:
                await connection.close()
            self._websocket_connections.discard(connection)
            self.websocket_connections = len(self._websocket_connections)
            duration = (time.monotonic() - started) * 1000
            self.request_records.append(
                RequestRecord(
                    "WEBSOCKET",
                    connection.request.path,
                    101,
                    duration,
                    datetime.now(UTC).isoformat(),
                    error,
                )
            )

    def _devtools_page(self) -> str:
        route_rows = (
            "".join(
                f"<tr><td>{html.escape(route.method)}</td>"
                f"<td><code>{html.escape(route.path)}</code></td></tr>"
                for route in (*self.routes, *self.websocket_routes)
            )
            or '<tr><td colspan="2">No routes registered</td></tr>'
        )
        request_rows = (
            "".join(
                f"<tr><td>{html.escape(record.method)}</td>"
                f"<td><code>{html.escape(record.path)}</code></td>"
                f"<td>{record.status}</td><td>{record.duration_ms:.1f} ms</td></tr>"
                for record in reversed(self.request_records)
            )
            or '<tr><td colspan="4">No requests yet</td></tr>'
        )
        state_rows = (
            "".join(
                f"<li><code>{html.escape(name)}</code>: {len(values)} values</li>"
                for name, values in self.state.snapshot().items()
            )
            or "<li>No application state</li>"
        )
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="2">
<title>{html.escape(self.name)} development server</title>
<style>
body{{font:15px system-ui;margin:2rem auto;max-width:70rem;padding:0 1rem}}
header{{display:flex;align-items:baseline;gap:1rem}}small{{color:#667085}}
section{{border:1px solid #d0d5dd;border-radius:.5rem;margin:1rem 0;padding:1rem}}
table{{border-collapse:collapse;width:100%}}td,th{{padding:.4rem;text-align:left}}
tr:nth-child(even){{background:#f8fafc}}code{{color:#6941c6}}
</style></head><body><header><h1>{html.escape(self.name)}</h1>
<small>Development server — never use in production</small></header>
<section><h2>Listeners</h2><p>HTTP: <code>{html.escape(self.http_url)}</code><br>
WebSocket: <code>{html.escape(self.websocket_url or "disabled")}</code><br>
Active sockets: {self.websocket_connections}</p></section>
<section><h2>Routes</h2><table><tr><th>Method</th><th>Path</th></tr>
{route_rows}</table></section><section><h2>Memory state</h2><ul>{state_rows}</ul>
<p><a href="state.json">JSON state</a></p></section>
<section><h2>Recent requests</h2><table><tr><th>Method</th><th>Path</th>
<th>Status</th><th>Duration</th></tr>{request_rows}</table></section>
</body></html>"""

    def _error_page(self, exception: Exception) -> str:
        source = "".join(
            traceback.format_exception(
                type(exception), exception, exception.__traceback__
            )
        )
        return (
            '<!doctype html><html><head><meta charset="utf-8">'
            "<title>PyJS development error</title></head><body>"
            f"<h1>{html.escape(type(exception).__name__)}</h1>"
            f"<pre>{html.escape(source)}</pre></body></html>"
        )


class _SessionNamespace(MemoryNamespace):
    def __init__(self, sessions: MemoryNamespace, session_id: str):
        self.sessions = sessions
        self.session_id = session_id
        super().__init__(sessions.store, f"session:{session_id}")

    @property
    def _values(self) -> dict[str, Any]:
        return self.sessions[self.session_id]


async def _invoke(callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    if inspect.iscoroutinefunction(callback):
        return await callback(*args, **kwargs)
    value = await asyncio.to_thread(callback, *args, **kwargs)
    if inspect.isawaitable(value):
        return await value
    return value


MAX_HEADER_SIZE = 64 * 1024


class _HTTPError(Exception):
    def __init__(self, status: int, message: str, headers=None):
        self.status = status
        self.message = message
        self.headers = dict(headers or {})
        super().__init__(message)


class Server:
    """Single-loop local HTTP and WebSocket server."""

    def __init__(
        self,
        application: Application,
        *,
        host: str = "127.0.0.1",
        port: int = 8000,
        allow_remote: bool = False,
        request_timeout: float = 30,
        quiet: bool = False,
    ):
        if not allow_remote and host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(
                "the development server binds to loopback by default; "
                "pass allow_remote=True to expose it"
            )
        self.application = application
        self.host = host
        self.request_timeout = request_timeout
        self.quiet = quiet
        self._listener = _create_listener(host, port)
        self.server_port = self._listener.getsockname()[1]
        self.loop: asyncio.AbstractEventLoop | None = None
        self.started = threading.Event()
        self._shutdown_event: asyncio.Event | None = None
        self._server: asyncio.Server | None = None
        self._thread: threading.Thread | None = None
        self._connections: set[asyncio.StreamWriter] = set()
        self._thread_error: BaseException | None = None
        self._started_async = False
        self._startup_completed = False
        self._closed = False
        self.application.http_url = _listener_url("http", host, self.server_port)
        self._set_websocket_url()

    @property
    def url(self) -> str:
        return self.application.http_url.rstrip("/")

    async def start_async(self) -> Self:
        if self._started_async:
            return self
        if self._closed:
            raise RuntimeError("a closed development server cannot be restarted")
        self.loop = asyncio.get_running_loop()
        self._shutdown_event = asyncio.Event()
        self._set_websocket_url()
        try:
            await self.application.startup()
            self._server = await asyncio.start_server(
                self._handle_connection,
                sock=self._listener,
                limit=MAX_HEADER_SIZE + 1,
                start_serving=False,
            )
            await self._server.start_serving()
        except BaseException as exception:
            if self._thread is not None:
                self._thread_error = exception
            self._closed = True
            self.started.set()
            if self._server is not None:
                self._server.close()
                await self._server.wait_closed()
            else:
                self._listener.close()
            raise
        self._started_async = True
        self._startup_completed = True
        self.started.set()
        return self

    async def serve_async(self) -> None:
        await self.start_async()
        self._print_listeners()
        try:
            await self._shutdown_event.wait()
        finally:
            await self.close_async()

    def serve_forever(self) -> None:
        asyncio.run(self.serve_async())

    def start(self) -> Self:
        if self._closed:
            raise RuntimeError("a closed development server cannot be restarted")
        if self._thread is not None:
            return self

        def run() -> None:
            try:
                asyncio.run(self.serve_async())
            except BaseException as exception:
                if self._startup_completed:
                    self._thread_error = exception
                self.started.set()

        self._thread = threading.Thread(
            target=run,
            daemon=True,
            name="pyjs-dev",
        )
        self._thread.start()
        if not self.started.wait(timeout=10):
            raise RuntimeError("the PyJS development server did not start")
        if self._thread_error is not None:
            error, self._thread_error = self._thread_error, None
            raise RuntimeError("the PyJS application failed to start") from (
                error
            )
        return self

    def shutdown(self) -> None:
        if self._closed:
            return
        if self.loop is None or self._shutdown_event is None:
            self._listener.close()
            self._closed = True
            return
        self.loop.call_soon_threadsafe(self._shutdown_event.set)

    async def close_async(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._shutdown_event is not None:
            self._shutdown_event.set()
        if self._server is not None:
            self._server.close()
        else:
            self._listener.close()
        connections = tuple(self.application._websocket_connections)
        if connections:
            await asyncio.gather(
                *(
                    connection.close(1001, "server is shutting down")
                    for connection in connections
                ),
                return_exceptions=True,
            )
        writers = tuple(self._connections)
        for writer in writers:
            writer.close()
        if writers:
            await asyncio.gather(
                *(writer.wait_closed() for writer in writers),
                return_exceptions=True,
            )
        if self._server is not None:
            await self._server.wait_closed()
        try:
            if self._started_async:
                await self.application.shutdown()
        finally:
            self._started_async = False

    def close(self) -> None:
        self.shutdown()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=10)
        if self._thread_error is not None:
            error, self._thread_error = self._thread_error, None
            raise RuntimeError(
                "the PyJS application failed while running or shutting down"
            ) from error

    async def __aenter__(self) -> Self:
        return await self.start_async()

    async def __aexit__(self, *args: object) -> None:
        await self.close_async()

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *args: object) -> None:
        self.close()

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._connections.add(writer)
        try:
            while not self._closed:
                parsed = await self._read_request(reader)
                if parsed is None:
                    break
                method, target, version, headers, body = parsed
                request = self.application.create_request(
                    method,
                    target,
                    headers,
                    body,
                )
                if headers.get("Upgrade", "").lower() == "websocket":
                    await self._handle_websocket(reader, writer, request)
                    return
                try:
                    response = await asyncio.wait_for(
                        self.application.dispatch(request),
                        timeout=self.request_timeout,
                    )
                except TimeoutError:
                    response = Response.text("Request timed out", status=504)
                close = _connection_closes(version, headers)
                await self._write_response(writer, response, method, close=close)
                self._log(method, target, response.status)
                if close:
                    break
        except _HTTPError as error:
            response = Response.text(
                error.message,
                status=error.status,
                headers=error.headers,
            )
            await self._write_response(writer, response, "GET", close=True)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            self._connections.discard(writer)
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()

    async def _read_request(self, reader: asyncio.StreamReader):
        try:
            source = await asyncio.wait_for(
                reader.readuntil(b"\r\n\r\n"),
                timeout=self.request_timeout,
            )
        except asyncio.IncompleteReadError as exception:
            if not exception.partial:
                return None
            raise _HTTPError(400, "Incomplete HTTP request") from exception
        except asyncio.LimitOverrunError as exception:
            raise _HTTPError(431, "Request headers are too large") from exception
        except TimeoutError as exception:
            raise _HTTPError(408, "Request timed out") from exception
        lines = source[:-4].split(b"\r\n")
        try:
            method, target, version = lines[0].decode("ascii").split(" ")
        except (UnicodeDecodeError, ValueError) as exception:
            raise _HTTPError(400, "Invalid HTTP request line") from exception
        if version not in {"HTTP/1.0", "HTTP/1.1"}:
            raise _HTTPError(505, "HTTP version is not supported")
        headers = _parse_headers(lines[1:])
        if headers.get("Transfer-Encoding"):
            raise _HTTPError(501, "Transfer-Encoding is not supported")
        try:
            content_length = int(headers.get("Content-Length", "0"))
        except ValueError as exception:
            raise _HTTPError(400, "Invalid Content-Length") from exception
        if content_length < 0:
            raise _HTTPError(400, "Invalid Content-Length")
        if content_length > self.application.body_limit:
            raise _HTTPError(413, "Request body is too large")
        if headers.get("Expect", "").lower() == "100-continue":
            raise _HTTPError(417, "Expect is not supported")
        try:
            body = await asyncio.wait_for(
                reader.readexactly(content_length),
                timeout=self.request_timeout,
            )
        except asyncio.IncompleteReadError as exception:
            raise _HTTPError(400, "Incomplete request body") from exception
        except TimeoutError as exception:
            raise _HTTPError(408, "Request body timed out") from exception
        return method, target, version, headers, body

    async def _handle_websocket(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        request: Request,
    ) -> None:
        if request.method != "GET":
            raise _HTTPError(400, "WebSocket upgrades require GET")
        matched = self.application.match_websocket(request.path)
        if matched is None:
            raise _HTTPError(404, "Unknown WebSocket route")
        connection_tokens = {
            value.strip().lower()
            for value in request.headers.get("Connection", "").split(",")
        }
        if "upgrade" not in connection_tokens:
            raise _HTTPError(400, "Invalid WebSocket Connection header")
        if request.headers.get("Sec-WebSocket-Version") != "13":
            raise _HTTPError(
                426,
                "WebSocket version is not supported",
                {"Sec-WebSocket-Version": "13"},
            )
        key = request.headers.get("Sec-WebSocket-Key", "")
        try:
            decoded_key = base64.b64decode(key, validate=True)
        except ValueError:
            decoded_key = b""
        if len(decoded_key) != 16:
            raise _HTTPError(400, "Invalid Sec-WebSocket-Key")
        accept = base64.b64encode(
            hashlib.sha1((key + WEBSOCKET_GUID).encode("ascii")).digest()
        ).decode("ascii")
        headers = {
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Accept": accept,
        }
        if request.new_session:
            headers["Set-Cookie"] = (
                f"{SESSION_COOKIE}={request.session_id}; HttpOnly; "
                "Path=/; SameSite=Lax"
            )
        await self._write_head(writer, 101, headers)
        self._log("GET", request.raw_path, 101)
        route, params = matched
        connection = WebSocket(
            reader,
            writer,
            request,
            max_size=self.application.body_limit,
        )
        try:
            await self.application.dispatch_websocket(connection, route, params)
        finally:
            await connection._finish()

    async def _write_response(
        self,
        writer: asyncio.StreamWriter,
        response: Response,
        method: str,
        *,
        close: bool,
    ) -> None:
        body = (
            response.body.encode("utf-8")
            if isinstance(response.body, str)
            else response.body
        )
        headers = {
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
            **response.headers,
        }
        if response.content_type is not None:
            headers.setdefault("Content-Type", response.content_type)
        if close:
            headers["Connection"] = "close"
        await self._write_head(writer, response.status, headers)
        if method != "HEAD" and body:
            writer.write(body)
            await writer.drain()

    async def _write_head(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        headers: Mapping[str, str],
    ) -> None:
        try:
            reason = HTTPStatus(status).phrase
        except ValueError:
            reason = "Unknown"
        lines = [f"HTTP/1.1 {status} {reason}\r\n"]
        lines.extend(f"{name}: {value}\r\n" for name, value in headers.items())
        lines.append("\r\n")
        writer.write("".join(lines).encode("latin-1"))
        await writer.drain()

    def _set_websocket_url(self) -> None:
        self.application.websocket_url = (
            _listener_url("ws", self.host, self.server_port)
            if self.application.websocket_routes
            else ""
        )

    def _print_listeners(self) -> None:
        if self.quiet:
            return
        build_stats = getattr(self.application, "build_stats", None)
        if build_stats is not None:
            print(build_stats)
        print(f"Serving {self.application.name} at {self.application.http_url}")
        if self.application.websocket_url:
            print("WebSockets use the same listener")
        print(f"Development UI at {self.application.http_url}_pyjs/")

    def _log(self, method: str, target: str, status: int) -> None:
        if not self.quiet:
            print(f"{method} {target} {status}")


def _parse_headers(lines: list[bytes]) -> _Headers:
    values: dict[str, tuple[str, str]] = {}
    for line in lines:
        if not line or line[:1] in b" \t" or b":" not in line:
            raise _HTTPError(400, "Invalid HTTP header")
        raw_name, raw_value = line.split(b":", 1)
        try:
            name = raw_name.decode("ascii")
            value = raw_value.decode("latin-1").strip()
        except UnicodeDecodeError as exception:
            raise _HTTPError(400, "Invalid HTTP header") from exception
        if not name or not all(
            character.isalnum() or character in "!#$%&'*+-.^_`|~"
            for character in name
        ):
            raise _HTTPError(400, "Invalid HTTP header name")
        normalized = name.lower()
        if normalized in values:
            original_name, original_value = values[normalized]
            values[normalized] = original_name, f"{original_value}, {value}"
        else:
            values[normalized] = name, value
    return _Headers(dict(values.values()))


def _connection_closes(version: str, headers: Mapping[str, str]) -> bool:
    tokens = {
        value.strip().lower()
        for value in headers.get("Connection", "").split(",")
    }
    if version == "HTTP/1.0":
        return "keep-alive" not in tokens
    return "close" in tokens


def _create_listener(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    listener = socket.socket(family, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen()
        listener.setblocking(False)
    except BaseException:
        listener.close()
        raise
    return listener


def _listener_url(scheme: str, host: str, port: int) -> str:
    display_host = "127.0.0.1" if host in {"", "0.0.0.0", "::"} else host
    if ":" in display_host and not display_host.startswith("["):
        display_host = f"[{display_host}]"
    return f"{scheme}://{display_host}:{port}/"


def _module_name(module):
    path = Path(module)
    if not path.is_file():
        return module

    source = path.resolve()
    for loaded_module in tuple(sys.modules.values()):
        spec = getattr(loaded_module, "__spec__", None)
        loaded_file = getattr(loaded_module, "__file__", None)
        if (
            spec is not None
            and loaded_file is not None
            and Path(loaded_file).resolve() == source
        ):
            return spec.name
    return path.stem


class _PyjsApplication:
    def __init__(
        self,
        module: str,
        css: str,
        entry_point: str,
        *entry_point_args,
        render=None,
        routes=None,
        layout=None,
        layout_id="main",
        page_entry_points=(),
    ):
        self.module_name = _module_name(module)
        self.title = self.module_name.rsplit(".", 1)[-1].replace("_", " ").title()
        self.module = importlib.import_module(self.module_name)
        self.module_path = Path(self.module.__file__)
        self.module_last_modified = None
        self.package = None
        self.source_maps = None
        self.vendor = None
        self.css_provided = bool(css)
        self.css = css
        self.entry_point = None
        self.entry_point_name = entry_point or "main"
        self.entry_point_args = entry_point_args
        self.render_name = self.callback_name(render) if render is not None else None
        self.layout_name = self.callback_name(layout) if layout is not None else None
        self.layout_id = layout_id
        self.page_entry_point_names = tuple(
            self.callback_name(callback) for callback in page_entry_points
        )
        self.routes = {
            (method.upper(), path): self.callback_name(callback)
            for (method, path), callback in (routes or {}).items()
        }
        self.build_stats = None
        self.refresh_lock = threading.RLock()
        self.refresh()

    def callback_name(self, callback):
        if isinstance(callback, str):
            return callback
        name = callback.__name__
        if not hasattr(self.module, name):
            raise ValueError(
                "server callbacks must be module-level functions in the served module"
            )
        return name

    def resolve_callback(self, name):
        return getattr(self.module, name)

    def dispatch(self, request: Request) -> Response:
        callback_name = self.routes.get((request.method, request.path))
        if callback_name is None:
            return Response.text("Not found", status=404)
        response = self.resolve_callback(callback_name)(request)
        if response is None:
            return Response(status=204, content_type=None)
        if isinstance(response, NavigationPage):
            return self.render_navigation_response(request, response)
        if not isinstance(response, Response):
            raise TypeError(
                "server route callbacks must return NavigationPage, Response, or None"
            )
        return response

    def render_navigation_response(
        self,
        request: Request,
        response: NavigationPage,
    ) -> Response:
        if self.layout_name is None:
            raise TypeError("NavigationPage responses require a layout callback")

        headers = dict(response.headers)
        vary = headers.get("Vary")
        if vary is None:
            headers["Vary"] = NAVIGATION_HEADER
        elif NAVIGATION_HEADER.lower() not in vary.lower():
            headers["Vary"] = f"{vary}, {NAVIGATION_HEADER}"

        if request.headers.get(NAVIGATION_HEADER) == "1":
            body = navigation_fragment(response.body, response.title, self.layout_id)
        else:
            layout = self.resolve_callback(self.layout_name)(
                request,
                response.body,
                self.layout_id,
            )
            body = page(
                layout,
                f"{self.entry_point.container.name}.js",
                "index.css",
                title=response.title,
            )
        return Response(
            body,
            status=response.status,
            content_type="text/html",
            headers=headers,
        )

    def refresh(self) -> None:
        with self.refresh_lock:
            last_modified = self.module_path.stat().st_mtime
            if self.module_last_modified == last_modified:
                return
            started = time.perf_counter()
            importlib.reload(self.module)
            entry_point = getattr(self.module, self.entry_point_name)
            additional_entry_points = tuple(
                getattr(self.module, name) for name in self.page_entry_point_names
            )
            (
                self.package,
                source_maps,
                self.entry_point,
                css,
            ) = prepare_bundle_with_source_maps(
                entry_point,
                additional_entry_points=additional_entry_points,
            )
            try:
                npm_imports = collect_npm_imports(self.package)
                vendor = ManagedNpmProject.for_project(
                    self.module_path
                ).vendor_for(npm_imports)
                if npm_imports and vendor is None:
                    raise RuntimeError(
                        "JavaScript dependencies are not synchronized; run "
                        f"'pyjs npm sync {self.module_name}:{self.entry_point_name}'"
                    )
                self.vendor = vendor.read_bytes() if vendor is not None else None
                if not self.css_provided:
                    self.css = css
                for package_name, javascript in self.package.items():
                    filename = f"{package_name}.js"
                    source_map = source_maps[package_name].with_file(filename)
                    generated = TranspiledJavaScript(javascript, source_map)
                    self.package[package_name] = generated.with_source_mapping_url(
                        f"{filename}.map"
                    ).encode("utf-8")
                    source_maps[package_name] = source_map.to_json().encode("utf-8")
                self.source_maps = source_maps
                self.build_stats = BuildStats(
                    time.perf_counter() - started,
                    len(self.package) + (self.vendor is not None),
                    sum(len(source) for source in self.package.values())
                    + (len(self.vendor) if self.vendor is not None else 0),
                    len(self.css.encode("utf-8")),
                )
                self.module_last_modified = last_modified
            finally:
                release_compilation(self.entry_point)

    def get_html(self, request: Request | None = None):
        if self.render_name is not None:
            return self.resolve_callback(self.render_name)(request)
        return self.entry_point.py_func(*self.entry_point_args)

    def get_css(self):
        return self.css


class _PyjsApplicationAdapter(Application):
    """Adapt compiled PyJS pages to the local development runtime."""

    def __init__(self, compiled: _PyjsApplication, websocket_routes=None):
        super().__init__(
            name=compiled.module_name,
            body_limit=MAX_REQUEST_BODY_SIZE,
        )
        self.compiled = compiled
        methods = {"GET", "POST"}
        methods.update(method for method, _ in compiled.routes)
        for method, path in compiled.routes:
            self.route(method, path, self.handle_request)
        for method in methods:
            if (method, "/") not in compiled.routes:
                self.route(method, "/", self.handle_request)
            self.route(method, "/{path:path}", self.handle_request)

        for path, callback in (websocket_routes or {}).items():
            callback_name = compiled.callback_name(callback)
            self.websocket(path, self.websocket_callback(callback_name))

    @property
    def build_stats(self) -> BuildStats:
        assert self.compiled.build_stats is not None
        return self.compiled.build_stats

    def handle_request(self, request: Request, **path_params) -> Response:
        self.compiled.refresh()
        method = "GET" if request.method == "HEAD" else request.method
        request = replace(request, method=method)

        if method == "GET" and request.path == "/":
            if (method, request.path) in self.compiled.routes:
                return self.compiled.dispatch(request)
            return Response(
                page(
                    self.compiled.get_html(request),
                    f"{self.compiled.entry_point.container.name}.js",
                    "index.css",
                    title=self.compiled.title,
                ),
                content_type="text/html",
            )
        if method == "GET" and request.path == "/index.css":
            return Response(self.compiled.get_css(), content_type="text/css")
        if method == "GET" and request.path == "/pyjs-vendor.js":
            if self.compiled.vendor is not None:
                return Response(
                    self.compiled.vendor,
                    content_type="application/javascript",
                )
            return Response.text("Not found", status=404)
        if (method, request.path) in self.compiled.routes:
            return self.compiled.dispatch(request)
        if method == "GET" and request.path.endswith(".js.map"):
            module_name = request.path.removeprefix("/").removesuffix(".js.map")
            if module_name in self.compiled.source_maps:
                return Response(
                    self.compiled.source_maps[module_name],
                    content_type="application/json",
                )
        if method == "GET" and request.path.endswith(".js"):
            module_name = Path(request.path).stem
            if module_name in self.compiled.package:
                return Response(
                    self.compiled.package[module_name],
                    content_type="application/javascript",
                )
        return Response.text("Not found", status=404)

    def websocket_callback(self, callback_name: str):
        async def callback(connection: WebSocket, **path_params):
            await asyncio.to_thread(self.compiled.refresh)
            function = self.compiled.resolve_callback(callback_name)
            await function(connection)

        return callback


def create_server(
    module,
    css="",
    entry_point=None,
    *args,
    render=None,
    routes=None,
    layout=None,
    layout_id="main",
    page_entry_points=(),
    websocket_routes=None,
    host="",
    port=8000,
):
    listener_host = host or "127.0.0.1"
    if isinstance(module, Application):
        application = module
    else:
        compiled = _PyjsApplication(
            module,
            css,
            entry_point,
            *args,
            render=render,
            routes=routes,
            layout=layout,
            layout_id=layout_id,
            page_entry_points=page_entry_points,
        )
        application = _PyjsApplicationAdapter(compiled, websocket_routes)
    return Server(
        application,
        host=listener_host,
        port=port,
        allow_remote=listener_host
        not in {"127.0.0.1", "localhost", "::1"},
    )


def serve(
    module,
    css="",
    entry_point=None,
    *args,
    render=None,
    routes=None,
    layout=None,
    layout_id="main",
    page_entry_points=(),
    websocket_routes=None,
    host="",
    port=8000,
) -> None:
    server = create_server(
        module,
        css,
        entry_point,
        *args,
        render=render,
        routes=routes,
        layout=layout,
        layout_id=layout_id,
        page_entry_points=page_entry_points,
        websocket_routes=websocket_routes,
        host=host,
        port=port,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.close()
