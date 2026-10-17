"""Render small documentation diagrams as static, themed SVG.

Use a ``diagram`` fence in Markdown or a docstring's narrative section:

```diagram
sequence "Reading a snapshot"
describe "The browser receives a snapshot before following later updates."
node browser "Browser" accent
node server "Server"
browser -> server "Request snapshot"
server --> browser "Snapshot and cursor"
```

The prototype supports ``flow``, ``sequence``, and ``timeline`` diagrams. Flows may nest
``group`` and ``browser`` blocks in braces, with ``row id ...`` arranging each
block's children. A ``tree`` panel contains ``file "relative/path.py"`` entries.
Use ``card`` for a wireframe content preview and ``highlight`` for a dashed
accent boundary; arrows can target these regions inside browser frames.
Sequences accept ``phase "Label"`` between messages. Timelines declare a unit
(``ms`` or ``s``), then ``span id start end "Task"`` rows. Labels
are plain text, never executable code. ``-->`` draws a dashed arrow.
"""

import hashlib
import math
import re
import shlex
import textwrap
from dataclasses import dataclass, replace
from html import escape


class DiagramError(ValueError):
    def __init__(self, line: int, message: str):
        super().__init__(f"Diagram line {line}: {message}")


@dataclass(frozen=True)
class Node:
    name: str
    label: str
    accent: bool
    kind: str = "node"
    muted: bool = False
    rows: tuple[tuple[str, ...], ...] = ()
    files: tuple[tuple[str, str], ...] = ()
    highlight: bool = False


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    label: str
    dashed: bool


@dataclass(frozen=True)
class Phase:
    before: int
    label: str


@dataclass(frozen=True)
class Span:
    node: str
    start: float
    end: float


@dataclass(frozen=True)
class Diagram:
    kind: str
    title: str
    description: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    rows: tuple[tuple[str, ...], ...]
    phases: tuple[Phase, ...] = ()
    spans: tuple[Span, ...] = ()
    unit: str = ""


