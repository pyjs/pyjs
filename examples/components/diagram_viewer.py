from pyjs import js, state
from pyjs.ui.diagram import Diagram, Edge, Node
from pyjs.web.dom import Element
from pyjs.web.domx import a, input, ref, tag, tw
from pyjs.web.events import CustomEvent
from pyjs.web.ui import Widget
from pyjs.web.ui.diagram_view import DiagramView


@js
def review_flow() -> Diagram:
    return Diagram(nodes=[
        Node(id="draft", label="Draft release", x=0.0, y=0.0, width=250.0, height=180.0),
        Node(id="publish", label="Publish release", x=330.0, y=0.0, width=250.0, height=180.0),
    ], edges=[Edge(id="review", source="draft", target="publish", label="Review")])


@js
class ReviewCard(Widget):
    def __init__(self, node: Node, owner: str):
        super().__init__()
        self.add({"style": "box-sizing:border-box;display:block;width:100%;height:100%;"
                          "padding:16px;font:14px system-ui;color:#1e293b"},
                 tag("h2", tw("font-semibold"), {"data-node-title": ""}, node.label),
                 tag("p", tw("my-2 text-slate-600"), "Owner: " + owner),
                 a(tw("text-blue-700 underline"), {"href": "#diagram-details"}, "Open details"),
                 input(tw("mt-2 w-full rounded border px-2 py-1"),
                       {"aria-label": "Comment for " + node.id, "placeholder": "Local comment"}))

    def update_node(self, node: Node) -> None:
        title = self.children[0]
        if title.textContent != node.label:
            title.textContent = node.label


@js
class ReviewDiagram(DiagramView):
    owner = state("Editorial team")

    def __init__(self, graph: Diagram | None = None, owner: str = "Editorial team"):
        super().__init__()
        self.owner = owner
        if graph is not None:
            self.configure(graph)

    def render_node(self, node: Node, previous: Element | None) -> Element:
        if isinstance(previous, ReviewCard):
            previous.update_node(node)
            return previous
        return ReviewCard(node, self.owner)


@js
class DiagramViewerApp(Widget):
    def __init__(self):
        super().__init__()
        self.viewer = ref(ReviewDiagram(review_flow(), owner="Publishing team"))
        self.status = ref(tag("p", {"role": "status"},
                              "Activate a node with a click, Enter or Space."))
        self.add(tw("mx-auto block max-w-5xl space-y-4 p-6"),
                 tag("h1", tw("text-2xl font-semibold"), "Read-only custom nodes"),
                 tag("p", "The diagram cannot be edited. Its embedded links and inputs "
                     "remain ordinary HTML controls; comments are not saved."),
                 self.viewer, tag("section", {"id": "diagram-details"}, self.status))
        self.viewer.addEventListener("diagram-node-activate", self.activated)

    def activated(self, event: CustomEvent) -> None:
        if isinstance(event.detail, str):
            self.status.textContent = "Activated: " + event.detail
