"""SVG diagram rendering and a keyboard/pointer editing surface."""
from pyjs import js
from pyjs.ui.diagram import (
    Diagram,
    DiagramEditor,
    DiagramIndex,
    Node,
    Point,
    arrow_points,
    node_at,
    route_edge,
)
from pyjs.web.dom import Element, document
from pyjs.web.domx import CustomElement, input, ref, tw
from pyjs.web.events import Event, KeyboardEvent, MouseEvent, PointerEvent, WheelEvent


@js
def svg_attributes(element: Element, attributes: dict[str, str]) -> None:
    for key in attributes:
        element.setAttribute(key, attributes[key])


@js
def svg_element(name: str, attributes: dict[str, str]) -> Element:
    element = document.createElementNS("http://www.w3.org/2000/svg", name)
    svg_attributes(element, attributes)
    return element


@js
def path_data(points: list[Point]) -> str:
    result = ""
    for point in points:
        result += ("M" if not result else " L") + str(point.x) + " " + str(point.y)
    return result


@js
def draw_diagram(layer: Element, graph: Diagram, nodes: list[str], edges: list[str]) -> None:
    # Keep pointer targets alive across redraws so native click/double-click
    # synthesis survives pointer-up commits and selection changes.
    existing_nodes: dict[str, Element] = {}
    existing_edges: dict[str, Element] = {}
    for child in layer.children:
        node_id, edge_id = child.getAttribute("data-node-id"), child.getAttribute("data-edge-id")
        if node_id is not None:
            existing_nodes[node_id] = child
        elif edge_id is not None:
            existing_edges[edge_id] = child
    ordered: list[Element] = []
    index = DiagramIndex(graph)
    for edge in graph.edges:
        group = existing_edges.get(edge.id)
        if group is None:
            group = svg_element("g", {"data-edge-id": edge.id, "fill": "none", "stroke-width": "2"})
            group.append(svg_element("path", {}), svg_element("path", {}),
                         svg_element("text", {"fill": "#475569", "stroke": "none",
                                              "font-size": "13", "text-anchor": "middle"}))
        group.setAttribute("stroke", "#d97706" if edge.id in edges else "#94a3b8")
        points = route_edge(index, edge)
        group.children[0].setAttribute("d", path_data(points))
        group.children[1].setAttribute("d", path_data(arrow_points(points)) if edge.directed else "")
        middle = len(points) // 2
        a, b = points[middle - 1], points[middle]
        vertical = a.x == b.x and a.y != b.y
        svg_attributes(group.children[2], {
            "x": str((a.x + b.x) / 2.0 + (8.0 if vertical else 0.0)),
            "y": str((a.y + b.y) / 2.0 - (0.0 if vertical else 8.0)),
            "text-anchor": "start" if vertical else "middle",
        })
        group.children[2].textContent = edge.label
        ordered.append(group)
    for node in graph.nodes:
        group = existing_nodes.get(node.id)
        if group is None:
            group = svg_element("g", {"data-node-id": node.id, "role": "button", "tabindex": "0"})
            group.append(svg_element("path", {}), svg_element("text", {
                "fill": "#1e293b", "font-size": "14", "text-anchor": "middle",
                "pointer-events": "none"}), svg_element("title", {}))
        group.setAttribute("transform", f"translate({node.x} {node.y})")
        group.setAttribute("aria-label", node.label)
        group.setAttribute("aria-pressed", "true" if node.id in nodes else "false")
        w, h = node.width, node.height
        if node.shape == "diamond":
            outline = f"M{w / 2.0} 0 L{w} {h / 2.0} L{w / 2.0} {h} L0 {h / 2.0} Z"
        else:
            radius = min(12.0, w / 2.0, h / 2.0)
            outline = (f"M{radius} 0 H{w - radius} Q{w} 0 {w} {radius} V{h - radius} "
                       f"Q{w} {h} {w - radius} {h} H{radius} Q0 {h} 0 {h - radius} "
                       f"V{radius} Q0 0 {radius} 0 Z")
        svg_attributes(group.children[0], {
            "d": outline, "fill": "#fffbeb" if node.id in nodes else "#f8fafc",
            "stroke": "#d97706" if node.id in nodes else "#64748b", "stroke-width": "2",
        })
        svg_attributes(group.children[1], {"x": str(w / 2.0), "y": str(h / 2.0 + 5.0)})
        group.children[1].textContent = node.label[:17] + "…" if len(node.label) > 20 else node.label
        group.children[2].textContent = node.label
        ordered.append(group)
    for i in range(len(ordered)):
        child = ordered[i]
        if i >= len(layer.children):
            layer.append(child)
        elif layer.children[i] is not child:
            layer.insertBefore(child, layer.children[i])
    while len(layer.children) > len(ordered):
        layer.children[len(ordered)].remove()


