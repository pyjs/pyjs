import asyncio
import importlib
import json
import runpy
import subprocess
import sys
import threading
from http.client import HTTPConnection

import pytest
from websockets.asyncio.client import connect

from pyjs.server import navigation_fragment, page
from pyjs.server.build import BuildStats
from pyjs.server.dev import Application, Server, create_server, serve
from pyjs.web import _dom_storage
from pyjs.web.dom import document
from pyjs.web.domx import tag
from pyjs.web.ssr import raw_html, render_document, render_html


def test_server_core_does_not_import_django():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import pyjs.server; "
            "assert not any(name == 'django' or name.startswith('django.') "
            "for name in sys.modules)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_server_core_does_not_load_the_development_transport():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import pyjs.server; "
            "assert 'pyjs.server.dev' not in sys.modules; "
            "assert 'websockets.asyncio.server' not in sys.modules",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_serve_handles_keyboard_interrupt_and_closes_server(monkeypatch, capsys):
    class InterruptedServer:
        closed = False

        def serve_forever(self):
            raise KeyboardInterrupt

        def close(self):
            self.closed = True

    server = InterruptedServer()
    monkeypatch.setattr("pyjs.server.dev.create_server", lambda *args, **kwargs: server)

    serve("example")

    assert server.closed
    assert capsys.readouterr().out == "\nServer stopped.\n"


def test_server_reports_compilation_time_and_asset_sizes(capsys):
    application = Application(name="example")
    application.build_stats = BuildStats(1.234, 3, 12_345, 678)
    server = Server(application, port=0)
    try:
        server._print_listeners()
    finally:
        server.close()

    assert capsys.readouterr().out == (
        "Build completed in 1.23s (3 JS files, 12.3 kB JS, 678 B CSS)\n"
        f"Serving example at {server.application.http_url}\n"
        f"Development UI at {server.application.http_url}_pyjs/\n"
    )


