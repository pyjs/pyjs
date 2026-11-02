import pytest
from pyjs import js
from pyjs.testing.web import bubbling_click, mount, wait_for_frames
from pyjs.ui.diagram import Diagram
from pyjs.web.domx import require_element
from pyjs.web.events import KeyboardEvent, PointerEvent, WheelEvent
from pyjs_examples.components.diagrams import DiagramsApp

pytestmark = pytest.mark.pyjs_web


@js
def command(app: DiagramsApp, name: str) -> None:
    bubbling_click(require_element(app, '[data-diagram-action="' + name + '"]'))


@js
def pointer(app: DiagramsApp, phase: str, x: float, y: float) -> None:
    rect = app.canvas.svg.getBoundingClientRect()
    view = app.canvas.state.viewport
    app.canvas.svg.dispatchEvent(PointerEvent(phase, pointerId=1, button=0,
                                             clientX=rect.left + x * view.scale + view.x,
                                             clientY=rect.top + y * view.scale + view.y))


@js
async def test_decision_tree_edit_move_arrange_delete_and_undo_workflow():
    app = DiagramsApp()
    mount(app)
    await wait_for_frames()
    state = app.canvas.state
    original = state.graph
    node = require_element(app, '[data-node-id="question"]')
    node.dispatchEvent(KeyboardEvent("keydown", key="Enter", bubbles=True))
    assert not app.canvas.label.hidden
    app.canvas.label.value = "Ready to release?"
    app.canvas.label.dispatchEvent(KeyboardEvent("keydown", key="Enter", bubbles=True))
    assert state.graph.nodes[0].label == "Ready to release?"
    assert require_element(app, '[data-node-id="question"]') is node
    pointer(app, "pointerdown", 276.0, 48.0)
    pointer(app, "pointermove", 306.0, 78.0)
    assert state.graph.nodes[0].x == 200.0
    pointer(app, "pointerup", 306.0, 78.0)
    assert state.graph.nodes[0].x == 230.0
    command(app, "layout")
    assert state.graph.nodes[0].y == 0.0
    command(app, "undo")
    assert state.graph.nodes[0].x == 230.0
    state.select_node("question")
    command(app, "delete")
    assert not state.graph.edges
    assert not app.canvas.layer.querySelectorAll("[data-edge-id]")
    command(app, "undo")
    command(app, "undo")
    command(app, "undo")
    assert state.graph is original
    assert len(app.canvas.layer.querySelectorAll("[data-edge-id]")) == 2
    assert len(app.canvas.layer.querySelectorAll("[data-node-id]")) == 3


@js
def test_diagram_cancel_detach_and_invalid_tree_keep_committed_content():
    app = DiagramsApp()
    mount(app)
    state = app.canvas.state
    original = state.graph
    pointer(app, "pointerdown", 276.0, 48.0)
    pointer(app, "pointermove", 330.0, 90.0)
    pointer(app, "pointercancel", 330.0, 90.0)
    assert state.preview is original
    pointer(app, "pointerdown", 276.0, 48.0)
    pointer(app, "pointermove", 330.0, 90.0)
    app.remove()
    assert not state.active and state.preview is original
    mount(app)
    state.selected_nodes = ["no", "question"]
    command(app, "connect")
    connected = state.graph
    assert len(connected.edges) == 3
    command(app, "layout")
    assert state.graph is connected
    assert "no cycles" in app.status.textContent
    command(app, "undo")
    assert state.graph is original


@js
def test_multitouch_replacement_and_label_cancellation_do_not_publish_previews():
    app = DiagramsApp()
    mount(app)
    canvas = app.canvas
    original = canvas.state.graph
    pointer(app, "pointerdown", 276.0, 48.0)
    pointer(app, "pointermove", 330.0, 90.0)
    canvas.svg.dispatchEvent(PointerEvent("pointerdown", pointerId=2, button=0))
    pointer(app, "pointerup", 330.0, 90.0)
    assert canvas.state.graph is original and not canvas.state.undo_stack
    assert not canvas.state.active and canvas.pointer == -1
    canvas.start_label("question")
    canvas.label.value = "Discard this"
    canvas.label.dispatchEvent(KeyboardEvent("keydown", key="Escape", bubbles=True))
    assert canvas.state.graph is original and canvas.label.hidden
    scale = canvas.state.viewport.scale
    canvas.svg.dispatchEvent(WheelEvent("wheel", deltaY=0.0))
    assert canvas.state.viewport.scale == scale
    canvas.start_label("question")
    canvas.label.value = "<script>plain text</script>"
    canvas.label.dispatchEvent(KeyboardEvent("keydown", key="Enter", bubbles=True))
    source = canvas.get_data("diagram") or ""
    assert Diagram.model_validate_json(source).nodes[0].label == "<script>plain text</script>"
    assert not canvas.querySelectorAll("script")
    pointer(app, "pointerdown", 276.0, 48.0)
    pointer(app, "pointermove", 330.0, 90.0)
    canvas.configure(original)
    pointer(app, "pointerup", 330.0, 90.0)
    assert canvas.state.graph is original and not canvas.state.undo_stack
