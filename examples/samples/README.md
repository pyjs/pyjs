# Focused samples

These small, runnable projects are the source of truth for focused PyJS
examples. They are intentionally separate from the scaffolding implementation:

- `state_counter/` demonstrates reactive state and effects.
- `ui_dialog/` demonstrates the accessible dialog component.

Each sample includes Python and browser tests. Documentation should excerpt
code from these files rather than maintain a second copy in Markdown. The
installed `pyjs-examples` distribution registers these sources and makes them
available to `pyjs create --template`.

Run all sample tests from the repository root:

```bash
.venv/bin/python -m pytest -q examples/samples
.venv/bin/python -m pytest -q examples/samples --pyjs-target=web
```