def parse_diagram(source: str) -> Diagram:
    if len(source) > 20_000:
        raise DiagramError(1, "source exceeds 20,000 characters")
    kind = title = description = ""
    nodes = {}
    edges = []
    phases = []
    spans = []
    unit = ""
    file_count = 0
    stack = [""]
    children = {"": []}
    parents = {}
    rows = {"": []}
    references = []
    placed = {}
    for line, raw in enumerate(source.splitlines(), 1):
        try:
            words = shlex.split(raw, comments=True)
        except ValueError as error:
            raise DiagramError(line, str(error)) from error
        if not words:
            continue
        parent = stack[-1]
        if not kind:
            if len(words) == 3 and words[0] == "timeline":
                kind, title, unit = words
                if unit not in {"ms", "s"}:
                    raise DiagramError(line, "timeline unit must be ms or s")
            elif len(words) == 2 and words[0] in {"flow", "sequence"}:
                kind, title = words
            else:
                raise DiagramError(line, 'start with flow "Title", sequence "Title", or timeline "Title" ms')
            if not title.strip():
                raise DiagramError(line, "title must not be empty")
        elif kind == "timeline" and words[0] not in {"span", "describe"}:
            raise DiagramError(line, 'timelines accept span identifier start end "Label" [accent|muted] or describe')
        elif parent and nodes[parent].kind == "tree" and words[0] not in {"file", "}"}:
            raise DiagramError(line, 'tree panels accept only file "relative/path" [accent|muted] entries')
        elif words == ["}"]:
            if len(stack) == 1:
                raise DiagramError(line, "unexpected closing brace")
            stack.pop()
        elif len(words) in {3, 4} and words[1] in {"->", "-->"}:
            start, arrow, end, *label = words
            if start == end:
                raise DiagramError(line, "self-arrows are not supported in this prototype")
            edges.append(Edge(start, end, label[0] if label else "", arrow == "-->"))
            references.extend(((line, start), (line, end)))
        elif words[0] == "describe" and len(words) == 2:
            if description:
                raise DiagramError(line, "describe may appear only once")
            description = words[1]
            if not description.strip():
                raise DiagramError(line, "description must not be empty")
        elif words[0] == "file":
            if not parent or nodes[parent].kind != "tree":
                raise DiagramError(line, "file entries require a tree panel")
            if len(words) not in {2, 3} or (len(words) == 3 and words[2] not in {"accent", "muted"}):
                raise DiagramError(line, 'expected file "relative/path" [accent|muted]')
            path = words[1]
            parts = path.split("/")
            if len(parts) > 8 or any(not part.strip() or part in {".", ".."} for part in parts) or "\\" in path:
                raise DiagramError(line, "file paths need 1 to 8 relative slash-separated names, without . or ..")
            panel = nodes[parent]
            if any(path == other or path.startswith(other + "/") or other.startswith(path + "/") for other, _ in panel.files):
                raise DiagramError(line, f"duplicate file or file/directory conflict: {path!r}")
            file_count += 1
            if file_count > 64:
                raise DiagramError(line, "limit diagrams to 64 file entries")
            nodes[parent] = replace(panel, files=panel.files + ((path, words[2] if len(words) == 3 else ""),))
        elif words[0] in {"node", "card", "group", "browser", "tree", "span"}:
            node_kind = words[0]
            if node_kind == "card" and kind != "flow":
                raise DiagramError(line, "cards require a flow diagram")
            container = node_kind in {"group", "browser", "tree"}
            if node_kind == "span":
                if kind != "timeline":
                    raise DiagramError(line, "span is only available in timeline diagrams")
                if len(words) not in {5, 6}:
                    raise DiagramError(line, 'expected span identifier start end "Label" [accent|muted]')
                try:
                    start, end = map(float, words[2:4])
                except ValueError as error:
                    raise DiagramError(line, "span times must be finite numbers with 0 <= start < end <= 1e9") from error
                if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= 1e9):
                    raise DiagramError(line, "span times must be finite numbers with 0 <= start < end <= 1e9")
                spans.append(Span(words[1], start, end))
                words = words[:2] + words[4:]
            if container:
                if kind != "flow":
                    raise DiagramError(line, "groups, browsers, and trees require a flow diagram")
                if words[-1] != "{":
                    raise DiagramError(line, "open a group, browser, or tree with {")
                words = words[:-1]
                if len(stack) >= 5:
                    raise DiagramError(line, "containers may be nested at most four levels")
            if len(words) not in {3, 4}:
                raise DiagramError(line, 'expected node identifier "Label" [accent|muted|highlight]')
            _, name, label, *style = words
            if not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", name):
                raise DiagramError(line, f"invalid node identifier {name!r}")
            if name in nodes:
                raise DiagramError(line, f"duplicate node {name!r}")
            if not label.strip():
                raise DiagramError(line, "node label must not be empty")
            if style and style[0] not in {"accent", "muted", "highlight"}:
                raise DiagramError(line, "node style must be accent, muted, or highlight")
            if style == ["highlight"] and kind != "flow":
                raise DiagramError(line, "highlight is only available in flow diagrams")
            nodes[name] = Node(
                name, label, style in (["accent"], ["highlight"]), node_kind,
                style == ["muted"], highlight=style == ["highlight"],
            )
            children[parent].append(name)
            parents[name] = parent
            if container:
                children[name] = []
                rows[name] = []
                stack.append(name)
        elif words[0] == "phase" and len(words) == 2:
            if kind != "sequence":
                raise DiagramError(line, "phase is only available in sequence diagrams")
            if not words[1].strip():
                raise DiagramError(line, "phase label must not be empty")
            phases.append(Phase(len(edges), words[1]))
        elif words[0] == "row" and len(words) > 1:
            if kind != "flow":
                raise DiagramError(line, "row is only available in flow diagrams")
            for name in words[1:]:
                if name in placed:
                    raise DiagramError(line, f"node {name!r} appears in more than one row")
                placed[name] = parent
                references.append((line, name))
            rows[parent].append(tuple(words[1:]))
        else:
            raise DiagramError(line, "expected node, card, group, browser, tree, row, phase, span, describe, or source -> target")
        if len(nodes) > 24 or len(edges) + len(phases) > 48:
            raise DiagramError(line, "limit diagrams to 24 nodes and 48 arrows or phases")
    if len(stack) > 1:
        raise DiagramError(len(source.splitlines()), f"unclosed container {stack[-1]!r}; expected }}")
    if not kind or not nodes:
        if kind == "timeline":
            raise DiagramError(1, "a timeline needs at least one span")
        raise DiagramError(1, "a diagram needs a title and at least one node")
    for line, name in references:
        if name not in nodes:
            raise DiagramError(line, f"unknown node {name!r}")
    for edge in edges:
        for source, target in ((edge.source, edge.target), (edge.target, edge.source)):
            parent = parents[source]
            while parent:
                if parent == target:
                    raise DiagramError(1, "containment already connects a container to its descendants; use arrows between peers")
                parent = parents[parent]
    for parent, names in children.items():
        if parent and nodes[parent].kind == "tree":
            if not nodes[parent].files:
                raise DiagramError(1, f"tree {parent!r} needs at least one file")
            continue
        if parent and not names:
            raise DiagramError(1, f"container {parent!r} needs at least one node")
        for name in names:
            if name in placed and placed[name] != parent:
                raise DiagramError(1, f"row for {name!r} must be inside its own container")
        if rows[parent]:
            missing = set(names) - placed.keys()
            if missing:
                raise DiagramError(1, "every node needs a row; missing: " + ", ".join(sorted(missing)))
        else:
            rows[parent] = [tuple(names)]
        if parent:
            nodes[parent] = replace(nodes[parent], rows=tuple(rows[parent]))
    return Diagram(
        kind, title, description, tuple(nodes.values()), tuple(edges),
        tuple(rows[""]), tuple(phases), tuple(spans), unit,
    )


