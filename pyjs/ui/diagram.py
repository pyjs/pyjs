"""Portable diagram geometry and editing, independent of rendering and storage.

Treat published models as snapshots. Editing functions return new models and
share unchanged objects; callers must not mutate a snapshot in place.
"""
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field

from pyjs import js
from pyjs.ui.diagram_geometry import Point, arrow_points, boundary_point

__all__ = [
    "Diagram", "DiagramEditor", "DiagramIndex", "Edge", "Node", "Point", "Port",
    "Viewport", "arrow_points", "boundary", "bounds", "delete_selection", "edge_at",
    "move_nodes", "moved", "node_at", "port_point", "route_edge",
    "segment_distance_squared", "validate",
]


@js
class Node(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    label: str
    x: float
    y: float
    width: float = 152.0
    height: float = 56.0
    shape: str = "rectangle"


@js
class Port(BaseModel):
    """A named boundary attachment; offset runs left-to-right or top-to-bottom."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    node: str
    side: str
    offset: float = 0.5


@js
class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    source: str
    target: str
    label: str = ""
    directed: bool = True
    source_port: str = ""
    target_port: str = ""
    routing: str = "straight"


@js
class Diagram(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    nodes: list[Node]
    edges: list[Edge]
    ports: list[Port] = Field(default_factory=list)


@js
class DiagramIndex:
    """Build once per snapshot, then reuse for geometry and rendering."""

    def __init__(self, graph: Diagram):
        self.nodes: dict[str, Node] = {}
        self.ports: dict[str, Port] = {}
        for node in graph.nodes:
            self.nodes[node.id] = node
        for port in graph.ports:
            self.ports[port.id] = port


@js
def validate(graph: Diagram) -> None:
    nodes: set[str] = set()
    ports: dict[str, str] = {}
    edges: set[str] = set()
    for node in graph.nodes:
        if not node.id or node.id in nodes:
            raise ValueError("Node IDs must be nonempty and unique")
        if (not isfinite(node.x) or not isfinite(node.y)
                or not isfinite(node.width) or not isfinite(node.height)
                or not isfinite(node.x + node.width) or not isfinite(node.y + node.height)
                or node.width <= 0.0 or node.height <= 0.0):
            raise ValueError("Nodes require finite positions and positive sizes")
        if node.shape not in {"rectangle", "diamond"}:
            raise ValueError("Unsupported node shape")
        nodes.add(node.id)
    for port in graph.ports:
        if not port.id or port.id in ports or port.node not in nodes:
            raise ValueError("Ports require unique IDs and existing nodes")
        if (port.side not in {"left", "right", "top", "bottom"}
                or not isfinite(port.offset) or not 0.0 <= port.offset <= 1.0):
            raise ValueError("Invalid port side or offset")
        ports[port.id] = port.node
    for edge in graph.edges:
        if not edge.id or edge.id in edges:
            raise ValueError("Edge IDs must be nonempty and unique")
        if edge.source not in nodes or edge.target not in nodes:
            raise ValueError("Edges require existing nodes")
        if ((edge.source_port and ports.get(edge.source_port) != edge.source)
                or (edge.target_port and ports.get(edge.target_port) != edge.target)):
            raise ValueError("Edge ports must belong to their endpoint nodes")
        if edge.routing not in {"straight", "orthogonal"}:
            raise ValueError("Unsupported edge routing")
        edges.add(edge.id)


@js
def moved(node: Node, x: float, y: float) -> Node:
    return Node(id=node.id, label=node.label, x=x, y=y, width=node.width,
                height=node.height, shape=node.shape)


@js
def move_nodes(graph: Diagram, ids: list[str], dx: float, dy: float) -> Diagram:
    if not isfinite(dx) or not isfinite(dy) or (dx == 0.0 and dy == 0.0):
        return graph
    selected = set(ids)
    result: list[Node] = []
    changed = False
    for node in graph.nodes:
        if node.id in selected:
            x, y = node.x + dx, node.y + dy
            if not isfinite(x + node.width) or not isfinite(y + node.height):
                return graph
            node = moved(node, x, y)
            changed = True
        result.append(node)
    return Diagram(nodes=result, edges=graph.edges, ports=graph.ports) if changed else graph


@js
def delete_selection(graph: Diagram, nodes: list[str], edges: list[str]) -> Diagram:
    removed_nodes, removed_edges = set(nodes), set(edges)
    remaining_nodes: list[Node] = []
    remaining_edges: list[Edge] = []
    remaining_ports: list[Port] = []
    for node in graph.nodes:
        if node.id not in removed_nodes:
            remaining_nodes.append(node)
    for edge in graph.edges:
        if (edge.id not in removed_edges and edge.source not in removed_nodes
                and edge.target not in removed_nodes):
            remaining_edges.append(edge)
    for port in graph.ports:
        if port.node not in removed_nodes:
            remaining_ports.append(port)
    if len(remaining_nodes) == len(graph.nodes) and len(remaining_edges) == len(graph.edges):
        return graph
    return Diagram(nodes=remaining_nodes, edges=remaining_edges, ports=remaining_ports)


@js
def node_at(graph: Diagram, x: float, y: float) -> str:
    if not isfinite(x) or not isfinite(y):
        return ""
    for index in range(len(graph.nodes) - 1, -1, -1):
        node = graph.nodes[index]
        if node.x <= x <= node.x + node.width and node.y <= y <= node.y + node.height:
            if (node.shape != "diamond" or
                    abs((x - node.x) / node.width - 0.5)
                    + abs((y - node.y) / node.height - 0.5) <= 0.5):
                return node.id
    return ""


@js
def boundary(node: Node, toward: Point) -> Point:
    center = Point(node.x + node.width / 2.0, node.y + node.height / 2.0)
    return boundary_point(center, node.width, node.height, toward, node.shape == "diamond")


@js
def port_point(node: Node, port: Port) -> Point:
    x, y = node.x + node.width * port.offset, node.y + node.height * port.offset
    if port.side == "top" or port.side == "bottom":
        y = node.y if port.side == "top" else node.y + node.height
    else:
        x = node.x if port.side == "left" else node.x + node.width
    return boundary(node, Point(x, y))


@js
def route_edge(index: DiagramIndex, edge: Edge) -> list[Point]:
    """Return the same world-space polyline for painting and hit testing.

    Orthogonal routing uses a midpoint elbow, not obstacle avoidance. Explicit
    ports control attachments; parallel edges may share a route.
    """
    start, end = index.nodes[edge.source], index.nodes[edge.target]
    source_port, target_port = index.ports.get(edge.source_port), index.ports.get(edge.target_port)
    a = Point(start.x + start.width / 2.0, start.y + start.height / 2.0)
    b = Point(end.x + end.width / 2.0, end.y + end.height / 2.0)
    if edge.source == edge.target:
        a = port_point(start, source_port) if source_port is not None else Point(start.x + start.width, a.y)
        b = port_point(end, target_port) if target_port is not None else Point(b.x, end.y)
        right, top = start.x + start.width + 24.0, start.y - 24.0
        return [a, Point(right, a.y), Point(right, top), Point(b.x, top), b]
    if source_port is not None:
        a = port_point(start, source_port)
    if target_port is not None:
        b = port_point(end, target_port)
    if edge.routing == "orthogonal":
        horizontal = abs(b.x - a.x) >= abs(b.y - a.y)
        if source_port is not None:
            horizontal = source_port.side == "left" or source_port.side == "right"
        if horizontal:
            mid = (a.x + b.x) / 2.0
            first, last = Point(mid, a.y), Point(mid, b.y)
        else:
            mid = (a.y + b.y) / 2.0
            first, last = Point(a.x, mid), Point(b.x, mid)
        a = a if source_port is not None else boundary(start, first)
        b = b if target_port is not None else boundary(end, last)
        return [a, first, last, b]
    first = a if source_port is not None else boundary(start, b)
    last = b if target_port is not None else boundary(end, a)
    return [first, last]


@js
def segment_distance_squared(x: float, y: float, x1: float, y1: float,
                             x2: float, y2: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    length = dx * dx + dy * dy
    projection = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length)) if length else 0.0
    offset_x, offset_y = x - x1 - projection * dx, y - y1 - projection * dy
    return offset_x * offset_x + offset_y * offset_y


@js
def edge_at(graph: Diagram, index: DiagramIndex, x: float, y: float,
            tolerance: float = 12.0) -> str:
    if not isfinite(x) or not isfinite(y) or not isfinite(tolerance) or tolerance < 0.0:
        return ""
    closest, selected = tolerance * tolerance, ""
    for edge in graph.edges:
        points = route_edge(index, edge)
        for i in range(1, len(points)):
            a, b = points[i - 1], points[i]
            distance = segment_distance_squared(x, y, a.x, a.y, b.x, b.y)
            if distance <= closest and (not selected or distance < closest):
                closest, selected = distance, edge.id
    return selected


@js
def bounds(graph: Diagram) -> tuple[float, float, float, float]:
    if not graph.nodes:
        return 0.0, 0.0, 152.0, 56.0
    first = graph.nodes[0]
    left, top, right, bottom = first.x, first.y, first.x + first.width, first.y + first.height
    for node in graph.nodes:
        left, top = min(left, node.x), min(top, node.y)
        right, bottom = max(right, node.x + node.width), max(bottom, node.y + node.height)
    return left, top, right, bottom


@js
class Viewport:
    """World-to-screen transform in logical pixels, independent of device DPR."""

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.scale = 1.0

    def world_x(self, x: float) -> float:
        return (x - self.x) / self.scale

    def world_y(self, y: float) -> float:
        return (y - self.y) / self.scale

    def zoom(self, factor: float, x: float, y: float) -> None:
        if not isfinite(factor) or factor <= 0.0 or not isfinite(x) or not isfinite(y):
            return
        wx, wy = self.world_x(x), self.world_y(y)
        scale = max(0.35, min(3.0, self.scale * factor))
        nx, ny = x - wx * scale, y - wy * scale
        if isfinite(nx) and isfinite(ny):
            self.x = nx
            self.y = ny
            self.scale = scale

    def fit(self, graph: Diagram, width: float, height: float) -> None:
        if (not isfinite(width) or not isfinite(height)
                or width <= 0.0 or height <= 0.0 or not graph.nodes):
            self.x = 0.0
            self.y = 0.0
            self.scale = 1.0
            return
        left, top, right, bottom = bounds(graph)
        self.scale = min(1.0, width / (right - left + 24.0), height / (bottom - top + 24.0))
        self.x = width / 2.0 - (left + (right - left) / 2.0) * self.scale
        self.y = height / 2.0 - (top + (bottom - top) / 2.0) * self.scale


@js
class DiagramEditor:
    """Transactional edits and screen-coordinate gestures.

    External replacements cancel previews and clear local undo history. Apps
    with document-wide undo can set history_limit=0 and record committed graph
    changes in their own history. Selection and pan are never document edits.
    """

    def __init__(self, graph: Diagram, history_limit: int = 100):
        validate(graph)
        self.graph = graph
        self.preview = graph
        self.index = DiagramIndex(graph)
        self.viewport = Viewport()
        self.selected_nodes: list[str] = []
        self.selected_edges: list[str] = []
        self.undo_stack: list[Diagram] = []
        self.redo_stack: list[Diagram] = []
        self.history_limit = max(0, history_limit)
        self.active = False
        self.dragged = False
        self.node_id = ""
        self.start_x = 0.0
        self.start_y = 0.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.drag_nodes: list[str] = []
        self.toggle_selection = True
        self.group_drag = True

    def _install(self, graph: Diagram) -> Diagram:
        self.graph = graph
        self.preview = graph
        self.index = DiagramIndex(graph)
        nodes: list[str] = []
        edges: list[str] = []
        for id in self.selected_nodes:
            if id in self.index.nodes:
                nodes.append(id)
        for edge in graph.edges:
            if edge.id in self.selected_edges:
                edges.append(edge.id)
        self.selected_nodes = nodes
        self.selected_edges = edges
        return graph

    def replace_graph(self, graph: Diagram) -> Diagram:
        validate(graph)
        self.cancel()
        self.undo_stack = []
        self.redo_stack = []
        return self._install(graph)

    def commit(self, graph: Diagram) -> Diagram:
        validate(graph)
        self.cancel()
        if graph is self.graph:
            return graph
        if self.history_limit:
            self.undo_stack.append(self.graph)
            if len(self.undo_stack) > self.history_limit:
                self.undo_stack.pop(0)
        self.redo_stack = []
        return self._install(graph)

    def undo(self) -> Diagram:
        self.cancel()
        if self.undo_stack:
            self.redo_stack.append(self.graph)
            self._install(self.undo_stack.pop())
        return self.graph

    def redo(self) -> Diagram:
        self.cancel()
        if self.redo_stack:
            self.undo_stack.append(self.graph)
            self._install(self.redo_stack.pop())
        return self.graph

    def select_node(self, node_id: str) -> None:
        self.selected_nodes = [node_id] if node_id in self.index.nodes else []
        self.selected_edges = []

    def delete_selected(self) -> Diagram:
        graph = delete_selection(self.graph, self.selected_nodes, self.selected_edges)
        self.commit(graph)
        self.selected_nodes = []
        self.selected_edges = []
        return self.graph

    def begin(self, x: float, y: float) -> None:
        self.cancel()
        if not isfinite(x) or not isfinite(y):
            return
        self.active = True
        self.start_x = x
        self.start_y = y
        self.pan_x = self.viewport.x
        self.pan_y = self.viewport.y
        self.node_id = node_at(self.graph, self.viewport.world_x(x), self.viewport.world_y(y))
        self.drag_nodes = list(self.selected_nodes) if self.group_drag and self.node_id in self.selected_nodes else [self.node_id]

    def move(self, x: float, y: float) -> None:
        if not self.active or not isfinite(x) or not isfinite(y):
            return
        dx, dy = x - self.start_x, y - self.start_y
        if not isfinite(dx) or not isfinite(dy):
            return
        if dx * dx + dy * dy >= 16.0:
            self.dragged = True
        if not self.dragged:
            return
        if self.node_id:
            self.preview = move_nodes(self.graph, self.drag_nodes,
                                      dx / self.viewport.scale, dy / self.viewport.scale)
        elif isfinite(self.pan_x + dx) and isfinite(self.pan_y + dy):
            self.viewport.x = self.pan_x + dx
            self.viewport.y = self.pan_y + dy

    def finish(self, x: float, y: float) -> Diagram:
        if not isfinite(x) or not isfinite(y):
            self.cancel()
        if not self.active:
            return self.graph
        self.move(x, y)
        if not self.dragged:
            if self.node_id:
                self.selected_edges = []
                if not self.toggle_selection:
                    self.selected_nodes = [self.node_id]
                elif self.node_id in self.selected_nodes:
                    self.selected_nodes.remove(self.node_id)
                else:
                    self.selected_nodes.append(self.node_id)
            else:
                edge = edge_at(self.graph, self.index, self.viewport.world_x(x),
                               self.viewport.world_y(y), 12.0 / self.viewport.scale)
                self.selected_nodes = []
                if not edge:
                    self.selected_edges = []
                elif not self.toggle_selection:
                    self.selected_edges = [edge]
                elif edge in self.selected_edges:
                    self.selected_edges.remove(edge)
                else:
                    self.selected_edges.append(edge)
        graph = self.preview
        self.active = False
        return self.commit(graph) if graph is not self.graph else self.graph

    def cancel(self) -> None:
        if self.active:
            self.viewport.x = self.pan_x
            self.viewport.y = self.pan_y
        self.active = False
        self.dragged = False
        self.preview = self.graph
