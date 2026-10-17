import re
import xml.etree.ElementTree as ET

import pytest

from pyjs.docs.api_extraction import extract_api
from pyjs.docs.api_rendering import build_api_documentation
from pyjs.docs.builder import _discover_pages
from pyjs.docs.config import load_config
from pyjs.docs.diagrams import (
    DiagramError,
    Edge,
    Node,
    Phase,
    Span,
    parse_diagram,
    render_diagram,
)
from pyjs.docs.markdown import render_markdown

pytestmark = pytest.mark.pyjs_python
SVG = "{http://www.w3.org/2000/svg}"

SEQUENCE = '''sequence "Snapshot, then updates"
describe "Read the snapshot before following its cursor."
node browser "Browser" accent
node server "Django"
browser -> server "Read snapshot"
server --> browser "Snapshot and cursor"
browser -> server "Follow cursor"
server --> browser "Later updates"
'''

FLOW = '''flow "Shared application bundles"
node app "Application core" accent
node public "Public section"
node account "Account section"
node product "Product page"
node orders "Orders page"
row app
row public account
row product orders
app -> public
app -> account
public -> product
account -> orders
'''

NESTED = '''flow "Component boundaries"
browser page "/store/" {
    node nav "Navigation"
    group content "Content" {
        node pending "Pending" muted
        node cart "Cart" accent
        row pending cart
    }
    row nav
    row content
}
node api "API"
row page api
api -> cart "Result"
'''

TREE = '''flow "Sources"
tree source "Project" {
    file "app/page.py" accent
    file "app/views/cart.py"
    file "app/layout.py"
    file "README.md" muted
}
node output "Page"
source -> output "Build"
'''

TIMELINE = '''timeline "Concurrent tasks" ms
span a 0 20 "Fetch A"
span b 0 40 "Fetch B" muted
span render 40 50 "Render" accent
'''

CARDS = '''flow "Updates"
browser page "/store/" {
    card target "Product <preview>" highlight
}
card source "New product" accent
row page source
source -> target "Result"
'''


def svg_element(html):
    return ET.fromstring(re.search(r"<svg\b.*?</svg>", html, re.DOTALL)[0])


def test_parser_preserves_order_and_forward_references():
    diagram = parse_diagram('''flow "A to B"
row a b
a --> b "Message #1"
node a "A" accent
node b "B" # a comment
''')
    assert diagram.kind == "flow"
    assert diagram.title == "A to B"
    assert diagram.nodes == (Node("a", "A", True), Node("b", "B", False))
    assert diagram.edges == (Edge("a", "b", "Message #1", True),)
    assert diagram.rows == (("a", "b"),)


def test_command_names_can_be_node_identifiers():
    diagram = parse_diagram('''flow "Names"
node row "A"
node node "B"
row -> node
''')
    assert diagram.edges == (Edge("row", "node", "", False),)


@pytest.mark.parametrize(("source", "message"), [
    ("", "Diagram line 1: a diagram needs a title and at least one node"),
    ('flow "T"', "Diagram line 1: a diagram needs a title and at least one node"),
    ('chart "T"', 'Diagram line 1: start with flow "Title", sequence "Title", or timeline "Title" ms'),
    ('flow ""', "Diagram line 1: title must not be empty"),
    ('flow "T"\nnode a "', "Diagram line 2: No closing quotation"),
    ('flow "T"\nnode a "A"\nnode a "B"', "Diagram line 3: duplicate node 'a'"),
    ('flow "T"\nnode 1a "A"', "Diagram line 2: invalid node identifier '1a'"),
    ('flow "T"\nnode a ""', "Diagram line 2: node label must not be empty"),
    ('flow "T"\nnode a "A" red', "Diagram line 2: node style must be accent, muted, or highlight"),
    ('flow "T"\nnode a "A"\na -> b', "Diagram line 3: unknown node 'b'"),
    ('flow "T"\nnode a "A"\nrow b', "Diagram line 3: unknown node 'b'"),
    ('flow "T"\nnode a "A"\nnode b "B"\nrow a',
     "Diagram line 1: every node needs a row; missing: b"),
    ('flow "T"\nrow a a', "Diagram line 2: node 'a' appears in more than one row"),
    ('sequence "T"\nrow a', "Diagram line 2: row is only available in flow diagrams"),
    ('flow "T"\nnode a "A"\na -> a',
     "Diagram line 3: self-arrows are not supported in this prototype"),
    ('flow "T"\ndescribe "A"\ndescribe "B"',
     "Diagram line 3: describe may appear only once"),
    ('flow "T"\ndescribe ""', "Diagram line 2: description must not be empty"),
    ('flow "T"\nimport os', "Diagram line 2: expected node, card, group, browser, tree, row, phase, span, describe, or source -> target"),
])
def test_parser_errors_have_locations(source, message):
    with pytest.raises(DiagramError) as error:
        parse_diagram(source)
    assert str(error.value) == message


