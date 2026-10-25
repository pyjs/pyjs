import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest

from tests.java.test_api_transport import django_server
from tests.java.test_exceptions import assert_compiles_to_android_dex, run_jvm


@pytest.fixture
def cookie_endpoint():
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append((self.path, self.headers.get("Cookie", "")))
            self.send_response(302 if self.path == "/redirect" else 200)
            if self.path == "/bootstrap":
                for cookie in ["session=alpha; Path=/api", "csrf=token; Path=/",
                               "secure=secret; Path=/; Secure", "dead=old; Max-Age=0; Path=/",
                               "foreign=other; Domain=example.invalid; Path=/"]:
                    self.send_header("Set-Cookie", cookie)
            if self.path == "/redirect":
                self.send_header("Set-Cookie", "rotated=new; Path=/")
                self.send_header("Location", "/never-follow")
            self.end_headers()
            self.wfile.write(self.headers.get("Cookie", "").encode())

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"])).decode()
            received.append((self.path, parse_qs(body), self.headers.get("Content-Type")))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"saved")

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_cookie_sessions_are_isolated_and_honor_native_cookie_policy(tmp_path, cookie_endpoint):
    url, received = cookie_endpoint
    source = f'''
from pyjs import jvm
from pyjs.java import run_sync
from pyjs.java.net import CookieManager
from pyjs.server.jvm import JVMTransport
@jvm.native("java/net/CookieHandler")
class CookieHandler:
    pass
@jvm.native("java/net/CookieHandler", name="getDefault")
def global_cookies() -> CookieHandler | None: ...
async def execute() -> str:
    assert global_cookies() is None
    jar = CookieManager()
    first = JVMTransport(cookies=jar)
    second = JVMTransport(cookies=CookieManager())
    await first.get({url + '/bootstrap'!r}, 3000)
    body = (await first.get({url + '/api/check'!r}, 3000)).body
    assert "session=alpha" in body
    assert "csrf=token" in body
    assert "secure=secret" not in body
    assert "dead=old" not in body
    assert "foreign=other" not in body
    assert "session=alpha" not in (await first.get({url + '/outside'!r}, 3000)).body
    assert (await second.get({url + '/api/check'!r}, 3000)).body == ""
    redirected = await first.get({url + '/redirect'!r}, 3000)
    assert redirected.status == 302
    assert "rotated=new" in (await first.get({url + '/api/check'!r}, 3000)).body
    jar.getCookieStore().removeAll()
    assert (await first.get({url + '/api/check'!r}, 3000)).body == ""
    assert global_cookies() is None
    return "isolated"
def main() -> str:
    return run_sync(execute())
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "isolated"
    assert "/never-follow" not in [entry[0] for entry in received]


def test_form_transport_encodes_unicode_and_reserved_characters(tmp_path, cookie_endpoint):
    url, received = cookie_endpoint
    source = f'''
from pyjs.java import run_sync
from pyjs.server.jvm import JVMTransport
async def execute() -> str:
    response = await JVMTransport().post_form({url + '/login'!r}, [("user name", "é😀雪 +&="), ("repeated", "first"), ("repeated", "second")], 3000)
    return response.body
def main() -> str:
    return run_sync(execute())
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "saved"
    assert received == [("/login", {"user name": ["é😀雪 +&="], "repeated": ["first", "second"]},
                         "application/x-www-form-urlencoded; charset=utf-8")]


@pytest.mark.parametrize("header", ["Cookie", "cOoKiE2"])
def test_managed_sessions_reject_explicit_cookies_before_sending(tmp_path, cookie_endpoint, header):
    url, received = cookie_endpoint
    source = f'''
from pyjs.java import run_sync
from pyjs.java.net import CookieManager
from pyjs.server.jvm import JVMTransport
def main() -> str:
    transport = JVMTransport([({header!r}, "session=unexpected")], cookies=CookieManager())
    try:
        run_sync(transport.get({url!r}, 3000))
    except ValueError as error:
        assert str(error) == "Managed cookies cannot be combined with explicit Cookie headers"
        return "rejected"
    return "sent"
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "rejected"
    assert received == []


def test_session_transport_compiles_to_android_dex(tmp_path):
    source = '''
