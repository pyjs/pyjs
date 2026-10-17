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
