# Kanban Board Example

This example implements a polished board with native HTML drag-and-drop. Cards can move between
columns, reorder at the pointer midpoint, or use visible arrow controls for the same behavior. The
DOM is the source of truth for card order and column counts.

## Run the board

From the repository root:

```bash
.venv/bin/python -m pyjs_examples.kanban
```

Open the clickable URL printed by the server.

## Run the tests

The focused browser suite dispatches the complete drag event lifecycle and covers midpoint
placement, invalid drops, count updates, accessibility controls, and the stored visual baseline:

```bash
.venv/bin/python -m pytest -q examples/kanban/tests --pyjs-target=web --pyjs-browser=managed
```

The end-to-end harness drives a real mouse through Chrome and writes its screenshot and structured
state to the current directory's `screenshots/` folder:

```bash
.venv/bin/python examples/kanban/visual_test.py
```
