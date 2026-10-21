"""Imported Python records and dormant browser state in native SSR."""

import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_navigation_response_and_dialog_preserve_python_rendering(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from datetime import UTC
from enum import IntEnum, StrEnum
from pathlib import Path
from pyjs.server import LiveSession, NavigationPage
from pyjs.web.domx import div
from pyjs.web.ssr import render_html
from pyjs.web.ui import Widget
from pyjs.web.ui.dialog import Dialog, DialogContent, DialogTrigger

class Status(IntEnum):
    OK = 200

class Title(StrEnum):
    EXAMPLE = "Example"

class Panel(Widget):
    session: LiveSession
    def __init__(self):
        super().__init__()
        self.add(div("Ready"))

def main() -> str:
    panel = Panel()
    dialog = Dialog(DialogTrigger("Open"), DialogContent("Details", panel))
    response = NavigationPage(div(dialog), str(Title.EXAMPLE), int(Status.OK))
    assert response.headers == {}
    assert response.status == 200
    assert response.title == "Example"
    other = NavigationPage(div("Second"), "Other", 201, {"X-Example": "yes"})
    assert other.headers["X-Example"] == "yes"
    assert other.status == 201
    return render_html(response.body)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert 'data-slot="dialog"' in result.native.stdout
    assert result.native.stderr == ""


def test_unused_partial_stdlib_imports_do_not_prevent_compilation(tmp_path):
    result = LLVM().assert_matches_python('''
from datetime import UTC, date
from pathlib import Path, PurePosixPath

def unrelated_host_code() -> str:
    return Path(".").resolve().as_posix()

def main() -> str:
    return str(date(2026, 1, 2)) + ":" + str(PurePosixPath("a", "b"))
''', directory=tmp_path)
    assert result.native.stdout == "2026-01-02:a/b"