def _wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width, break_on_hyphens=False) or [""]


def _wobble(key: str) -> float:
    value = int.from_bytes(hashlib.blake2s(key.encode(), digest_size=4).digest())
    return (value / 0xffffffff - 0.5) * 5


def _stroke(points: list[tuple[float, float]], key: str) -> str:
    x, y = points[0]
    parts = [f"M{x:.2f},{y:.2f}"]
    for index, (end_x, end_y) in enumerate(points[1:]):
        dx, dy = end_x - x, end_y - y
        length = math.hypot(dx, dy) or 1
        offsets = [
            _wobble(f"{key}:{index}:{control}") * min(1, length / 60)
            for control in range(2)
        ]
        parts.append(
            f"C{x + dx / 3 - dy / length * offsets[0]:.2f},"
            f"{y + dy / 3 + dx / length * offsets[0]:.2f} "
            f"{x + 2 * dx / 3 - dy / length * offsets[1]:.2f},"
            f"{y + 2 * dy / 3 + dx / length * offsets[1]:.2f} "
            f"{end_x:.2f},{end_y:.2f}"
        )
        x, y = end_x, end_y
    return " ".join(parts)


def _text(x: float, y: float, lines: list[str], *, background: bool = False,
          anchor: str = "middle", color: str = "var(--foreground, #18181b)") -> str:
    result = []
    if background:
        width = max(len(line) for line in lines) * 8 + 16
        result.append(
            f'<rect x="{x - width / 2:g}" y="{y - 15:g}" '
            f'width="{width}" height="{len(lines) * 20 + 4}" rx="5" '
            'fill="var(--background, #ffffff)"/>'
        )
    result.append(
        f'<text x="{x:g}" y="{y:g}" text-anchor="{anchor}" '
        f'fill="{color}">'
    )
    for index, line in enumerate(lines):
        result.append(f'<tspan x="{x:g}" dy="{20 if index else 0}">{escape(line)}</tspan>')
    result.append("</text>")
    return "".join(result)


def _tree_rows(node: Node) -> list[tuple[int, str, str]]:
    root = {}
    for path, style in node.files:
        parts = path.split("/")
        branch = root
        for part in parts[:-1]:
            branch = branch.setdefault(part, ("", {}))[1]
        branch[parts[-1]] = (style, None)
    result = []

    def visit(branch, depth):
        for name, (style, children) in branch.items():
            result.append((depth, name + ("/" if children is not None else ""), style))
            if children is not None:
                visit(children, depth + 1)

    visit(root, 0)
    return result


