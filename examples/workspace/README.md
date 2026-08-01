# Project Workspace Example

This example combines the structure of shadcn/ui's dashboard block with the interaction-rich
task example. It is a cohesive launch workspace rather than a component catalog: the sidebar,
metrics, chart, task table, forms, overlays, settings, notifications, and collaboration feed all
serve the same project-management workflow.

Its task count is a typed DOM-backed state field, with an effect keeping the visible count in sync.

## Run the workspace

From the repository root:

```bash
.venv/bin/python -m pyjs_examples.workspace
```

Open `http://127.0.0.1:8000/`.

## Run the tests

```bash
.venv/bin/python -m pytest -q examples/workspace/tests
.venv/bin/python -m pytest -q examples/workspace/tests --pyjs-target=web
```