from pyjs.java import run_sync
from pyjs.java.net import CookieManager
from pyjs.server.jvm import JVMTransport
from tests.java.api_session_contract import AuthenticatedAPI
async def execute() -> str:
    transport = JVMTransport(cookies=CookieManager())
    bootstrap = await transport.get("https://example.test/bootstrap/", 3000)
    login = await transport.post_form("https://example.test/login/", [("username", "example")], 3000)
    api = AuthenticatedAPI("https://example.test/api", transport=transport)
    return bootstrap.body + login.body + await api.username()
def main() -> str:
    return run_sync(execute())
'''
    assert_compiles_to_android_dex(source, tmp_path)


def test_managed_session_rejects_a_process_global_cookie_handler(tmp_path, cookie_endpoint):
    url, received = cookie_endpoint
    source = f'''
from pyjs import jvm
from pyjs.java import run_sync
from pyjs.java.net import CookieHandler, CookieManager, default_cookie_handler
from pyjs.server.jvm import JVMTransport
@jvm.native("java/net/CookieHandler", name="setDefault")
def set_global_cookies(value: CookieHandler | None) -> None: ...
def main() -> str:
    original = default_cookie_handler()
    global_jar = CookieManager()
    set_global_cookies(global_jar)
    try:
        try:
            run_sync(JVMTransport(cookies=CookieManager()).get({url + '/api/check'!r}, 3000))
        except ValueError as error:
            assert str(error) == "Managed sessions cannot share a process-global CookieHandler"
            assert default_cookie_handler() is global_jar
            return "rejected without changing global state"
        return "used global cookies"
    finally:
        set_global_cookies(original)
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "rejected without changing global state"
    assert received == []


@pytest.fixture(scope="module")
def django_session_endpoint(tmp_path_factory):
    directory = tmp_path_factory.mktemp("django-session")
    with django_server("tests.java.api_session_server", directory / "server.log", str(directory / "session.sqlite3")) as url:
        yield url


def test_generated_proxy_uses_real_django_login_rotation_and_logout(tmp_path, django_session_endpoint):
    url = django_session_endpoint
    source = f'''
from typing import cast
from pyjs.java import i32, run_sync
from pyjs.java.net import CookieManager, HttpCookie, URI
from pyjs.server.errors import OperationError
from pyjs.server.jvm import JVMTransport
from tests.java.api_session_contract import AuthenticatedAPI
from tests.java.api_transport_contract import Draft
def csrf(jar: CookieManager) -> str:
    cookies = jar.getCookieStore().get(URI({url!r}))
    for index in range(int(cookies.size())):
        cookie = cast(HttpCookie, cookies.get(i32(index)))
        if cookie.getName() == "csrftoken":
            return cookie.getValue()
    raise ValueError("Missing CSRF cookie")
async def execute() -> str:
    jar = CookieManager()
    transport = JVMTransport(cookies=jar)
    await transport.get({url + '/bootstrap/'!r}, 3000)
    before = csrf(jar)
    denied = await transport.post_form({url + '/login/'!r}, [("username", "test-user"), ("password", "test-pass-雪")], 3000)
    assert denied.status == 403
    login = await transport.post_form({url + '/login/'!r}, [("username", "test-user"), ("password", "test-pass-雪"), ("csrfmiddlewaretoken", before)], 3000)
    assert login.status == 302
    after = csrf(jar)
    assert after != before
    transport.headers.append(("X-CSRFToken", after))
    api = AuthenticatedAPI({url + '/api'!r}, transport=transport, timeout_ms=3000)
    assert await api.username() == "test-user"
    result = await api.echo(Draft(title="authenticated 雪😀"))
    assert result.title == "authenticated 雪😀"
    logout = await transport.post_form({url + '/logout/'!r}, [], 3000)
    assert logout.status == 302
    assert await api.username() == ""
    try:
        await api.echo(Draft(title="private"))
    except OperationError as error:
        assert error.issues[0].status == 403
        return result.title
    return "logout failed"
def main() -> str:
    return run_sync(execute())
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "authenticated 雪😀"
