from dataclasses import replace
from pathlib import Path

import pytest

from pyjs.cli import main
from pyjs.docs.builder import build
from pyjs.docs.config import DocsVersion, load_config
from pyjs.tooling.node import Node


def write_project(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "sample-sdk"

[project.urls]
Documentation = "https://example.com/docs"
Source = "https://github.com/example/sample-sdk"
Discord = "https://discord.gg/sample-sdk"
X = "https://x.com/sample_sdk"
""".strip(),
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    (docs / "guide").mkdir(parents=True)
    (docs / "index.md").write_text(
        """
---
title: Sample SDK
description: A small documentation fixture.
order: 0
---

# Sample SDK

Read the [guide](guide/index.md) or the [setup page](guide/setup.md#install).

## Overview

The overview is searchable.
""".strip(),
        encoding="utf-8",
    )
    (docs / "guide" / "index.md").write_text(
        """
---
title: Guide
order: 10
---

# Guide

Learn the core workflow.
""".strip(),
        encoding="utf-8",
    )
    (docs / "guide" / "setup.md").write_text(
        """
---
title: Setup
order: 20
---

# Setup

## Install

Run the installer.
""".strip(),
        encoding="utf-8",
    )
    (docs / "private.md").write_text(
        """
---
title: Private draft
hidden: true
---

# Private draft
""".strip(),
        encoding="utf-8",
    )
    (docs / "logo.txt").write_text("asset", encoding="utf-8")


@pytest.mark.pyjs_python
def test_build_creates_clean_routes_navigation_assets_and_search(tmp_path):
    write_project(tmp_path)

    output = build(load_config(tmp_path))

    index = (output / "index.html").read_text(encoding="utf-8")
    guide = (output / "guide" / "index.html").read_text(encoding="utf-8")
    setup = (output / "guide" / "setup" / "index.html").read_text(encoding="utf-8")

    assert "<title>Sample SDK · Sample Sdk</title>" in index
    assert index.count("<h1") == 1
    assert '<h1 class="page-title" id="sample-sdk">Sample SDK</h1>' in index
    assert (
        '<meta property="og:title" content="Sample SDK · Sample Sdk"/>'
        in index
    )
    assert (
        '<meta property="og:description" '
        'content="A small documentation fixture."/>'
        in index
    )
    assert '<meta property="og:site_name" content="Sample Sdk"/>' in index
    assert '<meta name="twitter:card" content="summary"/>' in index
    assert '<meta name="color-scheme" content="dark light"/>' in index
    assert (
        '<meta property="og:url" content="https://example.com/docs/"/>'
        in index
    )
    assert 'href="guide/"' in index
    assert 'href="guide/setup/#install"' in index
    assert 'aria-current="page">Sample SDK</a>' in index
    assert 'href="https://github.com/example/sample-sdk">GitHub</a>' in index
    assert 'href="https://discord.gg/sample-sdk">Discord</a>' in index
    assert 'href="https://x.com/sample_sdk">X</a>' in index
    assert 'aria-current="page">Guide</a>' in guide
    assert 'href="../../_pyjs/docs.css"' in setup
    assert 'data-search-url="_pyjs/search.json"' in index
    assert "Private draft" not in index.split('<main class="docs-main"', 1)[0]
    assert (output / "private" / "index.html").is_file()
    assert (output / "logo.txt").read_text(encoding="utf-8") == "asset"
    assert (output / "_pyjs" / "docs.js").is_file()
    assert (output / "_pyjs" / "docs.js.map").is_file()
    assert (output / "_pyjs" / "docs.css").is_file()
    assert (output / "_pyjs" / "favicon.svg").is_file()
    search = (output / "_pyjs" / "search.json").read_text(encoding="utf-8")
    assert '"title":"Install"' in search
    assert '"url":"/guide/setup/#install"' in search
    javascript = (output / "_pyjs" / "docs.js").read_text(encoding="utf-8")
    assert "this.search_input = document.getElementById" in javascript
    assert "this.search_dialog = document.getElementById" in javascript
    syntax = Node().check_module(javascript)
    assert syntax.returncode == 0, syntax.stderr
    assert (output / "404.html").is_file()
    assert (output / ".nojekyll").is_file()


@pytest.mark.pyjs_python
def test_config_uses_pyproject_defaults_and_optional_docs_overrides(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "acme-tools"

[project.urls]
Documentation = "https://docs.example.com"
Source = "https://github.com/example/acme-tools"

[tool.pyjs.docs]
source = "manual"
output = "public"
site_name = "Acme Tools"
version = "2.4"
api = ["acme.api", "acme.models"]
social_image = "https://cdn.example.com/docs.png"
social_image_alt = "Acme Tools documentation preview"
social_image_width = 1200
social_image_height = 630
x_handle = "@acme_tools"
versions = [
  {label = "Latest", url = "/docs/latest/"},
  {label = "2.4", url = "/docs/2.4/"},
]
""".strip(),
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    assert config.docs_dir == tmp_path / "manual"
    assert config.site_dir == tmp_path / "public"
    assert config.site_name == "Acme Tools"
    assert config.site_url == "https://docs.example.com"
    assert config.repo_name == "acme-tools"
    assert config.version == "2.4"
    assert config.social_image == "https://cdn.example.com/docs.png"
    assert config.social_image_alt == "Acme Tools documentation preview"
    assert config.social_image_width == 1200
    assert config.social_image_height == 630
    assert config.x_handle == "@acme_tools"
    assert config.api_modules == ("acme.api", "acme.models")
    assert [(version.label, version.url) for version in config.versions] == [
        ("Latest", "/docs/latest/"),
        ("2.4", "/docs/2.4/"),
    ]


@pytest.mark.pyjs_python
def test_config_rejects_api_as_one_ambiguous_string(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "acme"

[tool.pyjs.docs]
api = "acme"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="tool.pyjs.docs.api must be a list of module names",
    ):
        load_config(tmp_path)


@pytest.mark.pyjs_python
def test_build_rejects_duplicate_clean_routes(tmp_path):
    write_project(tmp_path)
    (tmp_path / "docs" / "guide.md").write_text("# Duplicate guide", encoding="utf-8")

    with pytest.raises(ValueError, match="both produce the route"):
        build(load_config(tmp_path))


@pytest.mark.pyjs_python
def test_cli_build_uses_the_selected_project_directory(tmp_path, capsys):
    write_project(tmp_path)

    result = main(["docs", "build", "--project-dir", str(tmp_path)])

    assert result == 0
    assert (tmp_path / "site" / "index.html").is_file()
    assert "Built documentation" in capsys.readouterr().out


@pytest.mark.pyjs_python
def test_build_can_mount_documentation_below_a_route_prefix(tmp_path):
    write_project(tmp_path)
    config = replace(load_config(tmp_path), route_prefix="/docs/", version="v1.2")

    output = build(config)

    index = (output / "docs" / "index.html").read_text(encoding="utf-8")
    setup = (output / "docs" / "guide" / "setup" / "index.html").read_text(encoding="utf-8")
    assert 'href="guide/"' in index
    assert '<span class="docs-version">v1.2</span>' in index
    assert 'href="../../../_pyjs/docs.css"' in setup
    assert (output / "docs" / "logo.txt").read_text(encoding="utf-8") == "asset"
    assert not (output / "logo.txt").exists()
    assert not (output / "404.html").exists()


@pytest.mark.pyjs_python
def test_build_adds_version_navigation_that_preserves_the_page_route(tmp_path):
    write_project(tmp_path)
    config = replace(
        load_config(tmp_path),
        route_prefix="/docs/2.4/",
        version="2.4",
        versions=(
            DocsVersion("Latest", "/docs/latest/"),
            DocsVersion("2.4", "/docs/2.4/"),
            DocsVersion("2.3", "/docs/2.3/"),
        ),
    )

    output = build(config)

    setup = (
        output / "docs" / "2.4" / "guide" / "setup" / "index.html"
    ).read_text(encoding="utf-8")
    assert 'class="docs-version-picker"' in setup
    assert 'class="docs-version">2.4</summary>' in setup
    assert 'href="/docs/latest/guide/setup/">Latest</a>' in setup
    assert (
        'href="/docs/2.4/guide/setup/" aria-current="page">2.4</a>'
        in setup
    )
    assert 'href="/docs/2.3/guide/setup/">2.3</a>' in setup
