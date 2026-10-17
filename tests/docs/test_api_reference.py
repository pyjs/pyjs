import json
import zlib
from pathlib import Path

import pytest

from pyjs.docs.api_extraction import extract_api
from pyjs.docs.builder import build
from pyjs.docs.cli import _print_api_coverage
from pyjs.docs.config import load_config


def write_api_project(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "acme"

[project.urls]
Source = "https://github.com/example/acme"

[tool.pyjs.docs]
api = ["acme"]
""".strip(),
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text("# Acme\n\nThe Acme guide.", encoding="utf-8")
    package = tmp_path / "acme"
    package.mkdir()
    (package / "models.py").write_text(
        '''
from dataclasses import dataclass


@dataclass
class Record:
    """A stored record."""

    name: str


def models() -> list[Record]:
    """Return every model."""
    return []
'''.strip(),
        encoding="utf-8",
    )
    (package / "__init__.py").write_text(
        '''
"""Typed access to Acme records."""

from .models import Record as Record
from .models import models as models

__all__ = ["Client", "Record", "find", "models"]


class Client:
    """Read records from Acme."""

    def load(
        self,
        record: Record | None,
        *,
        limit: int = 10,
    ) -> list[Record]:
        """Load records related to an optional starting record.

        Args:
            record: Starting record, if one is known.
            limit: Maximum number of records to return.

        Returns:
            Matching records in source order.

        Raises:
            ValueError: If ``limit`` is negative.
        """
        return []

    @load.analyze
    def load(call):
        return call

    def _connect(self):
        pass


async def find(name: str) -> Record | None:
    """Find one record by name."""
    return None


class Hidden:
    pass
'''.strip(),
        encoding="utf-8",
    )


@pytest.mark.pyjs_python
def test_extract_api_uses_exports_and_preserves_linkable_types(tmp_path):
    write_api_project(tmp_path)

    reference = extract_api(tmp_path, ("acme",))

    module = reference.modules[0]
    assert module.name == "acme"
    assert [member.name for member in module.members] == [
        "Client",
        "Record",
        "find",
        "models",
    ]
    client, record, find, models = module.members
    assert client.kind == "class"
    assert [member.name for member in client.members] == ["load"]
    load = client.members[0]
    assert [parameter.name for parameter in load.signature.parameters] == [
        "record",
        "limit",
    ]
    assert load.signature.parameters[0].annotation.text == "Record | None"
    assert [
        part.target for part in load.signature.parameters[0].annotation.parts
    ] == ["acme.models.Record", "", ""]
    assert load.signature.returns.text == "list[Record]"
    assert [section.kind for section in load.doc] == [
        "text",
        "parameters",
        "returns",
        "raises",
    ]
    assert [item.name for item in load.doc[1].items] == ["record", "limit"]
    assert record.canonical_path == "acme.models.Record"
    assert [parameter.name for parameter in record.signature.parameters] == ["name"]
    assert find.signature.asynchronous is True
    assert models.kind == "function"


@pytest.mark.pyjs_python
def test_build_adds_linked_searchable_api_reference_pages(tmp_path):
    write_api_project(tmp_path)

    output = build(load_config(tmp_path))

    reference = (output / "reference" / "acme" / "index.html").read_text(
        encoding="utf-8"
    )
    home = (output / "index.html").read_text(encoding="utf-8")
    assert '<h1 class="page-title" id="acme">acme</h1>' in reference
    assert (
        '<p class="page-description">Typed access to Acme records.</p>'
        in reference
    )
    assert (
        '<div class="docs-content"><p>Typed access to Acme records.</p>'
        not in reference
    )
    assert '<span class="api-kind">class</span>' in reference
    assert 'id="api-client"' in reference
    assert 'id="api-client-load"' in reference
    assert 'href="#api-record">Record</a> | None' in reference
    assert "Parameters" in reference
    assert "Starting record, if one is known." in reference
    assert "Hidden" not in reference
    assert "_connect" not in reference
    assert (
        "https://github.com/example/acme/blob/main/acme/__init__.py#L"
        in reference
    )
    assert 'href="reference/acme/">acme</a>' in home
    search = (output / "_pyjs" / "search.json").read_text(encoding="utf-8")
    assert '"title":"acme.Client.load"' in search
    inventory = (output / "objects.inv").read_bytes()
    header, compressed = inventory.split(
        b"# The remainder of this file is compressed using zlib.\n",
        1,
    )
    assert header == (
        b"# Sphinx inventory version 2\n"
        b"# Project: Acme\n"
        b"# Version: 0\n"
    )
    assert zlib.decompress(compressed).decode().splitlines() == [
        "acme py:module 1 reference/acme/ -",
        "acme.Client py:class 1 reference/acme/#api-client -",
        "acme.Client.load py:method 1 reference/acme/#api-client-load -",
        "acme.Record py:class 1 reference/acme/#api-record -",
        "acme.Record.name py:attribute 1 reference/acme/#api-record-name -",
        "acme.find py:function 1 reference/acme/#api-find -",
        "acme.models py:function 1 reference/acme/#api-models -",
    ]
    assert json.loads(
        (output / "_pyjs" / "api-coverage.json").read_text(encoding="utf-8")
    ) == {
        "modules": 1,
        "symbols": 6,
        "documented": 5,
        "undocumented": ["acme.Record.name"],
    }


@pytest.mark.pyjs_python
def test_reference_anchors_disambiguate_case_insensitive_names(tmp_path):
    write_api_project(tmp_path)
    package = tmp_path / "acme" / "__init__.py"
    package.write_text(
        '''
__all__ = ["Page", "page"]


class Page:
    pass


def page():
    pass
'''.strip(),
        encoding="utf-8",
    )

    output = build(load_config(tmp_path))
    reference = (output / "reference" / "acme" / "index.html").read_text(
        encoding="utf-8"
    )

    assert reference.count('id="api-page-class"') == 1
    assert reference.count('id="api-page-function"') == 1


@pytest.mark.pyjs_python
def test_cli_reports_api_docstring_coverage(tmp_path, capsys):
    write_api_project(tmp_path)
    output = build(load_config(tmp_path))

    _print_api_coverage(output)

    assert capsys.readouterr().out == (
        "API reference: 5/6 public symbols documented across 1 module\n"
        f"API coverage details: {output / '_pyjs' / 'api-coverage.json'}\n"
    )


@pytest.mark.pyjs_python
def test_extract_api_reports_an_unresolved_explicit_export(tmp_path):
    write_api_project(tmp_path)
    init = tmp_path / "acme" / "__init__.py"
    init.write_text(
        init.read_text(encoding="utf-8").replace(
            '"find", "models"]',
            '"find", "models", "missing"]',
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=(
            "acme exports names that static analysis could not resolve: "
            "missing"
        ),
    ):
        extract_api(tmp_path, ("acme",))