@js
def _diagram_layer(graph: Diagram) -> Element:
    layer = svg_element("g", {})
    draw_diagram(layer, graph, [], [])
    return layer


@js
class DiagramCanvas(CustomElement):
    """Editable diagram surface; emits bubbling ``diagram-change`` on commits.

    ``state`` exposes portable commands. After a programmatic commit call
    ``changed()``; after selection or viewport changes call ``draw()``.
    Toolbars, persistence and domain rules belong to the application.
    """

    def __init__(self, graph: Diagram | None = None):
        super().__init__()
        self.state = DiagramEditor(graph if graph is not None else Diagram(nodes=[], edges=[]))
        self.set_data("diagram", self.state.graph.model_dump_json())
        self.pointer = -1
        self.editing = ""
        self.setAttribute("tabindex", "0")
        self.setAttribute("aria-label", "Diagram editor")
        self.svg = ref(svg_element("svg", {"width": "100%", "height": "420",
                                           "role": "group", "aria-label": "Diagram canvas"}))
        self.svg.setAttribute("style", "touch-action:none;user-select:none;display:block")
        self.layer = ref(_diagram_layer(self.state.graph))
        self.svg.append(self.layer)
        self.label = ref(input(tw("w-full rounded border border-slate-400 px-3 py-2"),
                               {"aria-label": "Node label"}))
        self.label.hidden = True
        self.label.addEventListener("keydown", self.label_key)
        self.label.addEventListener("change", self.label_changed)
        self.append(self.label, self.svg)
        self.svg.addEventListener("pointerdown", self.pointer_down)
        self.svg.addEventListener("pointermove", self.pointer_move)
        self.svg.addEventListener("pointerup", self.pointer_up)
        self.svg.addEventListener("pointercancel", self.pointer_cancel)
        self.svg.addEventListener("lostpointercapture", self.pointer_cancel)
        self.svg.addEventListener("dblclick", self.double_click)
        self.svg.addEventListener("wheel", self.wheel)
        self.addEventListener("keydown", self.key)

    def configure(self, graph: Diagram) -> None:
        self.state.replace_graph(graph)
        self.set_data("diagram", graph.model_dump_json())
        self.cancel_interaction()
        self.editing = ""
        self.label.hidden = True
        self.draw()

    def initialize(self) -> None:
        if self.get_data("self-id") is not None:
            source = self.get_data("diagram")
            self.state = DiagramEditor(Diagram.model_validate_json(source) if source
                                       else Diagram(nodes=[], edges=[]))
            self.pointer = -1
            self.editing = ""
        rect = self.svg.getBoundingClientRect()
        self.state.viewport.fit(self.state.graph, rect.width, rect.height)
        self.draw()

    def reconnected(self) -> None:
        self.draw()

    def draw(self) -> None:
        view = self.state.viewport
        self.layer.setAttribute("transform", f"translate({view.x} {view.y}) scale({view.scale})")
        draw_diagram(self.layer, self.state.preview, self.state.selected_nodes, self.state.selected_edges)

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
        if event.button != 0:
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
        event.preventDefault()
        if not self.state.active and event.deltaY != 0.0:
            rect = self.svg.getBoundingClientRect()
            self.state.viewport.zoom(0.9 if event.deltaY > 0.0 else 1.1,
                                     event.clientX - rect.left, event.clientY - rect.top)
            self.draw()

    def double_click(self, event: MouseEvent) -> None:
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
        id = target.getAttribute("data-node-id") if isinstance(target, Element) else None
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
