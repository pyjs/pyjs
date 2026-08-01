import re
from pathlib import Path

import markdown
import yaml

from .models import Heading

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
DESCRIPTION = re.compile(r"<p>(.*?)</p>", re.DOTALL)
TAGS = re.compile(r"<[^>]+>")


def parse_document(path: Path) -> tuple[dict, str]:
    source = path.read_text(encoding="utf-8")
    match = FRONT_MATTER.match(source)
    if match is None:
        return {}, source
    metadata = yaml.safe_load(match.group(1)) or {}
    if not isinstance(metadata, dict):
        raise ValueError(f"{path}: front matter must be a mapping")
    return metadata, source[match.end() :]


def render_markdown(source: str) -> tuple[str, list[Heading], str]:
    renderer = markdown.Markdown(
        extensions=[
            "admonition",
            "attr_list",
            "codehilite",
            "fenced_code",
            "footnotes",
            "md_in_html",
            "sane_lists",
            "tables",
            "toc",
        ],
        extension_configs={
            "codehilite": {
                "css_class": "highlight",
                "guess_lang": False,
                "linenums": False,
            },
            "toc": {"permalink": True, "toc_depth": "2-4"},
        },
        output_format="html",
    )
    html = renderer.convert(source)
    headings = []

    def collect(tokens):
        for token in tokens:
            headings.append(Heading(token["id"], TAGS.sub("", token["name"]), token["level"]))
            collect(token.get("children", []))

    collect(renderer.toc_tokens)
    description_match = DESCRIPTION.search(html)
    description = ""
    if description_match is not None:
        description = TAGS.sub("", description_match.group(1)).strip()
    return html, headings, description
