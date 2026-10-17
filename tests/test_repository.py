import json
import subprocess
import tomllib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

import pytest
from markdown import markdown as render_markdown

ROOT = Path(__file__).parents[1]


class MarkdownLinks(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.targets = []
        self.feed(render_markdown(text, extensions=["fenced_code"]))

    def handle_starttag(self, tag, attrs):
        attribute = {"a": "href", "img": "src"}.get(tag)
        if attribute is not None:
            target = dict(attrs).get(attribute)
            if target:
                self.targets.append(target)


def test_markdown_links_ignore_code_and_expand_references():
    document = '''
`list[int](values)` is code, not a link.

```python
items = list[int](values)
```

[Guide][guide] and ![Example](example.png "An example").

[guide]: guide.md#section
'''
    assert MarkdownLinks(document).targets == ["guide.md#section", "example.png"]


def public_markdown_files():
    paths = subprocess.run(
        [
            "git",
            "ls-files",
            "--",
            "*.md",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    ).stdout.splitlines()
    return [ROOT / path for path in paths if path.endswith(".md")]


@pytest.mark.parametrize(
    "markdown",
    public_markdown_files(),
    ids=lambda path: str(path.relative_to(ROOT)),
)
def test_repository_markdown_local_links_resolve(markdown):
    for link in MarkdownLinks(markdown.read_text(encoding="utf-8")).targets:
        target = link.split("#", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        destination = (markdown.parent / unquote(target)).resolve()
        assert destination.exists(), f"{markdown}: missing {target}"
        assert destination.is_relative_to(ROOT), (
            f"{markdown}: {target} leaves the repository"
        )


def test_public_project_urls_reference_published_surfaces():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    examples = tomllib.loads(
        (ROOT / "examples" / "pyproject.toml").read_text(encoding="utf-8")
    )
    extras = tomllib.loads(
        (ROOT / "extras" / "pyproject.toml").read_text(encoding="utf-8")
    )
    npm_cli = json.loads(
        (ROOT / "npm" / "cli" / "package.json").read_text(encoding="utf-8")
    )
    npm_runtime = (
        ROOT / "npm" / "runtime" / "package.json.template"
    ).read_text(encoding="utf-8")

    assert project["project"]["urls"] == {
        "Homepage": "https://github.com/pyjs/pyjs",
        "Release notes": "https://github.com/pyjs/pyjs/releases",
        "Source": "https://github.com/pyjs/pyjs",
        "Tracker": "https://github.com/pyjs/pyjs/issues",
        "Discord": "https://discord.gg/YktKpQPG7",
        "X": "https://x.com/pyjsdev",
    }
    assert examples["project"]["urls"] == {
        "Homepage": "https://github.com/pyjs/pyjs",
        "Source": "https://github.com/pyjs/pyjs",
    }
    assert extras["project"]["urls"] == {
        "Homepage": "https://github.com/pyjs/pyjs",
        "Source": "https://github.com/pyjs/pyjs",
    }
    assert npm_cli["homepage"] == "https://github.com/pyjs/pyjs"
    assert '"homepage": "https://github.com/pyjs/pyjs"' in npm_runtime


def test_examples_test_extra_can_collect_every_shipped_example():
    project = tomllib.loads(
        (ROOT / "examples" / "pyproject.toml").read_text(encoding="utf-8")
    )
    extras = project["project"]["optional-dependencies"]

    assert set(extras["store"]).issubset(extras["test"])
    assert "pytest>=9.0" in extras["test"]


def test_contributor_and_release_tools_are_in_the_repository():
    for path in (
        "CONTRIBUTING.md",
        "tests/backend_semantics.py",
        "scripts/update_webidl.py",
        "scripts/generate_native_unicode.py",
        "npm/scripts/release.py",
        "npm/tests/smoke_test.py",
    ):
        assert (ROOT / path).is_file(), path