def test_parser_bounds_work():
    with pytest.raises(DiagramError, match="source exceeds"):
        parse_diagram("x" * 20_001)
    with pytest.raises(DiagramError, match="24 nodes and 48 arrows"):
        parse_diagram('flow "T"\n' + "\n".join(f'node n{i} "N"' for i in range(25)))
    with pytest.raises(DiagramError, match="24 nodes and 48 arrows"):
        parse_diagram('flow "T"\nnode a "A"\nnode b "B"\n' + "a -> b\n" * 49)


@pytest.mark.parametrize("source", [FLOW, SEQUENCE, NESTED, TREE, TIMELINE, CARDS, 'flow "One"\nnode only "Alone"'])
def test_svg_is_deterministic_accessible_and_self_contained(source):
    html = render_diagram(source)
    assert html == render_diagram(source)
    svg = svg_element(html)
    assert svg.attrib["role"] == "img"
    assert svg.find(SVG + "title").text == parse_diagram(source).title
    assert svg.attrib["aria-label"]
    assert svg.attrib["viewBox"].startswith("0 0 ")
    assert all("id" not in element.attrib for element in svg.iter())
    assert {element.tag.removeprefix(SVG) for element in svg.iter()} <= {
        "svg", "title", "desc", "g", "path", "rect", "text", "tspan", "circle",
    }
    assert "var(--accent," in html or "var(--foreground-muted," in html


def test_svg_escapes_labels_and_never_treats_them_as_markup():
    source = '''flow '<script>alert("x")</script>'
describe '<img src=x onerror=alert(1)>'
node a '<a href="evil">&</a>'
node b "B"
a -> b '<script>oops</script>'
'''
    html = render_diagram(source)
    svg = svg_element(html)
    assert svg.find(SVG + "title").text == '<script>alert("x")</script>'
    assert "<script>" not in html
    assert "<img" not in html
    assert "<a " not in html
    assert "&lt;script&gt;" in html


def test_sketch_outlines_do_not_change_when_unrelated_nodes_are_added():
    first = svg_element(render_diagram('flow "T"\nnode a "A"'))
    second = svg_element(render_diagram('flow "T"\nnode a "A"\nnode b "B"\nrow a\nrow b'))
    assert first.find(f"{SVG}g/{SVG}path").attrib == second.find(f"{SVG}g/{SVG}path").attrib


@pytest.mark.parametrize("source", [FLOW, SEQUENCE, NESTED, CARDS])
def test_box_outlines_close_with_rounded_joins_without_closing_arrows(source):
    svg = svg_element(render_diagram(source))
    boxes = [path for path in svg.iter(SVG + "path") if path.get("fill", "none") != "none"]
    assert len(boxes) == len(parse_diagram(source).nodes)
    for box in boxes:
        assert box.get("d").endswith(" Z")
        assert box.get("stroke-linejoin") == "round"
    for arrow in svg.iter(SVG + "g"):
        if "data-diagram-node" not in arrow.attrib:
            assert all(not path.get("d").endswith(" Z") for path in arrow)


