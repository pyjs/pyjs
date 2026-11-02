from typing import cast

import pytest
from pyjs import js
from pyjs.testing.web import bubbling_click, mount, wait_for_frames
from pyjs.ui.diagram import Diagram, Node
from pyjs.web.dom import Element, document
from pyjs.web.domx import require_element
from pyjs.web.events import KeyboardEvent, PointerEvent
from pyjs.web.html import HTMLElement, HTMLInputElement
from pyjs.web.ui.diagram import DiagramCanvas
from pyjs_examples.components.diagram_viewer import (
    DiagramViewerApp,
    ReviewCard,
    ReviewDiagram,
    review_flow,
)

pytestmark = pytest.mark.pyjs_web


@js
class ReviewEditor(DiagramCanvas):
    def render_node(self, node: Node, previous: Element | None) -> Element:
        if isinstance(previous, ReviewCard):
            previous.update_node(node)
            return previous
        return ReviewCard(node, "Editorial team")


@js
async def test_graph_reconciliation_preserves_custom_input_focus_and_selection():
    graph = review_flow()
    viewer = ReviewDiagram(graph)
    mount(viewer)
    await wait_for_frames()
    field = cast(HTMLInputElement, require_element(viewer, '[aria-label="Comment for publish"]'))
    field.value = "Keep this draft"
    field.focus()
    field.setSelectionRange(2, 7, "backward")
    for replacement in [
        Diagram(nodes=graph.nodes, edges=[]),
        Diagram(nodes=[graph.nodes[1], graph.nodes[0]], edges=[]),
        Diagram(nodes=graph.nodes, edges=graph.edges),
        Diagram(nodes=[graph.nodes[1]], edges=[]),
    ]:
        viewer.configure(replacement)
        assert document.activeElement is field
        assert field.value == "Keep this draft"
        assert field.selectionStart == 2 and field.selectionEnd == 7
        assert field.selectionDirection == "backward"
        groups = viewer.querySelectorAll("[data-node-id]")
        assert len(groups) == len(replacement.nodes)
        for i in range(len(groups)):
            assert groups[i].getAttribute("data-node-id") == replacement.nodes[i].id


@js
async def test_keyboard_delete_keeps_focus_for_undo():
    editor = ReviewEditor(review_flow())
    mount(editor)
    await wait_for_frames()
    target = require_element(editor, '[data-node-activate="draft"]')
    # Dispatch through the real active element so lost focus cannot be hidden
    # by sending the undo directly to the editor.
    cast(HTMLElement, target).focus()
    target.dispatchEvent(KeyboardEvent("keydown", key="Delete", bubbles=True))
    assert len(editor.get_graph().nodes) == 1
    active = document.activeElement
    assert active is editor
    cast(Element, active).dispatchEvent(KeyboardEvent("keydown", key="z", ctrlKey=True, bubbles=True))
    assert len(editor.get_graph().nodes) == 2


@js
async def test_readonly_custom_nodes_activate_without_editing_and_keep_native_controls():
    app = DiagramViewerApp()
    mount(app)
    await wait_for_frames()
    viewer = app.viewer
    original = viewer.get_graph()
    activate = require_element(viewer, '[data-node-activate="draft"]')
    bubbling_click(activate)
    assert app.status.textContent == "Activated: draft"
    other = require_element(viewer, '[data-node-activate="publish"]')
    other.dispatchEvent(KeyboardEvent("keydown", key="Enter", bubbles=True))
    assert app.status.textContent == "Activated: publish"
    activate.dispatchEvent(KeyboardEvent("keydown", key=" ", bubbles=True))
    assert app.status.textContent == "Activated: draft"
    field = cast(HTMLInputElement, require_element(viewer, '[aria-label="Comment for draft"]'))
    field.value = "Keep my comment"
    field.focus()
    field.dispatchEvent(KeyboardEvent("keydown", key="Delete", bubbles=True))
    field.dispatchEvent(KeyboardEvent("keydown", key="Enter", bubbles=True))
    viewer.draw()
    assert document.activeElement is field and field.value == "Keep my comment"
    assert app.status.textContent == "Activated: draft"
    viewer.svg.dispatchEvent(PointerEvent("pointerdown", pointerId=1, button=0))
    viewer.svg.dispatchEvent(PointerEvent("pointerup", pointerId=1, clientX=100.0))
    activate.dispatchEvent(KeyboardEvent("keydown", key="Delete", bubbles=True))
    assert viewer.get_graph() is original
    assert len(viewer.querySelectorAll("[data-node-id]")) == 2
    assert not viewer.querySelectorAll('[aria-label="Node label"]')


@js
async def test_custom_node_content_survives_editor_drag_and_controls_keep_input_ownership():
    editor = ReviewEditor(review_flow())
    mount(editor)
    await wait_for_frames()
    field = cast(HTMLInputElement, require_element(editor, '[aria-label="Comment for draft"]'))
    card = require_element(editor, "review-card")
    field.value = "Retain across moves"
    field.focus()
    field.dispatchEvent(PointerEvent("pointerdown", pointerId=1, button=0, bubbles=True))
    assert not editor.state.active
    field.dispatchEvent(KeyboardEvent("keydown", key="Delete", bubbles=True))
    assert len(editor.state.graph.nodes) == 2
    editor.state.begin(editor.viewport.x + 10.0 * editor.viewport.scale,
                       editor.viewport.y + 10.0 * editor.viewport.scale)
    editor.state.move(editor.viewport.x + 40.0 * editor.viewport.scale,
                      editor.viewport.y + 30.0 * editor.viewport.scale)
    assert editor.state.preview.nodes[0].x == 30.0
    editor.draw()
    assert require_element(editor, "review-card") is card
    assert document.activeElement is field and field.value == "Retain across moves"
    editor.state.finish(editor.viewport.x + 40.0 * editor.viewport.scale,
                        editor.viewport.y + 30.0 * editor.viewport.scale)
    editor.changed()
    assert require_element(editor, "review-card") is card
    assert field.value == "Retain across moves"
    editor.state.undo()
    editor.changed()
    assert require_element(editor, "review-card") is card
    assert field.value == "Retain across moves"
    original = editor.state.graph.nodes[0]
    assert original.x == 0.0
    assert editor.state.graph.nodes[1].x == 330.0
    assert original.width == 250.0 and original.height == 180.0
