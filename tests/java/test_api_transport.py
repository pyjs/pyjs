import json
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests.java.test_exceptions import assert_compiles_to_android_dex, run_jvm


@pytest.fixture
def endpoint():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, dict(self.headers), body))
            if self.path == "/slow":
                time.sleep(0.3)
            status = {"/error": 422, "/redirect": 307, "/empty": 204}.get(self.path, 200)
            response = b"" if status == 204 else body
            self.send_response(status)
            if status == 307:
                self.send_header("Location", "/must-not-follow")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            try:
                self.wfile.write(response)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The timeout case intentionally closes the client socket.

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()


IMPORTS = '''
from pyjs.java import run_sync
from pyjs.server.jvm import JVMTransport
from pyjs.server.transport import ClientTransport
'''


@pytest.mark.parametrize(("path", "status"), [("/echo", 200), ("/error", 422), ("/redirect", 307), ("/empty", 204)])
def test_transport_sends_utf8_and_retains_status_and_body(tmp_path, endpoint, path, status):
    url, received = endpoint
    body = json.dumps({"title": "é😀雪", "text": "line\nnext"}, ensure_ascii=False)
    result = run_jvm(IMPORTS + f'''
def main() -> str:
    transport: ClientTransport = JVMTransport([("Authorization", "Bearer example")])
    response = run_sync(transport.request({url + path!r}, {body!r}))
    assert response.status == {status}
    assert response.ok == {200 <= status < 300}
    return response.body
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ("" if status == 204 else body)
    assert len(received) == 1
    assert received[0][0] == path
    assert received[0][1]["Authorization"] == "Bearer example"
    assert received[0][1]["Content-Type"] == "application/json; charset=utf-8"
    assert received[0][2] == body.encode()


def test_transport_limits_bytes_and_remains_usable_after_failure(tmp_path, endpoint):
    url, received = endpoint
    result = run_jvm(IMPORTS + f'''
def main() -> str:
    transport = JVMTransport(None, 4)
    try:
        run_sync(transport.request({url + '/echo'!r}, "😀x"))
    except ValueError as error:
        assert str(error) == "API response exceeds the configured byte limit"
    else:
        return "limit missed"
    return run_sync(transport.request({url + '/echo'!r}, "😀")).body
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "😀"
    assert len(received) == 2


def test_explicit_referer_reaches_the_server(tmp_path, endpoint):
    url, received = endpoint
    result = run_jvm(IMPORTS + f'''
def main() -> str:
    transport = JVMTransport([("Referer", "https://example.test/"), ("X-CSRFToken", "token")])
    return run_sync(transport.request({url + '/echo'!r}, "ready")).body
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ready"
    assert len(received) == 1
    assert received[0][1]["Referer"] == "https://example.test/"
    assert received[0][1]["X-CSRFToken"] == "token"


def test_transport_timeout_keeps_native_exception(tmp_path, endpoint):
    url, _ = endpoint
    result = run_jvm(IMPORTS + f'''
from pyjs.java.net import SocketTimeoutException
def main() -> str:
    transport = JVMTransport()
    try:
        run_sync(transport.request({url + '/slow'!r}, "{{}}", 30))
    except SocketTimeoutException:
        return "timed out"
    return "timeout missed"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "timed out"


def test_transport_can_run_on_an_explicit_worker(tmp_path, endpoint):
    url, received = endpoint
    source = IMPORTS + f'''
from pyjs.java.concurrent import Runnable, Thread
class RequestTask(Runnable):
    def __init__(self):
        self.result = "pending"
    def run(self) -> None:
        response = run_sync(JVMTransport().request({url + '/echo'!r}, "worker"))
        self.result = response.body
def main() -> str:
    task = RequestTask()
    worker = Thread(task)
    worker.start()
    worker.join()
    return task.result
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "worker"
    assert len(received) == 1


def test_transport_compiles_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(IMPORTS + '''
def main() -> str:
    transport: ClientTransport = JVMTransport()
    response = run_sync(transport.request("https://example.invalid/api/echo", "{}"))
    return response.body if response.ok else "rejected"
''', tmp_path)


@pytest.mark.parametrize("expression", [
    "JVMTransport(None, -1)",
    "JVMTransport(None, 0)",
    'run_sync(JVMTransport().request("file:/unused", "{}"))',
    'run_sync(JVMTransport().request("http://unused", "{}", -1))',
    'run_sync(JVMTransport().request("http://unused", "{}", 2147483648))',
])
def test_transport_rejects_invalid_configuration_before_io(tmp_path, expression):
    result = run_jvm(IMPORTS + f'''
def main() -> str:
    try:
        {expression}
    except ValueError:
        return "rejected"
    return "not rejected"
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "rejected"


@contextmanager
def django_server(module, log_path, *arguments):
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", module, *arguments],
            stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                lines = log_path.read_text().splitlines()
                if process.poll() is not None:
                    pytest.fail("Django server exited:\n" + "\n".join(lines))
                if lines and lines[0].startswith("http://127.0.0.1:"):
                    yield lines[0]
                    return
                time.sleep(0.05)
            pytest.fail("Django server did not start:\n" + log_path.read_text())
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture(scope="module")
def django_endpoint(tmp_path_factory):
    log_path = tmp_path_factory.mktemp("django-transport") / "server.log"
    with django_server("tests.java.api_transport_server", log_path) as url:
        yield url


@pytest.mark.parametrize(("draft", "credential", "csrf", "status"), [
    ({"title": "é😀雪"}, True, True, 200),
    ({"title": ""}, True, True, 422),
    ({"title": "private"}, False, True, 403),
    ({"title": "unchecked"}, True, False, 403),
])
def test_transport_reaches_real_django_typed_dispatch(
    tmp_path, django_endpoint, draft, credential, csrf, status,
):
    # A fixed CSRF cookie/header pair exercises Django middleware, not a new
    # authentication mechanism. Obtaining and persisting credentials is separate.
    headers = []
    if csrf:
        headers += [("Cookie", "csrftoken=" + "a" * 32), ("X-CSRFToken", "a" * 32)]
    if credential:
        headers.append(("Authorization", "Bearer test-token"))
    body = json.dumps({"draft": draft}, ensure_ascii=False)
    result = run_jvm(IMPORTS + f'''
def main() -> str:
    transport = JVMTransport({headers!r})
    response = run_sync(transport.request({django_endpoint + '/echo'!r}, {body!r}))
    assert response.status == {status}
    return response.body
''', tmp_path)
    assert result.returncode == 0, result.stderr
    decoded = json.loads(result.stdout)
    if status == 200:
        assert decoded == {"title": draft["title"], "count": 0}
    else:
        assert decoded["errors"][0]["status"] == str(status)
        if not csrf:
            assert decoded["errors"][0]["code"] == "csrf_failed"
