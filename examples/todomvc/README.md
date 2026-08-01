# pyjs TodoMVC

This project ports the canonical [TodoMVC](https://todomvc.com/) application to idiomatic
Python compiled for the browser by pyjs.

It demonstrates:

- custom elements used directly as the application framework
- typed todo identifiers, titles, completion, and edit state stored on DOM attributes
- focused `@effect` methods that synchronize state with each item's controls
- creation, editing, deletion, completion, toggle-all, and clear-completed behavior
- the `#/`, `#/active`, and `#/completed` routes
- browser persistence using the `todos-pyjs` localStorage key
- server rendering followed by custom-element hydration
- deterministic Python tests and real browser interaction tests

The markup exposes the standard TodoMVC class selectors, and the behavior follows the current
official application specification. This keeps the example close to being suitable for an eventual
TodoMVC submission once pyjs has a generally available build command.

`base.css` and `index.css` are unmodified copies of `todomvc-common` 1.0.5 and
`todomvc-app-css` 2.4.2, matching the shared styles used by the official examples.

## Run the app

From the repository root:

```bash
.venv/bin/python -m pyjs_examples.todomvc
```

Open `http://127.0.0.1:8000/`. Todos persist in localStorage across refreshes. Clear the
`todos-pyjs` key in the browser to reset the application completely.

## Run the tests

Run the deterministic Python tests:

```bash
.venv/bin/python -m pytest -q examples/todomvc/tests
```

Run the complete suite in the browser:

```bash
.venv/bin/python -m pytest -q examples/todomvc/tests --pyjs-target=web
```

The browser suite covers the canonical interaction paths, persistence, route restoration, and the
main visual state used for screenshot review.
