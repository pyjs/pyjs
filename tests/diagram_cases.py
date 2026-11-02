from pyjs import js
from pyjs.ui.diagram import (
    Diagram,
    DiagramEditor,
    DiagramIndex,
    Edge,
    Node,
    Point,
    Port,
    arrow_points,
    boundary,
    edge_at,
    node_at,
    route_edge,
    validate,
)
from pyjs.ui.diagram_layout import tree_layout


@js
def decision_tree() -> Diagram:
    return Diagram(nodes=[
        Node(id="question", label="Approved?", x=200.0, y=20.0, shape="diamond"),
        Node(id="yes", label="Publish", x=20.0, y=200.0),
        Node(id="no", label="Revise", x=380.0, y=200.0),
    ], edges=[
        Edge(id="yes", source="question", target="yes", label="Yes", routing="orthogonal"),
        Edge(id="no", source="question", target="no", label="No", routing="orthogonal"),
    ])


@js
def editing_workflow() -> None:
    original = decision_tree()
    editor = DiagramEditor(original)
    editor.begin(276.0, 48.0)
    editor.move(306.0, 78.0)
    assert editor.graph is original
    assert editor.preview.nodes[0].x == 230.0
    editor.cancel()
    assert editor.preview is original and len(editor.undo_stack) == 0
    editor.begin(276.0, 48.0)
    editor.finish(306.0, 78.0)
    assert editor.graph.nodes[0].x == 230.0
    assert len(editor.undo_stack) == 1
    moved = editor.graph
    editor.select_node("question")
    editor.delete_selected()
    assert len(editor.graph.nodes) == 2 and not editor.graph.edges
    assert editor.undo() is moved
    assert editor.undo() is original
    assert editor.redo() is moved
    assert len(original.edges) == 2 and original.nodes[0].x == 200.0
    editor.begin(306.0, 78.0)
    editor.move(500.0, 500.0)
    editor.replace_graph(original)
    assert not editor.active and editor.preview is original
    assert editor.finish(500.0, 500.0) is original
    assert not editor.undo_stack and not editor.redo_stack


@js
def geometry_contract() -> None:
    graph = decision_tree()
    validate(graph)
    assert node_at(graph, 200.0, 20.0) == ""
    assert node_at(graph, 276.0, 48.0) == "question"
    index = DiagramIndex(graph)
    path = route_edge(index, graph.edges[0])
    assert len(path) == 4
    assert path[0].x == 200.0 and path[0].y == 48.0
    assert path[-1].x == 172.0 and path[-1].y == 228.0
    assert edge_at(graph, index, path[1].x, 140.0, 1.0) == "yes"
    assert edge_at(graph, index, 0.0, 0.0, 1.0) == ""
    ports = Diagram(nodes=graph.nodes, edges=[
        Edge(id="route", source="yes", target="no", source_port="out", target_port="in"),
        Edge(id="return", source="no", target="yes"),
        Edge(id="again", source="no", target="yes"),
        Edge(id="loop", source="yes", target="yes"),
    ], ports=[Port(id="out", node="yes", side="right"), Port(id="in", node="no", side="left")])
    validate(ports)
    indexed = DiagramIndex(ports)
    path = route_edge(indexed, ports.edges[0])
    assert path[0].x == 172.0 and path[1].x == 380.0
    assert len(route_edge(indexed, ports.edges[3])) == 5
    editor = DiagramEditor(ports)
    editor.selected_nodes = ["yes", "no"]
    editor.viewport.scale = 2.0
    editor.begin(50.0, 410.0)
    editor.finish(70.0, 430.0)
    assert editor.graph.nodes[1].x == 30.0 and editor.graph.nodes[2].x == 390.0
    editor.delete_selected()
    assert not editor.graph.edges and not editor.graph.ports

    box = Node(id="box", label="", x=0.0, y=0.0, width=100.0, height=60.0)
    center = Point(50.0, 30.0)
    point = boundary(box, Point(150.0, 30.0))
    assert point.x == 100.0 and point.y == 30.0
    point = boundary(box, center)
    assert point.x == center.x and point.y == center.y
    tip = Point(20.0, 0.0)
    head = arrow_points([Point(0.0, 0.0), tip, tip])
    assert len(head) == 3 and head[1] is tip
    assert head[0].x == 11.0 and head[0].y == -4.5
    assert head[2].x == 11.0 and head[2].y == 4.5
    assert not arrow_points([tip, tip])


@js
def viewport_contract() -> None:
    editor = DiagramEditor(decision_tree())
    editor.viewport.zoom(2.0, 100.0, 100.0)
    assert editor.viewport.world_x(100.0) == 100.0
    editor.begin(0.0, 0.0)
    editor.move(20.0, 30.0)
    editor.cancel()
    assert editor.viewport.x == -100.0 and editor.viewport.y == -100.0
    editor.begin(0.0, 0.0)
    editor.finish(20.0, 30.0)
    assert editor.viewport.x == -80.0 and editor.viewport.y == -70.0
    assert not editor.undo_stack
    editor.viewport.fit(editor.graph, 320.0, 240.0)
    for node in editor.graph.nodes:
        assert node.x * editor.viewport.scale + editor.viewport.x >= 0.0
        assert (node.x + node.width) * editor.viewport.scale + editor.viewport.x <= 320.0


@js
def layout_contract() -> None:
    original = decision_tree()
    editor = DiagramEditor(original)
    result = tree_layout(original)
    validate(result)
    root, yes, no = result.nodes[0], result.nodes[1], result.nodes[2]
    assert root.x == 96.0 and root.y == 0.0
    assert yes.x == 0.0 and yes.y == 120.0
    assert no.x == 192.0 and no.y == 120.0
    assert result.edges[0] is original.edges[0]
    editor.commit(result)
    assert editor.undo() is original
    horizontal = tree_layout(original, horizontal=True)
    assert horizontal.nodes[1].x == 216.0 and horizontal.nodes[2].y == 96.0
    assert original.nodes[0].x == 200.0
