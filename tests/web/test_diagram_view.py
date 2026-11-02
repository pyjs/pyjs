import re

import pytest
from pyjs_examples.components.diagram_viewer import ReviewDiagram, review_flow

from pyjs.analysis.source import create_module
from pyjs.javascript.source import compile_source
from pyjs.javascript.transpiler import BundleTarget, bundle_targets_with_source_maps
from pyjs.ui.diagram import Diagram, Node
from pyjs.web.ssr import render_html
from pyjs.web.ui.diagram_view import diagram_svg


@pytest.mark.parametrize("module,expression,editor", [
    ("pyjs.web.ui.diagram_view", "DiagramView()", False),
    ("pyjs_examples.components.diagram_viewer", "DiagramViewerApp()", False),
    ("pyjs.web.ui.diagram", "DiagramCanvas()", True),
])
def test_readonly_bundle_excludes_editor_implementation(module, expression, editor):
    name = expression[:-2]
    with compile_source(f'''
from pyjs.web.dom import document
from {module} import {name}
def main() -> None:
    document.body.append({expression})
''') as result:
        source = "\n".join(result.sources.values())
    # Inspect boundaries in the complete generated dependency bundle, not only
    # the entry module; default and custom viewers must both exclude editing.
    for token in ["class DiagramEditor", "class DiagramCanvas", "undo_stack",
                  "redo_stack", "diagram-change", "Node label", "pointerdown"]:
        assert (token in source) is editor, token
    listeners = set(re.findall(r"\.addEventListener\('([^']+)'", source))
    mutation_events = {"pointerdown", "pointermove", "pointerup", "dblclick", "wheel"}
    if editor:
        assert mutation_events <= listeners
    else:
        assert not listeners & mutation_events
    if not editor:
        assert {"click", "keydown"} <= listeners
        assert "diagram-node-activate" in source


def test_static_diagram_is_ordinary_markup_without_script_or_editor_controls():
    graph = Diagram(nodes=[Node(id="a", label="Long label that must not be truncated",
                                x=0.0, y=0.0, width=300.0)], edges=[])
    html = render_html(diagram_svg(graph, label="Static flow"))
    assert "Long label that must not be truncated" in html
    assert 'role="img"' in html and 'aria-label="Static flow"' in html
    for token in ["<script", "diagram-view", "diagram-canvas", "<input", "tabindex", 'role="button"']:
        assert token not in html


def test_static_page_compilation_does_not_ship_diagram_rendering_or_editing_code():
    module = create_module('''
from pyjs.ui.diagram import Diagram, Node
from pyjs.web.ui.diagram_view import diagram_svg
from pyjs.web.dom import Element
def main() -> Element:
    return diagram_svg(Diagram(nodes=[Node(id="a", label="A", x=0.0, y=0.0)], edges=[]))
''', "static_diagram.py")
    bundles, _ = bundle_targets_with_source_maps((BundleTarget("static", module.main),))
    source = bundles["static"].javascript
    # Only the framework's module-loader scaffold remains for a static page.
    assert re.findall(r"^(?:class|function) (\w+)", source, re.MULTILINE) == []
    assert "addEventListener" not in source
    assert "diagram_svg" not in source


def test_sibling_editor_page_does_not_leak_into_readonly_downloads():
    module = create_module('''
from pyjs.web.domx import div
from pyjs.web.ui.diagram_view import DiagramView
from pyjs.web.ui.diagram import DiagramCanvas
def shell(): return div()
def viewer(): return DiagramView()
def editor(): return DiagramCanvas()
''', "diagram_pages.py")
    bundles, _ = bundle_targets_with_source_maps((
        BundleTarget("app", module.shell),
        BundleTarget("viewer", module.viewer, "app"),
        BundleTarget("editor", module.editor, "app"),
    ))
    readonly = bundles["app"].javascript + bundles["viewer"].javascript
    for token in ["class DiagramEditor", "class DiagramCanvas", "undo_stack", "pointerdown", "label_key"]:
        assert token not in readonly
        assert token in bundles["editor"].javascript


def test_custom_node_can_be_updated_before_server_rendering():
    graph = review_flow()
    viewer = ReviewDiagram(graph)
    first = graph.nodes[0]
    replacement = Node(id=first.id, label="Updated server label", x=first.x, y=first.y,
                       width=first.width, height=first.height)
    viewer.configure(Diagram(nodes=[replacement, graph.nodes[1]], edges=graph.edges))
    html = render_html(viewer)
    assert "Updated server label" in html
    assert html.count("<input ") == 2
    assert html.count("Owner: Editorial team") == 2
