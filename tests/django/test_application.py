import asyncio
from types import SimpleNamespace

import pytest
from django.test import AsyncRequestFactory, RequestFactory
from django.test.utils import override_settings

import pyjs.server.django.application as application_module
import pyjs.server.django.development as development_module
from pyjs.javascript.sourcemap import SourceMap, TranspiledJavaScript
from pyjs.server.django import (
    ApplicationPage,
    ApplicationSection,
    PyJSApplication,
    development_reload_application,
    development_reload_script,
)
from pyjs.tooling.npm import NpmImport, NpmPackage
from pyjs.web.domx import tag
from pyjs.web.navigation import NAVIGATION_HEADER

CSRF_TOKEN = "test-csrf-token"


@pytest.fixture(autouse=True)
def deterministic_csrf_token(monkeypatch):
    monkeypatch.setattr(application_module, "get_token", lambda request: CSRF_TOKEN)


def main():
    return tag("main", "Application")


def dashboard_page():
    return tag("section", "Dashboard")


def settings_page():
    return tag("section", "Settings")


def account_section(content):
    return tag("section", tag("nav", "Account"), content)


def preferences_section(content):
    return tag("div", {"data-section": "preferences"}, content)


def application_shell(content):
    return tag("main", {"id": "application"}, content)


def authenticated_application_shell(content, username, csrf_token):
    return tag(
        "main",
        {"data-user": username},
        content,
        tag(
            "form",
            {"method": "post"},
            tag(
                "input",
                {
                    "name": "csrfmiddlewaretoken",
                    "type": "hidden",
                    "value": csrf_token,
                },
            ),
        ),
    )


def test_build_writes_namespaced_assets_and_includes_registered_pages(
    tmp_path,
    monkeypatch,
):
    calls = []

    def fake_bundle(targets, *, filename_suffix):
        calls.append((targets, filename_suffix))
        return {
            target.name: TranspiledJavaScript(
                f"// {target.name} javascript\n",
                SourceMap(file=f"{target.name}.js"),
            )
            for target in targets
        }, "/* application css */\n"

    monkeypatch.setattr(
        application_module,
        "bundle_targets_with_source_maps",
        fake_bundle,
    )
    dashboard = ApplicationPage("dashboard", dashboard_page)
    settings = ApplicationPage("settings", settings_page)
    application = PyJSApplication(
        main,
        name="example",
        mounts=(
            ApplicationSection(
                "account",
                account_section,
                (
                    dashboard,
                    ApplicationSection(
                        "preferences",
                        preferences_section,
                        (settings,),
                    ),
                ),
            ),
        ),
    )

    javascript, stylesheet = application.build(tmp_path)

    assert [
        (target.name, target.entry_point, target.parent)
        for target in calls[0][0]
    ] == [
        ("app", main, None),
        ("app.account", account_section, "app"),
        ("app.account.dashboard", dashboard_page, "app.account"),
        ("app.account.preferences", preferences_section, "app.account"),
        (
            "app.account.preferences.settings",
            settings_page,
            "app.account.preferences",
        ),
    ]
    assert calls[0][1] == ".js"
    assert javascript == tmp_path / "app.js"
    assert stylesheet == tmp_path / "app.css"
    assert javascript.read_text() == (
        "// app javascript\n//# sourceMappingURL=app.js.map\n"
    )
    assert (tmp_path / "app.js.map").read_text() == (
        '{"version":3,"sources":[],"sourcesContent":[],"names":[],"mappings":"",'
        '"file":"app.js"}'
    )
    assert stylesheet.read_text() == "/* application css */\n"
    assert (tmp_path / "app.account.preferences.settings.js").read_text() == (
        "// app.account.preferences.settings javascript\n"
        "//# sourceMappingURL=app.account.preferences.settings.js.map\n"
    )
    assert application.static_path("app.js") == "example/app.js"
    assert application.build_stats is not None
    assert application.build_stats.duration >= 0
    assert application.build_stats.javascript_files == 5
    assert application.build_stats.javascript_bytes == sum(
        path.stat().st_size for path in tmp_path.glob("*.js")
    )
    assert application.build_stats.css_bytes == stylesheet.stat().st_size