def test_sequence_preserves_message_order_and_dashes():
    svg = svg_element(render_diagram(SEQUENCE))
    labels = [element.text for element in svg.iter(SVG + "tspan")]
    assert labels == ["Browser", "Django", "Read snapshot", "Snapshot and cursor", "Follow cursor", "Later updates"]
    arrows = [group for group in svg.findall(SVG + "g") if "data-diagram-node" not in group.attrib]
    assert len(arrows) == 4
    assert [arrow[0].get("stroke-dasharray") for arrow in arrows] == [None, "5 5", None, "5 5"]


@pytest.mark.parametrize("fence", ["```", "~~~~", "````"])
def test_markdown_renders_diagrams_without_changing_headings_or_description(fence):
    html, headings, description = render_markdown(
        f"# Title\n\nIntroduction.\n\n## Example\n\n{fence}diagram\n{SEQUENCE}{fence}\n"
    )
    assert html.count("<svg ") == 1
    assert "<pre" not in html
    assert description == "Introduction."
    assert [heading.title for heading in headings] == ["Example"]


def test_markdown_keeps_nested_diagram_examples_as_code():
    html = render_markdown(f"````text\n```diagram\n{SEQUENCE}```\n````\n")[0]
    assert "<svg" not in html
    assert "<pre" in html
    assert "sequence" in html


def test_markdown_reports_diagram_errors():
    with pytest.raises(ValueError) as error:
        render_markdown('# T\n\n```diagram\nflow "T"\nnode a "A"\na -> missing\n```')
    assert str(error.value) == "Markdown line 3: Diagram line 3: unknown node 'missing'"
    with pytest.raises(ValueError, match="Markdown line 1: unclosed diagram fence"):
        render_markdown('```diagram\nflow "T"')


@pytest.mark.parametrize("diagram_source", [SEQUENCE, NESTED, TREE, TIMELINE, CARDS])
def test_static_docstring_extraction_renders_diagrams_without_importing(tmp_path, diagram_source):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\n[tool.pyjs.docs]\napi = ["example"]\n'
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "example.py").write_text(
        '"""Snapshot API.\n\n```diagram\n' + diagram_source + '```\n"""\n'
        'raise RuntimeError("This module must not be imported")\n'
        'def follow():\n'
        '    """Follow updates.\n\n'
        + "\n".join("    " + line for line in ("```diagram\n" + diagram_source + "```").splitlines())
        + '\n    """\n'
    )
    reference = extract_api(tmp_path, ("example",))
    assert "```diagram" in reference.modules[0].doc[0].text
    result = build_api_documentation(load_config(tmp_path))
    assert len(result.pages) == 1
    assert result.pages[0].html.count("<svg ") == 2


def test_nested_containers_use_local_rows_and_global_identifiers():
    diagram = parse_diagram(NESTED)
    nodes = {node.name: node for node in diagram.nodes}
    assert diagram.rows == (("page", "api"),)
    assert nodes["page"].rows == (("nav",), ("content",))
    assert nodes["content"].rows == (("pending", "cart"),)
    assert nodes["page"].kind == "browser"
    assert nodes["content"].kind == "group"
    assert nodes["pending"].muted and not nodes["pending"].accent
    assert diagram.edges == (Edge("api", "cart", "Result", False),)
    svg = svg_element(render_diagram(NESTED))
    assert len(list(svg.iter(SVG + "circle"))) == 3
    groups = {group.get("data-diagram-node"): group for group in svg.findall(SVG + "g")}
    assert groups["pending"].get("opacity") == "0.65"
    assert groups["content"][0].get("stroke-dasharray") == "5 5"
    description = svg.find(SVG + "desc").text
    assert "/store/ contains Navigation, Content" in description
    assert "Content contains Pending, Cart" in description
    assert "API to Cart: Result" in description
    assert all("nan" not in path.get("d").lower() for path in svg.iter(SVG + "path"))


