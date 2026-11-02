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

## Run the tests

```console
uv run pytest -q examples/components/tests
uv run pytest -q examples/components/tests --pyjs-target=web \
  --pyjs-browser=managed
```