def test_build_defaults_to_the_containing_django_apps_static_namespace(
    tmp_path,
    monkeypatch,
):
    app_path = tmp_path / "example_app"
    app_config = SimpleNamespace(path=str(app_path))

    looked_up_modules = []

    def containing_app(module_name):
        looked_up_modules.append(module_name)
        return app_config

    monkeypatch.setattr(
        application_module.apps,
        "get_containing_app_config",
        containing_app,
    )
    monkeypatch.setattr(
        application_module,
        "bundle_with_source_map",
        lambda entry_point, *, additional_entry_points, filename: (
            TranspiledJavaScript("javascript", SourceMap(file=filename)),
            "css",
        ),
    )
    monkeypatch.setattr(
        application_module,
        "import_module",
        lambda name: pytest.fail(
            f"Default Django asset output imported {name!r}."
        ),
    )
    application = PyJSApplication(main, name="example")

    javascript, stylesheet = application.build()

    assert looked_up_modules == [__name__]
    assert javascript == app_path / "static" / "example" / "app.js"
    assert stylesheet == app_path / "static" / "example" / "app.css"
    assert javascript.read_text() == "javascript\n//# sourceMappingURL=app.js.map\n"
    assert stylesheet.read_text() == "css"


def test_build_copies_the_exact_managed_vendor_module(tmp_path, monkeypatch):
    imports = (
        NpmImport(NpmPackage("example-package", "1.2.3"), "$example"),
    )
    monkeypatch.setattr(
        application_module,
        "bundle_with_source_map",
        lambda *args, **kwargs: (
            TranspiledJavaScript(
                "import { $example } from './pyjs-vendor.js';\n",
                SourceMap(file="app.js"),
                imports,
            ),
            "css",
        ),
    )
    def copy_vendor(required, destination):
        assert required == imports
        destination.write_text(
            "export const $example = {};\n",
            encoding="utf-8",
        )

    managed_project = SimpleNamespace(copy_vendor=copy_vendor)
    monkeypatch.setattr(
        application_module.ManagedNpmProject,
        "for_project",
        lambda start: managed_project,
    )
    application = PyJSApplication(main, name="example")

    javascript, stylesheet = application.build(tmp_path)

    assert javascript.read_text() == (
        "import { $example } from './pyjs-vendor.js';\n"
        "//# sourceMappingURL=app.js.map\n"
    )
    assert stylesheet.read_text() == "css"
    assert (tmp_path / "pyjs-vendor.js").read_text() == (
        "export const $example = {};\n"
    )
    assert application.build_stats is not None
    assert application.build_stats.javascript_files == 2
    assert application.build_stats.javascript_bytes == sum(
        path.stat().st_size for path in tmp_path.glob("*.js")
    )


def test_page_bundle_preserves_the_configured_javascript_suffix():
    settings = ApplicationPage("settings", settings_page)
    application = PyJSApplication(
        main,
        name="example",
        mounts=(settings,),
        javascript_name="browser.mjs",
    )

    assert application.bundle_filename() == "browser.mjs"
    assert application.bundle_filename(settings) == "browser.settings.mjs"


def test_rendered_page_wraps_nested_sections_and_selects_its_own_bundle():
    settings = ApplicationPage("settings", settings_page)
    root = ApplicationSection(
        "example",
        application_shell,
        (
            ApplicationSection(
                "account",
                account_section,
                (
                    ApplicationSection(
                        "preferences",
                        preferences_section,
                        (settings,),
                    ),
                ),
            ),
        ),
    )
    application = PyJSApplication(root, name="example")

    response = application.response(
        RequestFactory().get("/settings/"),
        settings(),
        title="Settings · Example",
    )

    assert response.content.decode() == (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"/>'
        '<meta content="width=device-width, initial-scale=1" name="viewport"/>'
        '<title>Settings · Example</title>'
        '<link href="/assets/example/app.account.preferences.settings.js" '
        'rel="modulepreload"/>'
        '<link href="/assets/example/app.css" rel="stylesheet"/>'
        '<meta content="test-csrf-token" name="csrf-token"/></head>'
        '<body><main id="application"><section><nav>Account</nav>'
        '<div data-section="preferences"><section>Settings</section></div>'
        '</section></main><script src="/assets/example/'
        'app.account.preferences.settings.js" type="module"> </script>'
        "</body></html>"
    )


def test_rendered_page_passes_request_scoped_arguments_to_the_shell():
    dashboard = ApplicationPage("dashboard", dashboard_page)
    application = PyJSApplication(
        authenticated_application_shell,
        name="example",
        layout_id="example",
        mounts=(dashboard,),
    )

    response = application.response(
        RequestFactory().get("/"),
        dashboard(),
        title="Dashboard · Example",
        shell_args=("operator", CSRF_TOKEN),
    )
    source = response.content.decode()

    assert '<main data-user="operator">' in source
    assert (
        '<input name="csrfmiddlewaretoken" type="hidden" '
        'value="test-csrf-token"/>'
    ) in source