@pytest.mark.parametrize(("tail", "message"), [
    ('group box "Box"', 'Diagram line 2: open a group, browser, or tree with {'),
    ('}', 'Diagram line 2: unexpected closing brace'),
    ('group box "Box" {', "Diagram line 2: unclosed container 'box'; expected }"),
    ('group box "Box" {\n}', "Diagram line 1: container 'box' needs at least one node"),
    ('node a', 'Diagram line 2: expected node identifier "Label" [accent|muted|highlight]'),
    ('phase "Before"', 'Diagram line 2: phase is only available in sequence diagrams'),
    ('group box "Box" {\nnode a "A"\n}\nrow a box',
     "Diagram line 1: row for 'a' must be inside its own container"),
    ('group box "Box" {\nnode a "A"\nnode b "B"\nrow a\n}',
     'Diagram line 1: every node needs a row; missing: b'),
    ('group box "Box" {\nnode a "A"\n}\nbox -> a',
     'Diagram line 1: containment already connects a container to its descendants; use arrows between peers'),
])
def test_container_diagnostics(tail, message):
    with pytest.raises(DiagramError) as error:
        parse_diagram('flow "T"\n' + tail)
    assert str(error.value) == message


def test_container_depth_is_bounded():
    with pytest.raises(DiagramError) as error:
        parse_diagram('flow "T"\n' + "\n".join(f'group g{i} "G" {{' for i in range(5)))
    assert str(error.value) == "Diagram line 6: containers may be nested at most four levels"


def test_phases_preserve_order_including_adjacent_and_final_phases():
    source = '''sequence "Stages"
node a "A"
node b "B"
phase "Prepare"
phase "<Read>"
a -> b "Request"
phase "Deliver"
b --> a "Response"
phase "Finished"
'''
    diagram = parse_diagram(source)
    assert diagram.phases == (Phase(0, "Prepare"), Phase(0, "<Read>"), Phase(1, "Deliver"), Phase(2, "Finished"))
    svg = svg_element(render_diagram(source))
    assert [span.text for span in svg.iter(SVG + "tspan")] == [
        "A", "B", "Prepare", "<Read>", "Request", "Deliver", "Response", "Finished",
    ]
    with pytest.raises(DiagramError, match="groups, browsers, and trees require a flow diagram"):
        parse_diagram('sequence "T"\nbrowser b "B" {')
    with pytest.raises(DiagramError, match="phase label must not be empty"):
        parse_diagram('sequence "T"\nphase ""')
    with pytest.raises(DiagramError, match="48 arrows or phases"):
        parse_diagram('sequence "T"\nnode a "A"\n' + 'phase "P"\n' * 49)


def test_highlighted_card_is_an_arrow_target_inside_the_browser():
    diagram = parse_diagram(CARDS)
    target = diagram.nodes[1]
    assert target.kind == "card" and target.highlight and target.accent
    svg = svg_element(render_diagram(CARDS))
    groups = {group.get("data-diagram-node"): group for group in svg.findall(SVG + "g")}
    assert groups["target"][0].get("stroke-dasharray") == "5 5"
    assert groups["target"][0].get("stroke") == "var(--accent, #5b5bd6)"
    assert groups["source"][0].get("stroke-dasharray") is None
    assert len(groups["target"].findall(SVG + "rect")) == 1
    assert len(groups["target"].findall(SVG + "path")) == 4
    assert "Product &lt;preview&gt;" in render_diagram(CARDS)
    arrow = groups[None][0].get("d")
    endpoint = tuple(map(float, re.findall(r"([\d.]+),([\d.]+)", arrow)[-1]))
    target_points = [tuple(map(float, pair)) for pair in re.findall(r"([\d.]+),([\d.]+)", groups["target"][0].get("d"))]
    browser_points = [tuple(map(float, pair)) for pair in re.findall(r"([\d.]+),([\d.]+)", groups["page"][0].get("d"))]
    assert endpoint[0] == max(x for x, _ in target_points[::3]) + 4
    assert endpoint[0] < max(x for x, _ in browser_points[::3])
    assert min(y for _, y in target_points) < endpoint[1] < max(y for _, y in target_points)


