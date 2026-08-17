# Django issue tracker

This conventional Django app uses models and relations for projects, issues,
users, labels, milestones, comments, and activity. Shared Pydantic models form
the typed client/server boundary. The app demonstrates SSR, generated client
API proxies, nested resources, Django request validation, filtering, mutations,
and model-driven forms.

From the repository root, run:

```console
uv run python -m pyjs_examples.issue_tracker
```

For an installed examples package, install its optional dependencies first:

```console
pip install "pyjs-examples[issue_tracker]"
```

Open the printed URL. Create an issue, filter the list, add a comment, and close
the issue. Every operation passes through the generated typed client and the
Django adapter. The standalone runner migrates a temporary SQLite database and
loads `fixtures/issue_tracker.json`, so each server process starts with the same
sample project and removes its database when it stops.

The application is divided by runtime responsibility:

- `core.py` contains Pydantic values shared by the server and client;
- `api.py` declares shared resources and supplies their ORM-backed server
  implementations;
- `ui.py` contains the transpiled and server-rendered interface; and
- `server.py` connects the interface and API to Django HTTP views.

The Django persistence models remain in `models.py`, as they would in an
ordinary Django application.

The standalone app is served through Django's ASGI interface. Open it in two
browser windows and create or update an issue in either one. A shared
`LiveSession` receives resource invalidations over SSE, batches the affected
typed operations into one registered subscription, and updates the other
window without a page refresh. Django evaluates the registered operations with
the current SSE request and includes replacement values in the event. Each
watched query retains its generated API operation and last submitted request,
so live updates do not read partially edited form or filter controls.
