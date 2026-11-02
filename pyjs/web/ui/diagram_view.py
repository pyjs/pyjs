"""Read-only SVG diagrams with accessible activation and HTML node content."""
from collections.abc import Callable

from pyjs import js
from pyjs.ui.diagram import (
    Diagram,
    DiagramIndex,
    Node,
    Point,
    Viewport,
    arrow_points,
    route_edge,
    validate,
)
from pyjs.web.dom import Element, document
from pyjs.web.domx import CustomElement, div, ref
from pyjs.web.events import CustomEvent, KeyboardEvent, MouseEvent


@js
def default_node(node: Node, previous: Element | None) -> Element:
    if previous is None:
        previous = div({"style": "box-sizing:border-box;width:100%;height:100%;"
                        "display:flex;align-items:center;justify-content:center;"
                        "padding:8px 12px;text-align:center;font:14px system-ui;"
                        "color:#1e293b;white-space:pre-wrap;overflow-wrap:anywhere;"
                        "overflow:hidden;pointer-events:none"})
    if previous.textContent != node.label:
        previous.textContent = node.label
    return previous


@js
def interactive_target(target: object) -> bool:
    return isinstance(target, Element) and target.closest(
        "a,button,input,textarea,select,[contenteditable],"
        "[data-diagram-interactive]") is not None


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
def draw_diagram(layer: Element, graph: Diagram, nodes: list[str], edges: list[str],
                 render_node: Callable[[Node, Element | None], Element] = default_node) -> None:
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
            group = svg_element("g", {"data-node-id": node.id, "role": "group"})
            group.append(svg_element("path", {"role": "button", "tabindex": "0",
                                              "data-node-activate": node.id}),
                         svg_element("foreignObject", {"x": "0", "y": "0"}),
                         svg_element("title", {}))
        group.setAttribute("transform", f"translate({node.x} {node.y})")
        group.setAttribute("aria-label", node.label)
        group.children[0].setAttribute("aria-label", node.label)
        group.children[0].setAttribute("aria-pressed", "true" if node.id in nodes else "false")
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
        container = group.children[1]
        svg_attributes(container, {"width": str(w), "height": str(h)})
        previous = container.firstElementChild
        content = render_node(node, previous)
        if content is not previous:
            container.replaceChildren(content)
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
def diagram_svg(graph: Diagram, width: float = 640.0, height: float = 420.0,
                label: str = "Diagram") -> Element:
    """Static SVG for server rendering; no custom element or event handlers."""
    validate(graph)
    view = Viewport()
    view.fit(graph, width, height)
    svg = svg_element("svg", {"width": str(width), "height": str(height),
                              "viewBox": f"0 0 {width} {height}", "role": "img",
                              "aria-label": label})
    layer = svg_element("g", {"transform": f"translate({view.x} {view.y}) scale({view.scale})"})
    draw_diagram(layer, graph, [], [])
    for group in layer.children:
        if group.getAttribute("data-node-id") is not None:
            group.children[0].removeAttribute("tabindex")
            group.children[0].removeAttribute("role")
            group.children[0].removeAttribute("aria-pressed")
    svg.append(layer)
    return svg


@js
class DiagramView(CustomElement):
    """Read-only viewer with bubbling diagram-node-activate events (ID detail).

    Override render_node(node, previous) to compose HTML with ordinary PyJS
    primitives. Reuse previous content on redraws to preserve focus and state.
    Node width/height define its content box, hit bounds and edge attachments.
    """

    def __init__(self, graph: Diagram | None = None):
        super().__init__()
        self._graph = graph if graph is not None else Diagram(nodes=[], edges=[])
        validate(self._graph)
        self.viewport = Viewport()
        self.set_data("diagram", self._graph.model_dump_json())
        self.svg = ref(svg_element("svg", {"width": "100%", "height": "420",
                                           "role": "group", "aria-label": "Diagram",
                                           "style": "display:block"}))
        self.layer = ref(self.create_layer(self._graph))
        self.svg.append(self.layer)
        self.append(self.svg)

    def create_layer(self, graph: Diagram) -> Element:
        layer = svg_element("g", {})
        draw_diagram(layer, graph, [], [], self.render_node)
        return layer

    def render_node(self, node: Node, previous: Element | None) -> Element:
        return default_node(node, previous)

    def bind_events(self) -> None:
        self.svg.addEventListener("click", self.click_node)
        self.addEventListener("keydown", self.key)

    def get_graph(self) -> Diagram:
        return self._graph

    def restore(self) -> None:
        if self.get_data("self-id") is not None:
            source = self.get_data("diagram")
            self._graph = Diagram.model_validate_json(source) if source else Diagram(nodes=[], edges=[])
            validate(self._graph)
            self.viewport = Viewport()

    def initialize(self) -> None:
        self.restore()
        self.fit()
        self.bind_events()

    def reconnected(self) -> None:
        self.draw()

    def configure(self, graph: Diagram) -> None:
        validate(graph)
        self._graph = graph
        self.set_data("diagram", graph.model_dump_json())
        self.draw()

    def fit(self) -> None:
        rect = self.svg.getBoundingClientRect()
        self.viewport.fit(self.get_graph(), rect.width, rect.height)
        self.draw()

    def paint(self, graph: Diagram, nodes: list[str], edges: list[str]) -> None:
        view = self.viewport
        self.layer.setAttribute("transform", f"translate({view.x} {view.y}) scale({view.scale})")
        draw_diagram(self.layer, graph, nodes, edges, self.render_node)

    def draw(self) -> None:
        self.paint(self.get_graph(), [], [])

    def activate_node(self, target: object) -> None:
        if not isinstance(target, Element) or interactive_target(target):
            return
        group = target.closest("[data-node-id]")
        if group is not None and self.layer.contains(group):
            self.dispatchEvent(CustomEvent("diagram-node-activate", bubbles=True,
                                           detail=group.getAttribute("data-node-id")))

    def click_node(self, event: MouseEvent) -> None:
        self.activate_node(event.target)

    def key(self, event: KeyboardEvent) -> None:
        if not interactive_target(event.target) and (event.key == "Enter" or event.key == " "):
            event.preventDefault()
            self.activate_node(event.target)