@pytest.mark.parametrize("declaration", ['node x "X" highlight', 'card x "X"'])
def test_wireframe_and_highlight_are_flow_only(declaration):
    with pytest.raises(DiagramError, match="flow diagram"):
        parse_diagram('sequence "T"\n' + declaration)


def test_tree_paths_group_siblings_without_reading_files():
    diagram = parse_diagram(TREE)
    assert diagram.nodes[0].files == (
        ("app/page.py", "accent"), ("app/views/cart.py", ""),
        ("app/layout.py", ""), ("README.md", "muted"),
    )
    svg = svg_element(render_diagram(TREE))
    assert [span.text for span in svg.iter(SVG + "tspan")] == [
        "Project", "app/", "page.py", "views/", "cart.py", "layout.py",
        "README.md", "Page", "Build",
    ]
    description = svg.find(SVG + "desc").text
    assert "Project files: app/page.py, app/views/cart.py, app/layout.py, README.md" in description
    assert diagram.rows == (("source", "output"),)


@pytest.mark.parametrize(("source", "message"), [
    ('flow "T"\nfile "a.py"', "Diagram line 2: file entries require a tree panel"),
    ('flow "T"\ntree t "T" {\n}', "Diagram line 1: tree 't' needs at least one file"),
    ('flow "T"\ntree t "T" {\nnode x "X"',
     'Diagram line 3: tree panels accept only file "relative/path" [accent|muted] entries'),
    ('flow "T"\ntree t "T" {\nfile "x" red',
     'Diagram line 3: expected file "relative/path" [accent|muted]'),
    ('timeline "T" hours', "Diagram line 1: timeline unit must be ms or s"),
    ('timeline "T" s', "Diagram line 1: a timeline needs at least one span"),
    ('timeline "T" s\nnode x "X"',
     'Diagram line 2: timelines accept span identifier start end "Label" [accent|muted] or describe'),
    ('flow "T"\nspan x 0 1 "X"', "Diagram line 2: span is only available in timeline diagrams"),
    ('timeline "T" s\nspan x 0 1',
     'Diagram line 2: expected span identifier start end "Label" [accent|muted]'),
])
def test_tree_and_timeline_diagnostics(source, message):
    with pytest.raises(DiagramError) as error:
        parse_diagram(source)
    assert str(error.value) == message


@pytest.mark.parametrize("path", ["/root.py", "../x", "a/./b", "a//b", "a/", "", " ", "a/ /b", "a\\b", "/".join("abcdefghi")])
def test_tree_rejects_non_relative_or_excessively_deep_paths(path):
    with pytest.raises(DiagramError) as error:
        parse_diagram(f'flow "T"\ntree t "T" {{\nfile "{path}"\n}}')
    assert str(error.value) == "Diagram line 3: file paths need 1 to 8 relative slash-separated names, without . or .."


@pytest.mark.parametrize(("first", "second"), [("x", "x"), ("x", "x/y"), ("x/y", "x")])
def test_tree_rejects_duplicate_files_and_file_directory_conflicts(first, second):
    with pytest.raises(DiagramError) as error:
        parse_diagram(f'flow "T"\ntree t "T" {{\nfile "{first}"\nfile "{second}"\n}}')
    assert str(error.value) == f"Diagram line 4: duplicate file or file/directory conflict: {second!r}"


def test_tree_file_limit_is_per_diagram_not_per_panel():
    source = 'flow "T"\ntree a "A" {\n' + '\n'.join(f'file "{i}"' for i in range(64))
    assert len(parse_diagram(source + "\n}").nodes[0].files) == 64
    with pytest.raises(DiagramError, match="limit diagrams to 64 file entries"):
        parse_diagram(source + '\n}\ntree b "B" {\nfile "last"\n}')


