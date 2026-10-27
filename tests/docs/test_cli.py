from pathlib import Path

import pytest

from pyjs.docs import cli

pytestmark = pytest.mark.pyjs_python


def test_serve_announces_its_url_only_once(tmp_path, monkeypatch, capsys):
    servers = []

    def interrupt(server):
        servers.append(server)
        server._print_listeners()
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "build", lambda config: tmp_path)
    monkeypatch.setattr(cli.Server, "serve_forever", interrupt)

    cli._serve(tmp_path, "127.0.0.1", 0)

    server, = servers
    assert capsys.readouterr().out == (
        f"Built documentation in {tmp_path}\n"
        f"Serving PyJS documentation at {server.url}/\n"
        f"Development UI at {server.url}/_pyjs/\n"
        "\nStopping documentation server.\n"
    )
    assert server._closed


def test_docs_can_mount_live_routes_and_open_them(tmp_path, monkeypatch):
    import sys
    from pyjs.cli import main
    from tests.test_dev_server import request

    monkeypatch.setattr(sys, "path", sys.path[:])

    (tmp_path / "live_docs_extension.py").write_text(
        "def mount(app):\n    app.get('/perf/', lambda request: 'live JSON viewer')\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.md").write_text("# Static documentation\n")
    before = sys.path[:]

    def run(server, *, open_path):
        assert open_path == "/perf/"
        with server:
            assert request(server, "GET", "/perf/")[2] == b"live JSON viewer"
            assert b"Static documentation" in request(server, "GET", "/")[2]

    monkeypatch.setattr(cli.Server, "serve_forever", run)
    try:
        assert main(["docs", "serve", "--project-dir", str(tmp_path),
                     "--host", "127.0.0.1", "--port", "0", "--app",
                     "live_docs_extension:mount", "--open", "/perf/"]) == 0
    finally:
        sys.modules.pop("live_docs_extension", None)
    # The outer CLI prepends cwd; the extension's temporary project path is gone.
    assert sys.path == [str(Path.cwd()), *before]
