import pytest

from pyjs.ui.diagram import Diagram, DiagramEditor, Edge, Node, Port
from tests import diagram_cases


@pytest.mark.parametrize("scenario", ["editing_workflow", "geometry_contract", "viewport_contract", "layout_contract"])
def test_portable_diagram_contract(scenario):
    getattr(diagram_cases, scenario)()


@pytest.mark.parametrize("graph,match", [
    (Diagram(nodes=[Node(id="a", label="", x=float("nan"), y=0.0)], edges=[]), "finite"),
    (Diagram(nodes=[Node(id="a", label="", x=0.0, y=0.0, width=0.0)], edges=[]), "positive"),
    (Diagram(nodes=[], edges=[Edge(id="a", source="x", target="x")]), "existing"),
    (Diagram(nodes=[], edges=[], ports=[Port(id="p", node="x", side="left")]), "existing"),
])
def test_invalid_graph_is_rejected_before_replacing_a_live_preview(graph, match):
    state = DiagramEditor(diagram_cases.decision_tree())
    state.begin(276.0, 48.0)
    state.move(300.0, 70.0)
    preview = state.preview
    with pytest.raises(ValueError, match=match):
        state.replace_graph(graph)
    assert state.active and state.preview is preview


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_invalid_pointer_up_cancels_instead_of_saving_a_preview(invalid):
    state = DiagramEditor(diagram_cases.decision_tree())
    original = state.graph
    state.begin(276.0, 48.0)
    state.move(300.0, 70.0)
    assert state.finish(invalid, 70.0) is original
    assert not state.active and not state.undo_stack


def test_rejected_commit_preserves_history_and_ports_cannot_attach_to_another_node():
    state = DiagramEditor(diagram_cases.decision_tree())
    invalid = Diagram(nodes=state.graph.nodes,
                      edges=[Edge(id="bad", source="yes", target="no", source_port="p")],
                      ports=[Port(id="p", node="no", side="left")])
    before = state.graph
    with pytest.raises(ValueError, match="belong"):
        state.commit(invalid)
    assert state.graph is before and state.undo_stack == []


def test_history_is_bounded_and_new_edits_replace_redo_but_selection_does_not():
    state = DiagramEditor(diagram_cases.decision_tree(), history_limit=2)
    for step in range(3):
        state.begin(276.0 + step * 20, 48.0)
        state.finish(296.0 + step * 20, 48.0)
    assert len(state.undo_stack) == 2
    assert state.undo().nodes[0].x == 240.0
    state.select_node("no")
    assert len(state.redo_stack) == 1
    state.delete_selected()
    assert not state.redo_stack


@pytest.mark.parametrize("edges,match", [
    ([Edge(id="self", source="question", target="question")], "cycles"),
    ([Edge(id="a", source="question", target="yes"),
      Edge(id="b", source="yes", target="question")], "cycles"),
    ([Edge(id="a", source="question", target="yes"),
      Edge(id="b", source="no", target="yes")], "parent"),
    ([Edge(id="a", source="question", target="yes", directed=False)], "directed"),
])
def test_tree_layout_rejects_non_tree_graphs_without_changing_them(edges, match):
    from pyjs.ui.diagram_layout import tree_layout

    original = diagram_cases.decision_tree()
    graph = Diagram(nodes=original.nodes, edges=edges)
    before = graph.model_dump_json()
    with pytest.raises(ValueError, match=match):
        tree_layout(graph)
    assert graph.model_dump_json() == before


def test_variable_size_forest_layout_is_order_stable_and_nonoverlapping():
    from pyjs.ui.diagram_layout import tree_layout

    graph = diagram_cases.decision_tree()
    graph.nodes[1].width = 350.0
    graph.nodes[2].height = 150.0
    graph.nodes.append(Node(id="island", label="Separate", x=0.0, y=0.0))
    result = tree_layout(graph)
    assert result.nodes[2].x >= result.nodes[1].x + result.nodes[1].width + 40.0
    assert result.nodes[3].x >= result.nodes[2].x + result.nodes[2].width + 40.0
    again = tree_layout(result)
    assert again.model_dump() == result.model_dump()


def test_deep_tree_layout_uses_no_python_recursion():
    from pyjs.ui.diagram_layout import tree_layout

    nodes = [Node(id=str(i), label=str(i), x=0.0, y=0.0) for i in range(1200)]
    edges = [Edge(id=str(i), source=str(i - 1), target=str(i)) for i in range(1, 1200)]
    result = tree_layout(Diagram(nodes=nodes, edges=edges))
    assert result.nodes[-1].y == 1199 * 120.0
