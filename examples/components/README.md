# Components

Components is the executable reference for `pyjs.web.ui`. It combines the
individual component catalog with composed application blocks and uses PyJS
partial navigation to keep its outer shell mounted between pages.

It demonstrates:

- the complete reusable component collection;
- accessible component states and interaction;
- a cohesive project workspace assembled from those components;
- server rendering of each page;
- a persistent `NavigationLayout` and `PageOutlet`;
- partial page downloads, History API updates, and browser hydration; and
- focused Python and managed-browser tests.

The same application is intended to power the future `/components/` section
of the PyJS website. Documentation can add prose, Python source, generated
JavaScript, and tests around these executable demonstrations.

## Run Components

From the repository root:

```console
uv run python -m pyjs_examples.components
```

Open the printed URL. Move between **Catalog** and **Workspace block** to see
the persistent shell and partial navigation.

## Diagram editor

Open **Diagrams** (`/diagrams`) for a decision-tree editor. Click nodes to
toggle selection, drag to move selected nodes, and drag empty space to pan.
Scroll to zoom around the pointer. Double-click a node, or focus it and press
Enter, to edit its label. Enter saves; Escape cancels label editing or a drag.
The toolbar adds and connects nodes, deletes selections, arranges a directed
tree, fits the view, and provides undo/redo. Delete/Backspace removes selected
items; Ctrl/Cmd-Z undoes and Ctrl/Cmd-Shift-Z redoes. Changes are in memory
only.

`pyjs.ui.diagram` contains the graph models, hit testing, viewport and
`DiagramEditor`. Treat models as snapshots: construct a replacement and call
`commit()` instead of mutating a published graph. A drag records one history
entry; selection and pan do not. External `replace_graph()` cancels a preview
and clears history. Use `history_limit=0` for application-owned undo.

`pyjs.web.ui.diagram.DiagramCanvas` renders SVG and handles browser input.
Pass the initial graph to its constructor. Call `configure(graph)` to replace
its document. Programmatic edits use
`canvas.state.commit(graph)` followed by `canvas.changed()`, which redraws and
emits a bubbling `diagram-change` event. Read `canvas.state.graph` in the
listener. Use `draw()` after selection or viewport changes. `draw_diagram()`
is also available for applications that own their interaction controls.

```python
from pyjs.ui.diagram import Diagram, Edge, Node
from pyjs.web.ui.diagram import DiagramCanvas

canvas = DiagramCanvas(Diagram(nodes=[
    Node(id="start", label="Start", x=0.0, y=0.0),
    Node(id="finish", label="Finish", x=240.0, y=0.0),
], edges=[Edge(id="next", source="start", target="finish")]))
```

Nodes support rectangles and diamonds; edges support labels, named boundary
ports, straight lines and midpoint orthogonal routes. Cycles, self-loops and
parallel edges are valid, but `tree_layout()` deliberately accepts only
directed forests with at most one parent per node. Layout is explicit and
undoable, never applied when opening an existing graph.

This initial editor does not provide obstacle avoidance, automatic label
placement, interactive resizing, port dragging, marquee selection or touch
pinch zoom. A second pointer cancels the current drag. Parallel edges may
overlap. Applications own persistence, domain rules and richer controls.
Static documentation keeps its specialized DSL and renderer, sharing boundary
and arrowhead geometry through `pyjs.ui.diagram_geometry`.

### Read-only diagrams and custom nodes

Use `DiagramView` from `pyjs.web.ui.diagram_view` for a permanently read-only
diagram. Its generated bundle excludes editor commands, history, label fields
and mutation gestures. Nodes can still be activated with a click, Enter or
Space: listen for `diagram-node-activate`, whose event detail is the node ID.
Use `configure(graph)`, `get_graph()`, `fit()` and `draw()` to control the view.
For static server output, `diagram_svg(graph)` returns ordinary SVG/HTML,
without a custom element, focusable actions, event handlers or JavaScript.
The documentation fence renderer already has this script-free behavior.

Open `/diagram-view` for a read-only example with `ReviewCard`, a normal
`Widget` subclass containing a title, details, link and input. Its host view
subclasses `DiagramView` and overrides this hook:

```python
def render_node(self, node: Node, previous: Element | None) -> Element:
    if isinstance(previous, ReviewCard):
        previous.update_node(node)
        return previous
    return ReviewCard(node)
```

The same hook is available on `DiagramCanvas`. A renderer may return any HTML
element, including ordinary `Widget`/`CustomElement` subclasses. It receives
the existing content on redraw; update and return it to preserve input values,
focus and component state. Returning a different element replaces that node's
content. Constructors and updates should follow ordinary PyJS hydration rules.

Passing a graph to the base constructor renders it immediately. When your
hook uses subclass fields, initialize an empty view first, set those fields,
then call `configure(graph)`, as `ReviewDiagram` does. This also prepares the
custom content for server rendering before the component is mounted.

Reordering uses atomic DOM moves where supported. `CustomElement.moved()`
handles those moves without running disconnect/reconnect cleanup. In older
browsers, reconciliation keeps the focused node attached and moves siblings
around it; other moved nodes still receive normal reconnect callbacks.

Set `Node.width` and `Node.height` explicitly: they define the SVG content box,
hit bounds and edge attachments. No DOM measurement or automatic resizing is
performed. Default labels wrap to that box without character-count truncation.
Custom content uses HTML inside SVG `foreignObject`; the portable data model
remains independent of browser components. Native links and form controls keep
their input behavior rather than initiating diagram actions; use
`data-diagram-interactive` on another custom interaction area to opt out too.

## Run the tests

```console
uv run pytest -q examples/components/tests
uv run pytest -q examples/components/tests --pyjs-target=web \
  --pyjs-browser=managed
```
