import html
import json
import posixpath
import re
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .api import (
    ApiCoverage,
    ApiDocSection,
    ApiModule,
    ApiObject,
    ApiParameter,
    ApiReference,
    ApiSignature,
    ApiType,
    ApiTypeParameter,
)
from .api_extraction import extract_api
from .config import DocsConfig
from .markdown import render_markdown
from .models import Heading, Page, SearchEntry

ANCHOR_CHARACTER = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class _SymbolTarget:
    relative_path: Path
    anchor: str


@dataclass(frozen=True)
class ApiDocumentation:
    pages: tuple[Page, ...]
    inventory: bytes
    coverage: ApiCoverage

    def coverage_json(self) -> str:
        return json.dumps(
            {
                "modules": self.coverage.modules,
                "symbols": self.coverage.symbols,
                "documented": self.coverage.documented,
                "undocumented": list(self.coverage.undocumented),
            },
            indent=2,
        ) + "\n"


def _module_relative_path(name: str) -> Path:
    return Path("reference", *name.split("."), "index.md")


def _anchor(module: str, path: str) -> str:
    relative = path.removeprefix(module).strip(".") or module
    slug = ANCHOR_CHARACTER.sub("-", relative.lower()).strip("-")
    return f"api-{slug}"


def _walk(values: tuple[ApiObject, ...]):
    for value in values:
        yield value
        yield from _walk(value.members)


class _SymbolIndex:
    def __init__(self, reference: ApiReference):
        self.targets = {}
        self.anchors = {}
        for module in reference.modules:
            relative_path = _module_relative_path(module.name)
            self.targets[module.name] = _SymbolTarget(relative_path, "")
            values = tuple(_walk(module.members))
            base_anchors = Counter(
                _anchor(module.name, value.path) for value in values
            )
            candidates = {}
            for value in values:
                base_anchor = _anchor(module.name, value.path)
                if base_anchors[base_anchor] > 1:
                    kind = ANCHOR_CHARACTER.sub("-", value.kind.lower()).strip("-")
                    base_anchor = f"{base_anchor}-{kind}"
                candidates[value.path] = base_anchor
            candidate_counts = Counter(candidates.values())
            for value in values:
                anchor = candidates[value.path]
                if candidate_counts[anchor] > 1:
                    checksum = zlib.crc32(value.path.encode())
                    anchor = f"{anchor}-{checksum:08x}"
                self.anchors[(module.name, value.path)] = anchor
                target = _SymbolTarget(
                    relative_path,
                    anchor,
                )
                self.targets[value.path] = target
                self.targets.setdefault(value.canonical_path, target)

    def anchor(self, module: ApiModule, value: ApiObject) -> str:
        return self.anchors[(module.name, value.path)]

    def href(self, current: ApiModule, path: str) -> str:
        target = self.targets.get(path)
        if target is None:
            return _external_url(path)
        current_dir = _module_relative_path(current.name).parent.as_posix()
        target_dir = target.relative_path.parent.as_posix()
        relative = posixpath.relpath(target_dir, current_dir)
        href = "" if relative == "." else relative.rstrip("/") + "/"
        return href + (f"#{target.anchor}" if target.anchor else "")


def _external_url(path: str) -> str:
    if path in {"str", "int", "float", "bool", "list", "tuple", "dict", "set"}:
        return f"https://docs.python.org/3/library/stdtypes.html#{path}"
    if path in {"object", "type"}:
        return f"https://docs.python.org/3/library/functions.html#{path}"
    if path.startswith("collections.abc."):
        return (
            "https://docs.python.org/3/library/collections.abc.html#"
            f"{path}"
        )
    if path.startswith("typing."):
        return f"https://docs.python.org/3/library/typing.html#{path}"
    return ""


def _type(value: ApiType | None, module: ApiModule, index: _SymbolIndex) -> str:
    if value is None:
        return ""
    parts = []
    for part in value.parts:
        source = html.escape(part.text)
        href = index.href(module, part.target) if part.target else ""
        if href:
            source = (
                f'<a class="api-type-link" href="{html.escape(href, quote=True)}">'
                f"{source}</a>"
            )
        parts.append(source)
    return "".join(parts)


def _type_parameter(
    value: ApiTypeParameter,
    module: ApiModule,
    index: _SymbolIndex,
) -> str:
    prefix = {"param-spec": "**", "type-var-tuple": "*"}.get(value.kind, "")
    source = prefix + html.escape(value.name)
    if value.bound is not None:
        source += f": {_type(value.bound, module, index)}"
    if value.default is not None:
        source += f" = {_type(value.default, module, index)}"
    return source


def _parameter(
    value: ApiParameter,
    module: ApiModule,
    index: _SymbolIndex,
) -> str:
    prefix = {
        "variadic positional": "*",
        "variadic keyword": "**",
    }.get(value.kind, "")
    source = prefix + html.escape(value.name)
    if value.annotation is not None:
        source += f": {_type(value.annotation, module, index)}"
    if value.default is not None and not value.kind.startswith("variadic"):
        source += f" = {html.escape(value.default)}"
    return source


