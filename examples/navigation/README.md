# Navigation Workspace Example

This example demonstrates server-rendered pages inside a persistent application layout. Normal
requests return complete HTML documents. Navigation initiated inside the application requests only
the selected page, updates the `PageOutlet`, and preserves the sidebar and header without requiring
a client-side routing table.

Run it from the repository root:

```bash
.venv/bin/python -m pyjs_examples.navigation
```

Open `http://127.0.0.1:8000/`, then move between the eight pages using the sidebar.

Run its server and browser coverage with:

```bash
.venv/bin/python -m pytest -q examples/navigation/tests
```