def _box(node: Node, x: float, y: float, height: float, width: float = 200) -> str:
    left, right, bottom = x - width / 2, x + width / 2, y + height
    outline = _stroke(
        [(left, y), (right, y), (right, bottom), (left, bottom), (left, y)],
        node.name,
    ) + " Z"
    stroke = "var(--accent, #5b5bd6)" if node.accent else "var(--foreground-muted, #616775)"
    fill = "var(--accent-soft, #eeeeff)" if node.accent else "var(--background-subtle, #f7f8fa)"
    if node.rows and not node.accent:
        fill = "var(--background, #ffffff)"
    dashed = ' stroke-dasharray="5 5"' if node.kind == "group" or node.muted or node.highlight else ""
    outline = (
        f'<path d="{outline}" stroke="{stroke}" fill="{fill}" '
        f'stroke-width="1.6" stroke-linejoin="round"{dashed}/>'
    )
    label = _text(x, y + 27, _wrap(node.label, 22))
    if node.kind == "card":
        top = y + len(_wrap(node.label, 22)) * 20 + 22
        label += (
            f'<rect x="{left + 18:g}" y="{top:g}" width="40" height="40" '
            'rx="5" fill="var(--foreground-muted, #616775)" opacity="0.25"/>'
        )
        for index, length in enumerate((width - 90, width - 114, width - 100)):
            baseline = top + 5 + index * 14
            label += (
                f'<path d="{_stroke([(left + 72, baseline), (left + 72 + length, baseline)], node.name + ":line:" + str(index))}" '
                'stroke="var(--foreground-muted, #616775)" stroke-width="6" '
                'stroke-linecap="round" opacity="0.4" fill="none"/>'
            )
    if node.kind == "tree":
        baseline = y + len(_wrap(node.label, 22)) * 20 + 52
        for index, (depth, name, style) in enumerate(_tree_rows(node)):
            indent = left + 30 + depth * 18
            color = "var(--accent, #5b5bd6)" if style == "accent" else "var(--foreground, #18181b)"
            opacity = ' opacity="0.65"' if style == "muted" else ""
            lines = _wrap(name, 32)
            label += (
                f'<g style="font-family:ui-monospace,monospace"{opacity}>'
                f'<path d="{_stroke([(indent - 10, baseline - 18), (indent - 10, baseline - 5), (indent - 3, baseline - 5)], node.name + str(index))}" '
                'fill="none" stroke="var(--foreground-muted, #616775)"/>'
                + _text(indent, baseline, lines, anchor="start", color=color)
                + '</g>'
            )
            baseline += len(lines) * 20 + 10
    if node.kind == "browser":
        toolbar = len(_wrap(node.label, 22)) * 20 + 36
        dots = "".join(
            f'<circle cx="{left + 13 + index * 10:g}" cy="{y + 12:g}" r="2.5" '
            'fill="var(--foreground-muted, #616775)"/>'
            for index in range(3)
        )
        label = dots + _text(x, y + 36, _wrap(node.label, 22)) + (
            f'<path d="{_stroke([(left, y + toolbar), (right, y + toolbar)], node.name + ":bar")}" '
            f'stroke="{stroke}" fill="none"/>'
        )
    opacity = ' opacity="0.65"' if node.muted else ""
    return f'<g data-diagram-node="{node.name}"{opacity}>{outline}{label}</g>'


def _arrow(start, end, edge: Edge, key: str) -> str:
    x, y = end
    angle = math.atan2(y - start[1], x - start[0])
    wings = [
        (x - 9 * math.cos(angle + turn), y - 9 * math.sin(angle + turn))
        for turn in (-0.45, 0.45)
    ]
    dash = ' stroke-dasharray="5 5"' if edge.dashed else ""
    return (
        '<g fill="none" stroke="var(--accent, #5b5bd6)" stroke-width="1.7" '
        'stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="{_stroke([start, end], key)}"{dash}/>'
        f'<path d="{_stroke([wings[0], end, wings[1]], key + ":tip")}"/>'
        '</g>'
    )


def _boundary(box, dx, dy):
    x, y, width, height = box
    scale = min(
        (width / 2 + 4) / abs(dx) if dx else math.inf,
        (height / 2 + 4) / abs(dy) if dy else math.inf,
    )
    return x + dx * scale, y + dy * scale