def _parameters(
    signature: ApiSignature,
    module: ApiModule,
    index: _SymbolIndex,
) -> str:
    values = []
    positional_only = sum(
        parameter.kind == "positional-only"
        for parameter in signature.parameters
    )
    has_variadic = any(
        parameter.kind == "variadic positional"
        for parameter in signature.parameters
    )
    inserted_keyword_separator = False
    for parameter_index, parameter in enumerate(signature.parameters, start=1):
        if (
            parameter.kind == "keyword-only"
            and not has_variadic
            and not inserted_keyword_separator
        ):
            values.append("*")
            inserted_keyword_separator = True
        values.append(_parameter(parameter, module, index))
        if parameter_index == positional_only:
            values.append("/")
    return ", ".join(values)


def _signature(
    value: ApiObject,
    module: ApiModule,
    index: _SymbolIndex,
) -> str:
    if value.signature is None:
        source = html.escape(value.name)
        if value.annotation is not None:
            source += f": {_type(value.annotation, module, index)}"
        if value.value is not None:
            source += f" = {html.escape(value.value)}"
        return source
    type_parameters = ""
    if value.signature.type_parameters:
        rendered = (
            _type_parameter(parameter, module, index)
            for parameter in value.signature.type_parameters
        )
        type_parameters = "[" + ", ".join(rendered) + "]"
    parameters = _parameters(value.signature, module, index)
    if value.kind == "class":
        prefix = "class "
    else:
        prefix = "async def " if value.signature.asynchronous else "def "
    source = f"{prefix}{html.escape(value.name)}{type_parameters}({parameters})"
    if value.signature.returns is not None:
        source += f" -&gt; {_type(value.signature.returns, module, index)}"
    return source


def _markdown(source: str) -> str:
    return render_markdown(source)[0] if source.strip() else ""


def _doc_section(
    section: ApiDocSection,
    module: ApiModule,
    index: _SymbolIndex,
) -> str:
    if section.kind == "text":
        return _markdown(section.text)
    title = f"<h5>{html.escape(section.title)}</h5>" if section.title else ""
    if section.items:
        items = []
        for item in section.items:
            name = html.escape(item.name)
            annotation = _type(item.annotation, module, index)
            if annotation and annotation != name:
                name += f' <span class="api-doc-type">{annotation}</span>'
            items.append(
                f"<dt><code>{name}</code></dt>"
                f"<dd>{_markdown(item.description)}</dd>"
            )
        return f'{title}<dl class="api-doc-items">{"".join(items)}</dl>'
    if section.kind == "examples":
        return title + _markdown(f"```python\n{section.text}\n```")
    return title + _markdown(section.text)


def _doc(
    sections: tuple[ApiDocSection, ...],
    module: ApiModule,
    index: _SymbolIndex,
    context: str,
) -> str:
    try:
        return "".join(_doc_section(section, module, index) for section in sections)
    except ValueError as error:
        raise ValueError(f"{context}: {error}") from error


def _source_url(value: ApiObject, config: DocsConfig) -> str:
    if not config.repo_url or not value.source_path:
        return ""
    try:
        relative = value.source_path.relative_to(config.project_root).as_posix()
    except ValueError:
        return ""
    lines = f"#L{value.line}"
    if value.end_line != value.line:
        lines += f"-L{value.end_line}"
    return f"{config.repo_url.rstrip('/')}/blob/main/{relative}{lines}"


def _object(
    value: ApiObject,
    module: ApiModule,
    index: _SymbolIndex,
    config: DocsConfig,
    *,
    member: bool = False,
) -> str:
    anchor = index.anchor(module, value)
    level = 4 if member else 3
    source_url = _source_url(value, config)
    source = ""
    if source_url:
        source = (
            f'<a class="api-source" href="{html.escape(source_url, quote=True)}">'
            "Source</a>"
        )
    bases = ""
    if value.bases:
        bases = (
            '<p class="api-bases"><span>Inherits</span> '
            + ", ".join(_type(base, module, index) for base in value.bases)
            + "</p>"
        )
    members = ""
    if value.members:
        members = '<div class="api-members">' + "".join(
            _object(child, module, index, config, member=True)
            for child in value.members
        ) + "</div>"
    documentation = _doc(
        value.doc, module, index, f"{value.source_path} ({value.path})",
    )
    return (
        f'<section class="api-object api-{html.escape(value.kind.replace(" ", "-"))}">'
        f'<div class="api-heading"><span class="api-kind">'
        f"{html.escape(value.kind)}</span>{source}</div>"
        f'<h{level} id="{anchor}"><code>{html.escape(value.name)}</code>'
        f'<a class="headerlink" href="#{anchor}" aria-label="Link to '
        f'{html.escape(value.path, quote=True)}">¶</a></h{level}>'
        f'<pre class="api-signature"><code>{_signature(value, module, index)}'
        f"</code></pre>"
        f"{bases}"
        f'<div class="api-doc">{documentation}</div>'
        f"{members}</section>"
    )