def test_navigation_fragment_does_not_rerender_request_scoped_shell():
    dashboard = ApplicationPage("dashboard", dashboard_page)
    application = PyJSApplication(
        authenticated_application_shell,
        name="example",
        layout_id="example",
        mounts=(dashboard,),
    )

    response = application.response(
        RequestFactory().get(
            "/",
            headers={NAVIGATION_HEADER: "1"},
        ),
        dashboard(),
        title="Dashboard · Example",
        shell_args=("operator", CSRF_TOKEN),
    )
    source = response.content.decode()

    assert "operator" not in source
    assert "csrfmiddlewaretoken" not in source
    assert "Dashboard" in source


def test_rendered_page_automatically_returns_a_navigation_fragment():
    settings = ApplicationPage("settings", settings_page)
    application = PyJSApplication(
        application_shell,
        name="example",
        layout_id="example",
        mounts=(
            ApplicationSection(
                "account",
                account_section,
                (settings,),
            ),
        ),
    )

    response = application.response(
        RequestFactory().get(
            "/settings/",
            headers={NAVIGATION_HEADER: "1"},
        ),
        settings(),
        title="Settings · Example",
    )

    assert response.headers["Vary"] == NAVIGATION_HEADER
    assert response.content.decode() == (
        "<div><title>Settings · Example</title>"
        '<div data-pyjs-layout="example" data-pyjs-page="" '
        'data-pyjs-bundle="/assets/example/app.account.settings.js">'
        "<section><nav>Account</nav><section>Settings</section></section>"
        "</div></div>"
    )


def test_application_nodes_must_form_an_unambiguous_tree():
    dashboard = ApplicationPage("dashboard", dashboard_page)

    with pytest.raises(
        ValueError,
        match="Application node name 'dashboard' is duplicated under 'app'",
    ):
        PyJSApplication(
            main,
            name="example",
            mounts=(dashboard, ApplicationPage("dashboard", settings_page)),
        )

    with pytest.raises(
        ValueError,
        match="Application node 'dashboard' may only be mounted once",
    ):
        PyJSApplication(
            main,
            name="example",
            mounts=(
                ApplicationSection("first", account_section, (dashboard,)),
                ApplicationSection("second", preferences_section, (dashboard,)),
            ),
        )

    with pytest.raises(
        ValueError,
        match="Each application node requires a distinct entry point",
    ):
        PyJSApplication(
            main,
            name="example",
            mounts=(
                ApplicationSection("first", account_section),
                ApplicationSection("second", account_section),
            ),
        )

    with pytest.raises(
        ValueError,
        match="An application section root already defines its mounted children",
    ):
        PyJSApplication(
            ApplicationSection("root", application_shell, (dashboard,)),
            name="example",
            mounts=(dashboard,),
        )


def test_build_requires_an_output_for_an_entry_outside_an_installed_app(
    monkeypatch,
):
    monkeypatch.setattr(
        application_module.apps,
        "get_containing_app_config",
        lambda module_name: None,
    )
    application = PyJSApplication(main, name="example")

    with pytest.raises(
        ValueError,
        match=(
            "The PyJS entry point is not inside an installed Django application; "
            r"pass output_directory to build\(\)."
        ),
    ):
        application.build()


def test_response_renders_a_complete_document_with_django_static_urls():
    application = PyJSApplication(
        main,
        name="example",
        head=(tag("meta", {"content": "PyJS", "name": "application-name"}),),
        html_attributes={"class": "h-full", "lang": "en"},
        body_attributes={"class": "min-h-full"},
    )
    request = RequestFactory().get("/account/")

    response = application.response(
        request,
        tag("main", "Account"),
        title="Account · Example",
        head=(tag("meta", {"content": "Account page", "name": "description"}),),
        status=201,
        headers={"X-Application": "example"},
    )

    assert response.status_code == 201
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert response.headers["X-Application"] == "example"
    assert response.content.decode() == (
        '<!doctype html>\n<html class="h-full" lang="en"><head>'
        '<meta charset="utf-8"/><meta content="width=device-width, '
        'initial-scale=1" name="viewport"/><title>Account · Example</title>'
        '<link href="/assets/example/app.js" rel="modulepreload"/>'
        '<link href="/assets/example/app.css" rel="stylesheet"/>'
        '<meta content="PyJS" name="application-name"/>'
        '<meta content="test-csrf-token" name="csrf-token"/>'
        '<meta content="Account page" name="description"/></head>'
        '<body class="min-h-full"><main>Account</main>'
        '<script src="/assets/example/app.js" type="module"> </script>'
        "</body></html>"
    )


