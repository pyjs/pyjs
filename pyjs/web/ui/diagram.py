"""Interactive diagram editing built on the read-only rendering component."""
from pyjs import js
from pyjs.ui.diagram import Diagram, DiagramEditor, Node, node_at
from pyjs.web.dom import Element
from pyjs.web.domx import input, ref, tw
from pyjs.web.events import Event, KeyboardEvent, MouseEvent, PointerEvent, WheelEvent
from pyjs.web.ui.diagram_view import (
    DiagramView,
    draw_diagram,
    interactive_target,
    svg_element,
)

__all__ = ["DiagramCanvas", "draw_diagram", "svg_element"]


@js
class DiagramCanvas(DiagramView):
    """Editable diagram surface; emits bubbling ``diagram-change`` on commits.

    ``state`` exposes portable commands. After a programmatic commit call
    ``changed()``; after selection or viewport changes call ``draw()``.
    Toolbars, persistence and domain rules belong to the application.
    """

    def __init__(self, graph: Diagram | None = None):
        super().__init__(graph)
        self.state = DiagramEditor(self._graph)
        self.viewport = self.state.viewport
        self.pointer = -1
        self.editing = ""
        self.setAttribute("tabindex", "0")
        self.setAttribute("aria-label", "Diagram editor")
        self.svg.setAttribute("style", "touch-action:none;user-select:none;display:block")
        self.label = ref(input(tw("w-full rounded border border-slate-400 px-3 py-2"),
                               {"aria-label": "Node label"}))
        self.label.hidden = True
        self.label.addEventListener("keydown", self.label_key)
        self.label.addEventListener("change", self.label_changed)
        self.insertBefore(self.label, self.svg)

    def bind_events(self) -> None:
        self.svg.addEventListener("pointerdown", self.pointer_down)
        self.svg.addEventListener("pointermove", self.pointer_move)
        self.svg.addEventListener("pointerup", self.pointer_up)
        self.svg.addEventListener("pointercancel", self.pointer_cancel)
        self.svg.addEventListener("lostpointercapture", self.pointer_cancel)
        self.svg.addEventListener("dblclick", self.double_click)
        self.svg.addEventListener("wheel", self.wheel)
        self.addEventListener("keydown", self.key)

    def get_graph(self) -> Diagram:
        return self.state.graph

    def configure(self, graph: Diagram) -> None:
        self.state.replace_graph(graph)
        self.set_data("diagram", graph.model_dump_json())
        self.cancel_interaction()
        self.editing = ""
        self.label.hidden = True
        self.draw()

    def initialize(self) -> None:
        self.restore()
        if self.get_data("self-id") is not None:
            self.state = DiagramEditor(self._graph)
            self.pointer = -1
            self.editing = ""
        self.viewport = self.state.viewport
        self.fit()
        self.bind_events()

    def draw(self) -> None:
        self.paint(self.state.preview, self.state.selected_nodes, self.state.selected_edges)

    def changed(self) -> None:
        self.set_data("diagram", self.state.graph.model_dump_json())
        self.draw()
        self.dispatchEvent(Event("diagram-change", bubbles=True))

    def cancel_interaction(self) -> None:
        self.state.cancel()
        pointer = self.pointer
        self.pointer = -1
        if pointer != -1 and self.svg.hasPointerCapture(pointer):
            self.svg.releasePointerCapture(pointer)

    def pointer_down(self, event: PointerEvent) -> None:
        if self.pointer != -1:
            if event.pointerId != self.pointer:
                self.cancel_interaction()
                self.draw()
            return
        if event.button != 0 or interactive_target(event.target):
            return
        self.commit_label()
        self.focus(preventScroll=True)
        rect = self.svg.getBoundingClientRect()
        self.pointer = event.pointerId
        self.state.begin(event.clientX - rect.left, event.clientY - rect.top)
        if event.isTrusted:
            self.svg.setPointerCapture(event.pointerId)
        event.preventDefault()

    def pointer_move(self, event: PointerEvent) -> None:
        if self.pointer == event.pointerId:
            rect = self.svg.getBoundingClientRect()
            self.state.move(event.clientX - rect.left, event.clientY - rect.top)
            self.draw()

    def pointer_up(self, event: PointerEvent) -> None:
        if self.pointer != event.pointerId:
            return
        before = self.state.graph
        rect = self.svg.getBoundingClientRect()
        self.state.finish(event.clientX - rect.left, event.clientY - rect.top)
        self.pointer = -1
        if self.state.graph is not before:
            self.changed()
        else:
            self.draw()

    def pointer_cancel(self, event: PointerEvent) -> None:
        if self.pointer == event.pointerId:
            self.cancel_interaction()
            self.draw()

    def wheel(self, event: WheelEvent) -> None:
        if interactive_target(event.target):
            return
        event.preventDefault()
        if not self.state.active and event.deltaY != 0.0:
            rect = self.svg.getBoundingClientRect()
            self.state.viewport.zoom(0.9 if event.deltaY > 0.0 else 1.1,
                                     event.clientX - rect.left, event.clientY - rect.top)
            self.draw()

    def double_click(self, event: MouseEvent) -> None:
        if interactive_target(event.target):
            return
        rect = self.svg.getBoundingClientRect()
        view = self.state.viewport
        self.start_label(node_at(self.state.graph, view.world_x(event.clientX - rect.left),
                                view.world_y(event.clientY - rect.top)))

    def start_label(self, id: str) -> None:
        node = self.state.index.nodes.get(id)
        if node is not None:
            self.cancel_interaction()
            self.state.select_node(id)
            self.editing = id
            self.label.hidden = False
            self.label.value = node.label
            self.label.focus()
            self.label.select()
            self.draw()

    def commit_label(self) -> None:
        id, text = self.editing, self.label.value
        self.editing = ""
        self.label.hidden = True
        node = self.state.index.nodes.get(id)
        if node is None or text == node.label:
            return
        nodes: list[Node] = []
        for item in self.state.graph.nodes:
            nodes.append(Node(id=item.id, label=text, x=item.x, y=item.y,
                              width=item.width, height=item.height, shape=item.shape)
                         if item.id == id else item)
        self.state.commit(Diagram(nodes=nodes, edges=self.state.graph.edges,
                                  ports=self.state.graph.ports))
        self.changed()

    def label_changed(self, event: Event) -> None:
        event.stopPropagation()
        self.commit_label()

    def label_key(self, event: KeyboardEvent) -> None:
        event.stopPropagation()
        if event.key == "Enter":
            event.preventDefault()
            self.commit_label()
            self.focus()
        elif event.key == "Escape":
            self.editing = ""
            self.label.hidden = True
            self.focus()

    def key(self, event: KeyboardEvent) -> None:
        target = event.target
        if interactive_target(target):
            return
        group = target.closest("[data-node-id]") if isinstance(target, Element) else None
        id = group.getAttribute("data-node-id") if group is not None else None
        if id is not None and (event.key == "Enter" or event.key == " "):
            event.preventDefault()
            self.start_label(id)
            return
        before = self.state.graph
        if event.key == "Escape":
            self.cancel_interaction()
        elif event.key == "Delete" or event.key == "Backspace":
            event.preventDefault()
            self.cancel_interaction()
            if id is not None:
                self.state.select_node(id)
            self.state.delete_selected()
        elif (event.ctrlKey or event.metaKey) and event.key.lower() == "z":
            event.preventDefault()
            self.cancel_interaction()
            if event.shiftKey:
                self.state.redo()
            else:
                self.state.undo()
        if self.state.graph is before:
            self.draw()
        else:
            self.changed()

    def disconnected(self) -> None:
        self.cancel_interaction()
