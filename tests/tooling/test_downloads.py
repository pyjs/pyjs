import os

import pytest

from pyjs.javascript.utils import TailwindCSS
from pyjs.tooling.node import Node, Npm

pytestmark = pytest.mark.skipif(
    os.environ.get("PYJS_RUN_DOWNLOAD_TESTS") != "1",
    reason="set PYJS_RUN_DOWNLOAD_TESTS=1 to exercise external tool downloads",
)


def test_tailwind_standalone_download_runs_on_current_platform(tmp_path):
    tailwind = TailwindCSS(cache_directory=tmp_path)
    tailwind.tailwindcss = str(tailwind.install())

    css = tailwind.get_css({"rounded-md"})

    assert css is not None
    assert ".rounded-md" in css


def test_managed_node_and_npm_run_on_current_platform(tmp_path, monkeypatch):
    # sdkmgr reuses the selected provider's store; root only isolates bootstrap.
    # Fresh isolated provider installation is covered by sdkmgr's live smokes.
    monkeypatch.delenv("PYJS_NODE", raising=False)
    node = Node(root=tmp_path / "node")

    result = node.run_javascript("console.log('pyjs-node-ready');")

    assert result.returncode == 0
    assert result.stdout == "pyjs-node-ready\n"

    project = tmp_path / "npm-project"
    Npm(node).install(project, f"tailwindcss@{TailwindCSS.VERSION}")
    assert (project / "node_modules" / "tailwindcss" / "package.json").is_file()