@pytest.mark.parametrize(("start", "end"), [
    ("x", "1"), ("nan", "1"), ("0", "inf"), ("-1", "1"),
    ("1", "1"), ("2", "1"), ("0", "1000000001"),
])
def test_timeline_rejects_invalid_times(start, end):
    with pytest.raises(DiagramError) as error:
        parse_diagram(f'timeline "T" s\nspan x {start} {end} "X"')
    assert str(error.value) == "Diagram line 2: span times must be finite numbers with 0 <= start < end <= 1e9"


def test_timeline_preserves_parallel_times_and_proportional_widths():
    diagram = parse_diagram(TIMELINE)
    assert diagram.unit == "ms"
    assert diagram.spans == (Span("a", 0, 20), Span("b", 0, 40), Span("render", 40, 50))
    svg = svg_element(render_diagram(TIMELINE))
    bars = {path.get("data-diagram-span"): path for path in svg.iter(SVG + "path") if path.get("data-diagram-span")}
    coordinates = [re.findall(r"([\d.]+),([\d.]+)", bar.get("d")) for bar in bars.values()]
    assert [(points[0][0], points[3][0]) for points in coordinates] == [
        ("240.00", "480.00"), ("240.00", "720.00"), ("720.00", "840.00"),
    ]
    assert bars["b"].get("opacity") == "0.65"
    assert bars["render"].get("fill") == "var(--accent-soft, #eeeeff)"
    assert svg.find(SVG + "desc").text == "Fetch A: 0 to 20 ms; Fetch B: 0 to 40 ms; Render: 40 to 50 ms"


def test_timeline_decimals_and_source_order_do_not_imply_execution_order():
    diagram = parse_diagram('timeline "T" s\nspan late 1.25 2.5 "Later"\nspan early 0 0.5 "Earlier"')
    assert diagram.spans == (Span("late", 1.25, 2.5), Span("early", 0, 0.5))
    assert "1.25–2.5 s" in render_diagram('timeline "T" s\nspan a 1.25 2.5 "A"')


def test_tree_can_be_nested_and_new_labels_are_escaped():
    source = '''flow "T"
group g "Group" {
  tree t "Files" {
    file "dir/<script>.py" accent
  }
}
'''
    html = render_diagram(source)
    assert "<script>" not in html
    assert "&lt;script&gt;.py" in html
    svg_element(html)
    html = render_diagram('timeline "T" s\nspan x 0 1 "<script>"')
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    svg_element(html)


@pytest.mark.parametrize("owner", ["module", "function"])
def test_api_errors_identify_the_source_and_symbol(tmp_path, owner):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\n[tool.pyjs.docs]\napi = ["example"]\n'
    )
    (tmp_path / "docs").mkdir()
    docstring = '"""Summary.\n\n```diagram\nflow "T"\nnode a "A"\na -> missing\n```\n"""'
    source = docstring if owner == "module" else "def follow():\n" + "\n".join(
        "    " + line for line in docstring.splitlines()
    )
    path = tmp_path / "example.py"
    path.write_text(source)
    with pytest.raises(ValueError) as error:
        build_api_documentation(load_config(tmp_path))
    symbol = "example" if owner == "module" else "example.follow"
    line = 1 if owner == "module" else 3
    assert str(error.value) == (
        f"{path} ({symbol}): Markdown line {line}: "
        "Diagram line 3: unknown node 'missing'"
    )


def test_markdown_errors_identify_the_source_file(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\n')
    docs = tmp_path / "docs"
    docs.mkdir()
    path = docs / "index.md"
    path.write_text('# Title\n\n```diagram\nflow "T"\nnode a "A"\na -> missing\n```')
    with pytest.raises(ValueError) as error:
        _discover_pages(load_config(tmp_path))
    assert str(error.value) == (
        f"{path}: Markdown line 3: Diagram line 3: unknown node 'missing'"
    )
