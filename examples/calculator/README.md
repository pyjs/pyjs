# Calculator Example

This project is a small but complete calculator application and the primary
example for pyjs browser-target testing.

It demonstrates:

- calculator state and behavior owned by a custom element
- typed `state()` fields serialized to DOM attributes and rendered with `@effect`
- a centered responsive custom-element UI
- digit and decimal entry
- addition, subtraction, multiplication, and division
- sign, percent, clear, and divide-by-zero behavior
- asynchronous result persistence through an HTTP POST route
- per-browser in-memory sessions that restore the last result after refresh
- a Python-authored service worker with cache-first offline application loading
- browser tests that interact with the real DOM through button events

The example intentionally stays focused on calculator behavior. Reusable widget
coverage, including the dropdown menu and floating positioning, lives under
`tests/web/ui/`.

## Run the calculator

From the repository root:

```bash
.venv/bin/python -m pyjs_examples.calculator
```

Open `http://127.0.0.1:8000/`. Completing a calculation with `=` saves its
result to the server. Refreshing the page restores that result through the
browser's session cookie. Sessions are intentionally in memory, so restarting
the server clears them. The app also registers `/calculator-serviceworker.js`.
After its first controlled reload, the calculator can load and calculate while
the browser is offline.

## Run the tests

From the repository root, run the Python target:

```bash
.venv/bin/python -m pytest -q examples/calculator/tests
```

Run the same model tests plus the browser-only UI tests in the browser:

```bash
.venv/bin/python -m pytest -q examples/calculator/tests --pyjs-target=web
```

The pytest plugin starts or reconnects to the browser-test daemon on
`127.0.0.1:8765`. To keep the daemon alive while iterating:

```bash
.venv/bin/python -m pytest -q examples/calculator/tests --pyjs-target=web \
  --pyjs-daemon-idle-seconds=0
```