def _module_description(module: ApiModule) -> str:
    for section in module.doc:
        if section.kind == "text" and section.text.strip():
            return section.text.strip().split("\n\n", 1)[0]
    return f"Python API reference for {module.name}."


def _module_doc(module: ApiModule, index: _SymbolIndex) -> str:
    """Render module details without repeating its summary."""
    sections = list(module.doc)
    for position, section in enumerate(sections):
        if section.kind != "text" or not section.text.strip():
            continue
        paragraphs = section.text.strip().split("\n\n", 1)
        if len(paragraphs) == 1:
            sections.pop(position)
        else:
            sections[position] = ApiDocSection(
                kind="text",
                text=paragraphs[1],
            )
        break
    return _doc(tuple(sections), module, index, f"{module.source_path} ({module.name})")


def _module_html(
    module: ApiModule,
    index: _SymbolIndex,
    config: DocsConfig,
) -> tuple[str, list[Heading], tuple[SearchEntry, ...]]:
    module_id = ANCHOR_CHARACTER.sub("-", module.name.lower()).strip("-")
    content = [f'<h1 id="{module_id}">{html.escape(module.name)}</h1>']
    content.append(_module_doc(module, index))
    grouped = defaultdict(list)
    for value in module.members:
        grouped[value.kind].append(value)
    headings = [Heading(module_id, module.name, 1)]
    section_order = (
        ("class", "Classes"),
        ("function", "Functions"),
        ("type alias", "Type aliases"),
        ("attribute", "Attributes"),
        ("module", "Modules"),
    )
    for kind, title in section_order:
        values = grouped.get(kind, ())
        if not values:
            continue
        section_id = ANCHOR_CHARACTER.sub("-", title.lower()).strip("-")
        content.append(
            f'<h2 id="{section_id}">{title}'
            f'<a class="headerlink" href="#{section_id}">¶</a></h2>'
        )
        headings.append(Heading(section_id, title, 2))
        for value in values:
            content.append(_object(value, module, index, config))
            headings.append(
                Heading(index.anchor(module, value), value.name, 3)
            )
    search = tuple(
        SearchEntry(
            title=value.path,
            section=module.name,
            fragment=f"#{index.anchor(module, value)}",
            text=" ".join(
                section.text
                for section in value.doc
                if section.kind == "text"
            )[:240],
        )
        for value in _walk(module.members)
    )
    return "".join(content), headings, search


def _inventory_kind(value: ApiObject, *, member: bool) -> str:
    if value.kind == "class":
        return "py:class"
    if value.kind == "function":
        return "py:method" if member else "py:function"
    return "py:attribute" if member else "py:data"


def _inventory(
    reference: ApiReference,
    config: DocsConfig,
    index: _SymbolIndex,
) -> bytes:
    lines = []
    for module in reference.modules:
        directory = _module_relative_path(module.name).parent.as_posix() + "/"
        lines.append(f"{module.name} py:module 1 {directory} -")
        for value in module.members:
            lines.append(
                f"{value.path} {_inventory_kind(value, member=False)} 1 "
                f"{directory}#{index.anchor(module, value)} -"
            )
            for child in _walk(value.members):
                lines.append(
                    f"{child.path} {_inventory_kind(child, member=True)} 1 "
                    f"{directory}#{index.anchor(module, child)} -"
                )
    version = config.version or "0"
    header = (
        "# Sphinx inventory version 2\n"
        f"# Project: {config.site_name}\n"
        f"# Version: {version}\n"
        "# The remainder of this file is compressed using zlib.\n"
    ).encode()
    return header + zlib.compress(("\n".join(lines) + "\n").encode())


def _coverage(reference: ApiReference) -> ApiCoverage:
    values = [
        value
        for module in reference.modules
        for value in _walk(module.members)
    ]
    undocumented = tuple(value.path for value in values if not value.doc)
    return ApiCoverage(
        modules=len(reference.modules),
        symbols=len(values),
        documented=len(values) - len(undocumented),
        undocumented=undocumented,
    )


def build_api_documentation(config: DocsConfig) -> ApiDocumentation:
    reference = extract_api(config.project_root, config.api_modules)
    index = _SymbolIndex(reference)
    pages = []
    for order, module in enumerate(reference.modules, start=1):
        relative_path = _module_relative_path(module.name)
        route_parts = relative_path.parent.parts
        route = "/" + "/".join(route_parts) + "/"
        if config.route_prefix:
            route = f"/{config.route_prefix.strip('/')}{route}"
        output_path = config.site_dir.joinpath(*route.strip("/").split("/"), "index.html")
        rendered, headings, search = _module_html(module, index, config)
        pages.append(
            Page(
                source_path=module.source_path,
                relative_path=relative_path,
                output_path=output_path,
                route=route,
                title=module.name,
                description=_module_description(module),
                order=900 + order,
                hidden=False,
                html=rendered,
                headings=headings,
                search_entries=search,
            )
        )
    return ApiDocumentation(
        tuple(pages),
        _inventory(reference, config, index),
        _coverage(reference),
    )
