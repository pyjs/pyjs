from typing import cast

import pytest
from pyjs import js
from pyjs.testing.web import bubbling_click, mount, wait_for_frames
from pyjs.ui.diagram import Node
from pyjs.web.dom import Element, document
from pyjs.web.domx import require_element
from pyjs.web.events import KeyboardEvent, PointerEvent
from pyjs.web.html import HTMLInputElement
from pyjs.web.ui.diagram import DiagramCanvas
from pyjs_examples.components.diagram_viewer import DiagramViewerApp, ReviewCard, review_flow

pytestmark = pytest.mark.pyjs_web


@js
class ReviewEditor(DiagramCanvas):
    def render_node(self, node: Node, previous: Element | None) -> Element:
        if isinstance(previous, ReviewCard):
            previous.update_node(node)
            return previous
        return ReviewCard(node)


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