def test_development_reload_script_is_opt_in_per_application():
    application = PyJSApplication(
        main,
        name="example",
        development_reload_url="/__pyjs__/reload.js",
    )

    response = application.response(
        RequestFactory().get("/"),
        tag("main", "Application"),
        title="Example",
    )

    assert (
        '<script src="/__pyjs__/reload.js" type="module"> </script>'
        in response.content.decode()
    )


@override_settings(DEBUG=True)
def test_development_reload_client_detects_disconnects_and_generations(
    monkeypatch,
):
    monkeypatch.setattr(development_module, "_generation", "process-generation")

    response = development_reload_script(RequestFactory().get("/reload.js"))
    source = response.content.decode()

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-PyJS-Generation"] == "process-generation"
    assert 'const generation = "process-generation";' in source
    assert 'eventsUrl.searchParams.set("events", "");' in source
    assert "new EventSource(eventsUrl)" in source
    assert "new WebSocket(socketUrl)" in source
    assert 'socket.addEventListener("close"' in source
    assert "window.setTimeout(connectSocket, 500)" in source
    assert 'source.addEventListener("generation"' in source
    assert "generationChanged(JSON.parse(event.data))" in source
    assert "window.location.reload();" in source
    assert "setInterval" not in source
    assert "fetch(" not in source
    assert development_reload_script(
        RequestFactory().head("/reload.js")
    ).status_code == 200


@override_settings(DEBUG=True)
def test_development_reload_websocket_cooperates_with_asgi_disconnects(
    monkeypatch,
):
    async def scenario():
        monkeypatch.setattr(development_module, "_generation", "generation")
        received = iter(
            (
                {"type": "websocket.connect"},
                {"type": "websocket.disconnect", "code": 1012},
            )
        )
        sent = []

        async def receive():
            return next(received)

        async def send(message):
            sent.append(message)

        async def downstream(scope, receive, send):
            raise AssertionError("reload sockets must not reach Django")

        application = development_reload_application(
            downstream,
            "/reload.js",
        )
        await application(
            {"type": "websocket", "path": "/reload.js"},
            receive,
            send,
        )

        assert sent == [
            {"type": "websocket.accept"},
            {"type": "websocket.send", "text": '"generation"'},
        ]

    asyncio.run(scenario())


def test_development_reload_asgi_wrapper_delegates_other_requests():
    async def scenario():
        calls = []

        async def downstream(scope, receive, send):
            calls.append(scope)

        application = development_reload_application(
            downstream,
            "/reload.js",
        )
        scope = {"type": "http", "path": "/reload.js"}
        await application(scope, None, None)

        assert calls == [scope]

    asyncio.run(scenario())


@override_settings(DEBUG=True)
def test_development_reload_events_use_one_async_stream(monkeypatch):
    async def scenario():
        monkeypatch.setattr(development_module, "_generation", "first")
        monkeypatch.setattr(
            development_module,
            "DEVELOPMENT_RELOAD_INTERVAL_SECONDS",
            0,
        )
        response = development_reload_script(
            AsyncRequestFactory().get("/reload.js?events=")
        )
        stream = response.streaming_content

        assert response.status_code == 200
        assert response.headers["Content-Type"] == "text/event-stream"
        assert response.headers["Cache-Control"] == (
            "no-cache, no-store, no-transform"
        )
        assert response.headers["X-Accel-Buffering"] == "no"
        assert response.is_async is True
        assert await anext(stream) == b"retry: 500\n\n"
        assert await anext(stream) == b'event: generation\ndata: "first"\n\n'

        monkeypatch.setattr(development_module, "_generation", "second")
        assert await anext(stream) == b'event: generation\ndata: "second"\n\n'
        await stream.aclose()

    asyncio.run(scenario())


@override_settings(DEBUG=True)
def test_development_reload_events_use_a_sync_stream_for_wsgi(monkeypatch):
    monkeypatch.setattr(development_module, "_generation", "first")
    monkeypatch.setattr(
        development_module,
        "DEVELOPMENT_RELOAD_INTERVAL_SECONDS",
        0,
    )
    response = development_reload_script(
        RequestFactory().get("/reload.js?events=")
    )
    stream = response.streaming_content

    assert response.is_async is False
    assert next(stream) == b"retry: 500\n\n"
    assert next(stream) == b'event: generation\ndata: "first"\n\n'
    response.close()


@override_settings(DEBUG=False)
def test_development_reload_client_is_unavailable_outside_debug_mode():
    response = development_reload_script(RequestFactory().get("/reload.js"))

    assert response.status_code == 404