@pytest.fixture
def running_server(tmp_path, monkeypatch):
    module_name = "server_session_example"
    (tmp_path / f"{module_name}.py").write_text(
        """
from pyjs import js, nojs
from pyjs.server.dev import Response
from pyjs.web.domx import tag


@js
def main(value="0"):
    return tag("div", {"data-value": value}, value)


@nojs
def render(request):
    return main(request.session.get("value", "0"))


@nojs
def save_value(request):
    value = request.json().get("value")
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    request.session["value"] = value


@nojs
def generated_script(request):
    return Response("self.generated = true;", content_type="application/javascript")
""",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(tmp_path)
    module = importlib.import_module(module_name)
    server = create_server(
        module_name,
        "",
        "main",
        render=module.render,
        routes={
            ("POST", "/value"): module.save_value,
            ("GET", "/generated.js"): module.generated_script,
        },
        host="127.0.0.1",
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        sys.modules.pop(module_name, None)


@pytest.fixture
def running_websocket_server(tmp_path, monkeypatch):
    module_name = "server_websocket_example"
    (tmp_path / f"{module_name}.py").write_text(
        """
from pyjs import js, nojs
from pyjs.server.dev import Response
from pyjs.web.domx import tag


@js
def main():
    return tag("div", {"data-websocket-example": "true"}, "WebSocket example")


@nojs
async def echo(connection):
    async for message in connection:
        await connection.send("echo: " + message)


@nojs
def generated_script(request):
    return Response("self.generated = true;", content_type="application/javascript")
""",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(tmp_path)
    module = importlib.import_module(module_name)
    server = create_server(
        module_name,
        "",
        "main",
        routes={("GET", "/generated.js"): module.generated_script},
        websocket_routes={"/ws": module.echo},
        host="127.0.0.1",
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    assert server.started.wait(5)
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        sys.modules.pop(module_name, None)


@pytest.fixture
def running_navigation_server(tmp_path, monkeypatch):
    module_name = "server_navigation_example"
    (tmp_path / f"{module_name}.py").write_text(
        """
from pyjs import js, nojs
from pyjs.server import NavigationPage
from pyjs.web.dom import Element
from pyjs.web.domx import tag, tw
from pyjs.web.navigation import NavigationLayout


@js
class ExampleLayout(NavigationLayout):
    def __init__(self, content: Element, layout_id: str = "example"):
        super().__init__(content, layout_id)
        self.add(
            tag(
                "nav",
                tag("a", {"href": "/"}, "Home"),
                tag("a", {"href": "/details"}, "Details"),
            ),
            self.outlet,
        )


@js
def home_view():
    return tag("main", tag("h1", "Home"))


@js
def details_view():
    return tag("main", tw("text-fuchsia-700"), tag("h1", "Details"))


@nojs
def layout(request, content: Element, layout_id: str):
    return ExampleLayout(content, layout_id)


@nojs
def home(request):
    return NavigationPage(home_view(), "Home title")


@nojs
def details(request):
    return NavigationPage(
        details_view(),
        "Details title",
        headers={"Cache-Control": "private", "Vary": "Cookie"},
    )


def main():
    return ExampleLayout(home_view())
""",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(tmp_path)
    module = importlib.import_module(module_name)
    server = create_server(
        module_name,
        "",
        "main",
        routes={
            ("GET", "/"): module.home,
            ("GET", "/details"): module.details,
        },
        layout=module.layout,
        layout_id="example",
        page_entry_points=(module.home_view, module.details_view),
        host="127.0.0.1",
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        sys.modules.pop(module_name, None)


def request(server, method, path, body=None, headers=None):
    connection = HTTPConnection("127.0.0.1", server.server_port)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    result = response.status, response.getheaders(), response.read().decode("utf-8")
    connection.close()
    return result


def header(headers, name):
    return next(value for header_name, value in headers if header_name.lower() == name.lower())


def test_development_server_serves_the_exact_managed_vendor_module(
    tmp_path,
    monkeypatch,
):
    module_name = "server_npm_example"
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "server_vendor.py").write_text(
        '''
from pyjs import js
from pyjs.tooling.npm import NpmImport, NpmPackage

__pyjs_npm_imports__ = (NpmImport(NpmPackage("example-vendor", "1.0.0"), "$vendor"),)


@js
def project_name() -> str:
    return "server-example"


project_name.source("return $vendor.projectName();")
''',
        encoding="utf-8",
    )
    (tmp_path / f"{module_name}.py").write_text(
        """
from pyjs import js
from pyjs.web.domx import tag
from server_vendor import project_name


@js
def main():
    return tag("main", project_name())
""",
        encoding="utf-8",
    )
    managed = tmp_path / ".pyjs" / "npm"
    managed.mkdir(parents=True)
    (managed / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"example-vendor": "1.0.0"},
                "pyjs": {"imports": {"$vendor": "example-vendor"}},
            }
        ),
        encoding="utf-8",
    )
    vendor_source = "export const $vendor = {projectName: () => 'server-example'};\n"
    (managed / "pyjs-vendor.js").write_text(vendor_source, encoding="utf-8")
    monkeypatch.syspath_prepend(tmp_path)

    try:
        server = create_server(
            module_name,
            "",
            "main",
            host="127.0.0.1",
            port=0,
        )
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            status, headers, body = request(server, "GET", "/pyjs-vendor.js")
            assert status == 200
            assert header(headers, "Content-Type") == "application/javascript"
            assert body == vendor_source

            entry_module = server.application.compiled.entry_point.container.name
            status, _, body = request(server, "GET", f"/{entry_module}.js")
            assert status == 200
            assert body.startswith(
                "import { tag } from './pyjs.web.domx.js';\n"
                "import { project_name } from './server_vendor.js';\n"
            )

            status, _, body = request(server, "GET", "/server_vendor.js")
            assert status == 200
            assert body.startswith(
                "import { $vendor } from './pyjs-vendor.js';\n"
            )
        finally:
            server.shutdown()
            thread.join()
    finally:
        server.close()
        sys.modules.pop("server_npm_example", None)
        sys.modules.pop("server_vendor", None)


def test_application_can_load_and_refresh_from_its_file_path(tmp_path, monkeypatch):
    module_name = "standalone_file_app"
    module_path = tmp_path / f"{module_name}.py"
    module_path.write_text(
        """
from pyjs import js
from pyjs.web.domx import tag


@js
def main():
    return tag("p", "Before")
""",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(tmp_path)

    try:
        server = create_server(
            str(module_path),
            "",
            "main",
            host="127.0.0.1",
            port=0,
        )
        application = server.application.compiled

        assert application.module_name == module_name
        assert application.title == "Standalone File App"
        assert render_html(application.get_html()) == "<p>Before</p>"

        module_path.write_text(
            """
from pyjs import js
from pyjs.web.domx import tag


@js
def main():
    return tag("p", "After regeneration")
""",
            encoding="utf-8",
        )
        application.module_last_modified = None
        application.refresh()

        assert render_html(application.get_html()) == "<p>After regeneration</p>"
    finally:
        server.close()
        sys.modules.pop(module_name, None)


def test_module_name_uses_qualified_name_during_python_m_execution(tmp_path, monkeypatch):
    package = tmp_path / "example_package"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "app.py").write_text(
        """
from pyjs.server.dev import _module_name

resolved_module_name = _module_name(__file__)
""",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(tmp_path)

    result = runpy.run_module("example_package.app", run_name="__main__", alter_sys=True)

    assert result["resolved_module_name"] == "example_package.app"


def test_posted_session_state_is_rendered_on_the_next_request(running_server):
    assert isinstance(running_server, Server)

    status, headers, body = request(running_server, "GET", "/")
    cookie = header(headers, "Set-Cookie").split(";", 1)[0]

    assert status == 200
    assert "<title>Server Session Example</title>" in body
    assert '<link rel="icon" href="data:,"/>' in body
    assert 'data-value="0"' in body

    status, _, body = request(
        running_server,
        "POST",
        "/value",
        body='{"value": "42"}',
        headers={"Content-Type": "application/json", "Cookie": cookie},
    )

    assert status == 204
    assert body == ""

    status, _, body = request(running_server, "GET", "/", headers={"Cookie": cookie})

    assert status == 200
    assert 'data-value="42"' in body


def test_get_routes_can_serve_generated_javascript(running_server):
    status, headers, body = request(running_server, "GET", "/generated.js")

    assert status == 200
    assert header(headers, "Content-Type") == "application/javascript"
    assert body == "self.generated = true;"


def test_sessions_are_isolated_between_browsers(running_server):
    _, first_headers, _ = request(running_server, "GET", "/")
    first_cookie = header(first_headers, "Set-Cookie").split(";", 1)[0]
    request(
        running_server,
        "POST",
        "/value",
        body='{"value": "42"}',
        headers={"Content-Type": "application/json", "Cookie": first_cookie},
    )

    _, second_headers, second_body = request(running_server, "GET", "/")

    assert header(second_headers, "Set-Cookie").split(";", 1)[0] != first_cookie
    assert 'data-value="0"' in second_body


def test_invalid_route_data_returns_a_bad_request(running_server):
    status, _, body = request(
        running_server,
        "POST",
        "/value",
        body='{"value": 42}',
        headers={"Content-Type": "application/json"},
    )

    assert status == 400
    assert body == "value must be a string"


def test_websocket_server_serves_the_page_and_socket_on_one_port(running_websocket_server):
    assert isinstance(running_websocket_server, Server)
    assert (
        running_websocket_server.application.websocket_url
        == f"ws://127.0.0.1:{running_websocket_server.server_port}/"
    )

    status, _, body = request(running_websocket_server, "GET", "/")

    assert status == 200
    assert 'data-websocket-example="true"' in body

    async def exchange_message():
        uri = f"ws://127.0.0.1:{running_websocket_server.server_port}/ws"
        async with connect(uri, proxy=None) as connection:
            await connection.send("hello")
            return await connection.recv()

    assert asyncio.run(exchange_message()) == "echo: hello"


def test_compiled_applications_include_the_shared_development_ui(running_server):
    status, _, body = request(running_server, "GET", "/_pyjs/")

    assert status == 200
    assert "server_session_example" in body
    assert "Development server" in body


def test_websocket_server_serves_generated_get_routes(running_websocket_server):
    status, headers, body = request(running_websocket_server, "GET", "/generated.js")

    assert status == 200
    assert header(headers, "Content-Type") == "application/javascript"
    assert body == "self.generated = true;"


def test_navigation_route_returns_a_complete_document_for_normal_requests(
    running_navigation_server,
):
    status, headers, body = request(running_navigation_server, "GET", "/details")

    assert status == 200
    assert header(headers, "Content-Type") == "text/html"
    assert header(headers, "Vary") == "Cookie, X-PyJS-Navigation"
    assert body.startswith("<!doctype html>\n<html>")
    assert "<title>Details title</title>" in body
    assert "<example-layout" in body
    assert 'data-pyjs-layout="example" data-pyjs-page=""' in body
    assert "<h1>Details</h1>" in body
    assert "<script type=\"module\"" in body


def test_navigation_route_returns_only_the_page_for_enhanced_requests(
    running_navigation_server,
):
    status, headers, body = request(
        running_navigation_server,
        "GET",
        "/details",
        headers={"X-PyJS-Navigation": "1"},
    )

    assert status == 200
    assert header(headers, "Vary") == "Cookie, X-PyJS-Navigation"
    assert body == (
        '<div><title>Details title</title><div data-pyjs-layout="example" '
        'data-pyjs-page=""><main class="text-fuchsia-700"><h1>Details</h1>'
        "</main></div></div>"
    )


def test_navigation_compilation_roots_contribute_client_code_and_css(
    running_navigation_server,
):
    application = running_navigation_server.application.compiled
    javascript = application.package["server_navigation_example"].decode()
    navigation_javascript = application.package[
        "pyjs.web.navigation"
    ].decode()

    assert "class ExampleLayout extends NavigationLayout" in javascript
    assert "function details_view" not in javascript
    assert ".text-fuchsia-700" in application.get_css()
    assert (
        """function clicked_link(event, root) {
    var target = event.target;
    if ((target instanceof Element)) {
        var link = target.closest('a[href]');
        if (link != null && root.contains(link)) {
            return link;
        }
    }
    return null;
}"""
        in navigation_javascript
    )
    assert (
        """if ((heading instanceof HTMLElement)) {
                heading.setAttribute('tabindex', '-1');
                heading.focus({preventScroll: true});
            }"""
        in navigation_javascript
    )
    source_map = json.loads(
        application.source_maps["server_navigation_example"].decode()
    )
    assert source_map["version"] == 3
    assert source_map["file"] == "server_navigation_example.js"
    assert any(
        source.endswith("server_navigation_example.py")
        for source in source_map["sources"]
    )

    status, headers, body = request(
        running_navigation_server,
        "GET",
        "/server_navigation_example.js.map",
    )
    assert status == 200
    assert header(headers, "Content-Type") == "application/json"
    assert json.loads(body) == source_map


def test_navigation_fragment_has_a_stable_framework_neutral_shape():
    source = navigation_fragment(tag("article", "Page"), "Page title", "application")

    assert source == (
        '<div><title>Page title</title><div data-pyjs-layout="application" '
        'data-pyjs-page=""><article>Page</article></div></div>'
    )


def test_empty_non_void_elements_have_closing_tags():
    source = page(tag("main", tag("section"), tag("input")), "app.js", "app.css")

    assert '<link rel="icon" href="data:,"/>' in source
    assert "<section></section>" in source
    assert "<section/>" not in source
    assert "<input/>" in source


def test_html_renderer_escapes_text_and_attributes_by_default():
    source = render_html(tag("p", {"title": 'A & "B"'}, "<script>alert('x')</script>"))

    assert 'title="A &amp; &quot;B&quot;' in source
    assert "&lt;script&gt;alert('x')&lt;/script&gt;" in source
    assert "<script>" not in source


def test_html_renderer_only_preserves_explicitly_trusted_markup():
    source = render_html(tag("article", raw_html("<strong>Trusted</strong>")))

    assert "<strong>Trusted</strong>" in source


def test_html_renderer_escapes_str_subclasses_as_text():
    class Label(str):
        pass

    source = render_html(tag("article", Label("<strong>Untrusted</strong>")))

    assert source == "<article>&lt;strong&gt;Untrusted&lt;/strong&gt;</article>"


def test_compact_renderer_does_not_expand_lazy_dom_views():
    element = tag("article", {"aria-label": "Status"}, "Ready")
    parts = _dom_storage._get_parts(element)

    assert render_html(element) == '<article aria-label="Status">Ready</article>'
    assert parts == [1, ' aria-label="Status"', "Ready"]


def test_compact_renderer_stores_escaped_attributes_as_html_fragments():
    value = 'A & "B"'
    element = tag("article", {"aria-label": value}, "Ready")

    assert _dom_storage._get_parts(element) == [
        1,
        ' aria-label="A &amp; &quot;B&quot;"',
        "Ready",
    ]
    assert element.getAttribute("aria-label") == value
    assert render_html(element) == (
        '<article aria-label="A &amp; &quot;B&quot;">Ready</article>'
    )


def test_compact_renderer_syncs_materialized_attribute_nodes():
    element = tag("article", {"aria-label": "Before"})
    attribute = element.attributes.getNamedItem("aria-label")

    attribute.value = "After"

    assert element.getAttribute("aria-label") == "After"
    assert render_html(element) == '<article aria-label="After"></article>'


def test_compact_renderer_traverses_deep_trees_without_python_recursion():
    root = tag("div")
    parent = root
    for _ in range(1_100):
        child = tag("div")
        parent.append(child)
        parent = child

    source = render_html(root)

    assert source.count("<div>") == 1_101
    assert source.count("</div>") == 1_101


def test_document_renderer_adds_doctype():
    source = render_document(tag("html", tag("body", "Hello")))

    assert source.startswith("<!doctype html>\n<html>")


def test_html_renderer_preserves_inline_text_boundaries():
    source = render_html(tag("span", "Hello ", tag("strong", "world"), "!"))

    assert source == "<span>Hello <strong>world</strong>!</span>"


def test_html_renderer_serializes_reflected_dataset_attributes_once():
    element = tag("div")
    element.dataset["userId"] = "42"

    source = render_html(element)

    assert source == '<div data-user-id="42"></div>'
    assert source.count("data-user-id") == 1


def test_html_renderer_serializes_svg_element_trees():
    svg = document.createElementNS("http://www.w3.org/2000/svg", "svg")
    path = document.createElementNS("http://www.w3.org/2000/svg", "path")
    svg.setAttribute("viewBox", "0 0 16 16")
    path.setAttribute("d", "M1 1L15 15")
    svg.append(path)

    assert render_html(svg) == (
        '<svg viewBox="0 0 16 16"><path d="M1 1L15 15"></path></svg>'
    )


def test_compact_html_renderer_serializes_nested_svg_trees():
    svg = document.createElementNS("http://www.w3.org/2000/svg", "svg")
    path = document.createElementNS("http://www.w3.org/2000/svg", "path")
    path.setAttribute("d", "M1 1L15 15")
    svg.append(path)

    assert render_html(tag("div", svg)) == (
        '<div><svg><path d="M1 1L15 15"></path></svg></div>'
    )