def _flow(diagram: Diagram) -> tuple[int, int, str]:
    nodes = {node.name: node for node in diagram.nodes}
    label_lines = max((len(_wrap(edge.label, 24)) for edge in diagram.edges), default=1)
    gap = max(100, label_lines * 20 + 48)
    inner_gap = max(40, label_lines * 20 + 32)
    sizes = {}

    def measure_rows(rows, horizontal_gap, vertical_gap):
        width = max(sum(measure(name)[0] for name in row) + (len(row) - 1) * horizontal_gap for row in rows)
        height = sum(max(measure(name)[1] for name in row) for row in rows) + (len(rows) - 1) * vertical_gap
        return width, height

    def measure(name):
        if name not in sizes:
            node = nodes[name]
            header = len(_wrap(node.label, 22)) * 20 + 30
            width, height = 200, header
            if node.kind == "card":
                height += 48
            if node.kind == "tree":
                entries = _tree_rows(node)
                width = max(248, max(depth * 18 + max(map(len, _wrap(label, 32))) * 9 + 60 for depth, label, _ in entries))
                height = header + sum(len(_wrap(label, 32)) * 20 + 10 for _, label, _ in entries) + 24
            if node.rows:
                inner_width, inner_height = measure_rows(node.rows, 60, inner_gap)
                header += 26 if node.kind == "browser" else 0
                width, height = max(248, inner_width + 48), header + inner_height + 24
            sizes[name] = width, height
        return sizes[name]

    width, height = measure_rows(diagram.rows, 120, gap)
    width += 120
    height += 56
    positions = {}
    boxes = []

    def place(rows, center, y, horizontal_gap, vertical_gap):
        for row in rows:
            row_width = sum(sizes[name][0] for name in row) + (len(row) - 1) * horizontal_gap
            x = center - row_width / 2
            for name in row:
                node = nodes[name]
                w, h = sizes[name]
                positions[name] = (x + w / 2, y + h / 2, w, h)
                boxes.append(_box(node, x + w / 2, y, h, w))
                if node.rows:
                    header = len(_wrap(node.label, 22)) * 20 + 30
                    header += 26 if node.kind == "browser" else 0
                    place(node.rows, x + w / 2, y + header, 60, inner_gap)
                x += w + horizontal_gap
            y += max(sizes[name][1] for name in row) + vertical_gap

    place(diagram.rows, width / 2, 28, 120, gap)
    paths = []
    labels = []
    bottom = height
    for edge in diagram.edges:
        sx, sy, sw, sh = positions[edge.source]
        tx, ty, tw, th = positions[edge.target]
        dx, dy = tx - sx, ty - sy

        start = _boundary(positions[edge.source], dx, dy)
        end = _boundary(positions[edge.target], -dx, -dy)
        horizontal = abs(dx) > (sw + tw) / 2
        wrap_width = 12 if horizontal else 24
        paths.append(_arrow(start, end, edge, f"{edge.source}:{edge.target}:{edge.label}"))
        if edge.label:
            lines = _wrap(edge.label, wrap_width)
            label_y = (start[1] + end[1]) / 2
            label_y += 24 if horizontal else -len(lines) * 10
            labels.append(_text(
                (start[0] + end[0]) / 2,
                label_y,
                lines, background=True,
            ))
            bottom = max(bottom, label_y + len(lines) * 20 + 16)
    return width, int(bottom), "".join(boxes + paths + labels)


def _sequence(diagram: Diagram) -> tuple[int, int, str]:
    spacing = 300
    width = len(diagram.nodes) * spacing
    height = max(len(_wrap(node.label, 22)) for node in diagram.nodes) * 20 + 30
    positions = {node.name: 150 + index * spacing for index, node in enumerate(diagram.nodes)}
    y = height + 62
    arrows = []
    phases = {}
    for phase in diagram.phases:
        phases.setdefault(phase.before, []).append(phase.label)
    for index in range(len(diagram.edges) + 1):
        for label in phases.get(index, []):
            lines = _wrap(label, 40)
            band_height = len(lines) * 20 + 20
            arrows.append(
                f'<rect x="28" y="{y - 14}" width="{width - 56}" '
                f'height="{band_height}" rx="6" fill="var(--accent-soft, #eeeeff)"/>'
                + _text(width / 2, y + 8, lines)
            )
            y += band_height + 28
        if index == len(diagram.edges):
            break
        edge = diagram.edges[index]
        lines = _wrap(edge.label, 30)
        y += len(lines) * 20
        start, end = (positions[edge.source], y), (positions[edge.target], y)
        arrows.append(_arrow(start, end, edge, f"{edge.source}:{edge.target}:{edge.label}"))
        if edge.label:
            arrows.append(_text((start[0] + end[0]) / 2, y - len(lines) * 20, lines))
        y += 48
    shapes = []
    for node in diagram.nodes:
        x = positions[node.name]
        shapes.append(
            f'<path d="M{x},28 V{y}" fill="none" '
            'stroke="var(--foreground-muted, #616775)" '
            'stroke-dasharray="3 7" opacity="0.5"/>'
        )
        shapes.append(_box(node, x, 28, height))
    return width, y + 16, "".join(shapes + arrows)


