from pyjs import js
from pyjs.ui.diagram import Diagram, Edge, Node
from pyjs.ui.diagram_layout import tree_layout
from pyjs.web.crypto import crypto
from pyjs.web.dom import Element
from pyjs.web.domx import div, ref, tag, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget
from pyjs.web.ui.button import Button
from pyjs.web.ui.diagram import DiagramCanvas


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
def diagram_toolbar() -> Element:
    toolbar = div(tw("flex flex-wrap gap-2"), {"aria-label": "Diagram commands"})
    for action, title in [("add", "Add step"), ("connect", "Connect selection"),
                          ("delete", "Delete"), ("undo", "Undo"), ("redo", "Redo"),
                          ("layout", "Arrange tree"), ("fit", "Fit diagram")]:
        control = Button(title, variant="outline")
        control.element.setAttribute("data-diagram-action", action)
        toolbar.append(control.element)
    return toolbar


@js
class DiagramsApp(Widget):
    def __init__(self):
        super().__init__()
        self.canvas = ref(DiagramCanvas(decision_tree()))
        self.status = ref(tag("p", {"role": "status"}, "Select nodes to connect them; double-click to edit labels."))
        self.toolbar = ref(diagram_toolbar())
        self.toolbar.addEventListener("click", self.action)
        self.add(tw("mx-auto block max-w-5xl space-y-4 p-6"),
                 tag("h1", tw("text-2xl font-semibold"), "Decision tree"),
                 tag("p", tw("text-slate-600"), "Drag steps, label decisions and undo changes. "
                     "The model and geometry are shared by Python and the browser."),
                 self.toolbar, self.canvas, self.status)
        self.canvas.addEventListener("diagram-change", self.updated)

    def updated(self, event: Event) -> None:
        self.status.textContent = "Diagram updated. Changes remain in this demonstration only."

    def action(self, event: Event) -> None:
        target = event.target
        if not isinstance(target, Element):
            return
        target = target.closest("[data-diagram-action]")
        if target is None or not self.toolbar.contains(target):
            return
        self.canvas.commit_label()
        state = self.canvas.state
        action = target.getAttribute("data-diagram-action")
        before = state.graph
        if action == "add":
            rect = self.canvas.svg.getBoundingClientRect()
            id = crypto.randomUUID()
            node = Node(id=id, label="New step", x=state.viewport.world_x(rect.width / 2.0),
                        y=state.viewport.world_y(rect.height / 2.0))
            state.commit(Diagram(nodes=[*state.graph.nodes, node], edges=state.graph.edges,
                                 ports=state.graph.ports))
            state.select_node(id)
        elif action == "connect":
            if len(state.selected_nodes) != 2:
                self.status.textContent = "Select two nodes first."
                return
            edge = Edge(id=crypto.randomUUID(), source=state.selected_nodes[0],
                        target=state.selected_nodes[1], routing="orthogonal")
            state.commit(Diagram(nodes=state.graph.nodes, edges=[*state.graph.edges, edge],
                                 ports=state.graph.ports))
        elif action == "delete":
            state.delete_selected()
        elif action == "undo":
            state.undo()
        elif action == "redo":
            state.redo()
        elif action == "layout":
            try:
                state.commit(tree_layout(state.graph))
            except ValueError:
                self.status.textContent = "Tree layout needs directed connections, no cycles and at most one parent per step."
                return
        if action == "layout" or action == "fit":
            rect = self.canvas.svg.getBoundingClientRect()
            state.viewport.fit(state.graph, rect.width, rect.height)
        if state.graph is before:
            self.canvas.draw()
        else:
            self.canvas.changed()