def _timeline(diagram: Diagram) -> tuple[int, int, str]:
    left, scale_width = 240, 600
    maximum = max(span.end for span in diagram.spans)
    muted = "var(--foreground-muted, #616775)"
    y = 68
    shapes = []
    for node, span in zip(diagram.nodes, diagram.spans, strict=True):
        lines = _wrap(node.label, 22)
        shapes.append(_text(28, y + 18, lines, anchor="start"))
        shapes.append(_text(
            28, y + len(lines) * 20 + 22,
            [f"{span.start:g}–{span.end:g} {diagram.unit}"],
            anchor="start", color=muted,
        ))
        x = left + span.start / maximum * scale_width
        end = left + span.end / maximum * scale_width
        outline = _stroke([(x, y), (end, y), (end, y + 28), (x, y + 28), (x, y)], node.name) + " Z"
        stroke = "var(--accent, #5b5bd6)" if node.accent else muted
        fill = "var(--accent-soft, #eeeeff)" if node.accent else "var(--background-subtle, #f7f8fa)"
        style = ' opacity="0.65" stroke-dasharray="5 5"' if node.muted else ""
        shapes.append(
            f'<path data-diagram-span="{node.name}" d="{outline}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.6" '
            f'stroke-linejoin="round"{style}/>'
        )
        y += len(lines) * 20 + 64
    grid = []
    for index in range(5):
        x = left + index / 4 * scale_width
        grid.append(_text(x, 32, [f"{maximum * (index / 4):g} {diagram.unit}"]))
        grid.append(
            f'<path d="M{x:g},48 V{y - 20:g}" stroke="{muted}" '
            'stroke-dasharray="3 7" opacity="0.35"/>'
        )
    return left + scale_width + 80, y, "".join(grid + shapes)


def render_diagram(source: str) -> str:
    """Render a ``diagram`` fence without importing or executing user code."""
    diagram = parse_diagram(source)
    renderer = {"flow": _flow, "sequence": _sequence, "timeline": _timeline}[diagram.kind]
    width, height, content = renderer(diagram)
    labels = {node.name: node.label for node in diagram.nodes}
    relationships = [
        f"{node.label} contains " + ", ".join(labels[name] for row in node.rows for name in row)
        for node in diagram.nodes if node.rows
    ]
    relationships.extend(
        f"{labels[edge.source]} to {labels[edge.target]}: {edge.label or 'connection'}"
        for edge in diagram.edges
    )
    relationships.extend(
        f"{node.label} files: " + ", ".join(path for path, _ in node.files)
        for node in diagram.nodes if node.files
    )
    relationships.extend(
        f"{labels[span.node]}: {span.start:g} to {span.end:g} {diagram.unit}"
        for span in diagram.spans
    )
    description = diagram.description or "; ".join(relationships)
    title = escape(diagram.title)
    accessible = escape(f"{diagram.title}. {description}")
    return (
        '<figure class="docs-sketch" style="margin:1.5rem 0">'
        '<div style="overflow-x:auto;padding:4px" tabindex="0" role="region" '
        f'aria-label="{title}">'
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{accessible}" '
        f'viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'style="display:block;width:100%;height:auto;min-width:{width}px;'
        'font:14px ui-sans-serif,system-ui,sans-serif">'
        f'<title>{title}</title><desc>{escape(description)}</desc>{content}</svg></div>'
        '<figcaption style="margin-top:0.5rem;color:var(--foreground-muted, #616775)">'
        f'<strong>{title}</strong>'
        + (f" — {escape(diagram.description)}" if diagram.description else "")
        + '</figcaption></figure>'
    )
