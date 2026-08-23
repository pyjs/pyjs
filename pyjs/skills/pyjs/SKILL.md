---
name: pyjs
description: Build, modify, run, and test PyJS projects, custom elements, UI components, and browser applications written in Python and compiled to JavaScript.
---

# PyJS

Use the installed examples as the source of truth for this version of PyJS.

## Workflow

1. Run `pyjs template` to list the templates registered by installed packages.
2. Run `pyjs template NAME` and inspect the closest application or component example. Add `--src`
   to compare it with the transpiled entry-module JavaScript.
3. Prefer adapting a working example over inventing framework APIs.
4. Create a project with `pyjs create APP [DESTINATION]`, optionally adding `--src-layout` or
   `--template NAME`.
5. Add `--single-file` and use a file template when the application should be one Python file.
6. Probe language support with `pyjs -c CODE`; add `-v` to inspect generated JavaScript and get a
   compiler traceback if the probe fails.
7. Run the Python and relevant platform test targets before considering the work complete.

Install the official examples with `python -m pip install "pyjs[examples]"` if no
`pyjs_examples.*` templates are listed.

```bash
pyjs create my_app
pyjs create my_app .
pyjs create my_app --src-layout
python -m my_app
pyjs create calculator_demo --template pyjs_examples.calculator
pyjs create counter --single-file --template pyjs_examples.counter
```

For a small, Node-compatible language experiment, avoid creating a temporary file:

```bash
pyjs -c 'print(1 + 2)'
pyjs -v -c 'value = 3 * 3; print(value)'
pyjs --src -c 'print("JavaScript source only")'
pyjs --src -c 'from pyjs.web.events import Event; print(Event("ready").type)'
pyjs --src-all app.py
pyjs --perf -c 'print(sum(range(10)))'
```

`pyjs FILE.py`, `pyjs -m MODULE`, and `pyjs -c CODE` run generated JavaScript with the managed Node
runtime. Imports and decorated declarations in a command string are analyzed at module scope, while
the executable statements become its entry point. `--src` prints only the entry module; use
`--src-all` when dependency implementations are also relevant. Use `--json` for structured results
and compilation errors. Browser-only APIs still require a browser test or a served application.

## Documentation

Run `pyjs --version`, then use the resources shipped with that installed
version first:

- Installed framework guidance: `pyjs skill`
- Installed examples: `pyjs template` and `pyjs template NAME`
- Public source and README: `https://github.com/pyjs/pyjs/`
- Supported subset:
  `https://github.com/pyjs/pyjs/#current-limitations-and-missing-features`

The public branch may be newer than an installed release. Inspect the installed
`pyjs` package and the source and tests exposed by installed templates when the
README does not cover an advanced case.

## Application model

- PyJS statically analyzes typed Python and emits JavaScript without a Python runtime.
- `CustomElement` classes are browser-native custom elements that can also render on the server.
- Use `@js` for code that must be available in the browser.
- Mark module values needed by compiled code as `JS`; non-empty static values
  infer their types. Use `JS[T]` when an empty collection needs an explicit
  type and `Final[JS]` for immutable bindings.
  Unmarked module values remain server-only.
- Treat the custom element and its DOM as application state when that state must survive server
  rendering and hydration.
- Use `state()` and `@effect(...)` for reactive values when they make imperative DOM updates clearer.
- Run an installed project or example through its normal Python entry point with
  `python -m PACKAGE`. Use `pyjs serve` in a configured project or `pyjs serve app.py` as a
  convenient alternative, particularly when PyJS was installed through npm.
- Do not edit generated `.main.js`, `.main.css`, or `.main.html` files.

## Web UI

- Start with components from `pyjs.web.ui` for ordinary application controls
  and layouts instead of hand-crafting equivalent HTML and CSS.
- Run `pyjs template pyjs_examples.components` to browse current component
  composition patterns. Components are imported from focused modules such as
  `pyjs.web.ui.button`, not re-exported from the package root.
- Compose large DOM trees from small, ordinary `@js` rendering functions.
  Constructors should read as an outline with roughly one call per major
  widget or panel, rather than containing deeply nested inline `tag(...)`
  definitions. Keep each retained `self` reference next to its event binding.
- Inspect the installed components and their examples for the current APIs and
  composition patterns before using them.
- Hand-craft a control only when no suitable component exists or the design
  intentionally requires custom behavior.

## Django applications

- Use `PyJSApplication`, `ApplicationSection`, and `ApplicationPage` from
  `pyjs.server.django` for an explicitly mounted navigation hierarchy. Sections
  may recursively contain sections and pages.
- Export a feature as one root `ApplicationSection`; it can be the root of a
  standalone `PyJSApplication` or one mounted subtree in a larger host.
- Call the registered page and pass its rendered result to
  `application.response()`. It applies the enclosing layouts and selects the
  same leaf ES module for direct loads and progressive navigation.
- Pass authenticated display values or other request-scoped shell state through
  `shell_args`; progressive fragments preserve the already-rendered shell.
- Let reachability decide which server rendering, hydration, and browser
  creation code is emitted. Do not add application-level static or hydration
  flags; server-only helpers still contribute HTML and Tailwind classes.
- Return `Page[T]` from paginated resource queries and use
  `queryset_page()` with `CursorPageRequest` for Django keyset pagination.
  Treat `next` and `previous` as opaque capabilities rather than parsing or
  constructing cursors in client code.
- Assign `pyjs.server.django.relationship()` to a typed `Relationship` when a
  Django include needs a renamed source, filtered queryset, per-parent limit,
  or one batched computed loader. Keep the selected resource type explicit so
  the generated client can access the included models.
- Keep resource operations asynchronous. Use Django's async ORM for ordinary
  work; isolate transactional ORM work in one synchronous
  `@transaction.atomic` helper and call it through `sync_to_async()` once.
- Resolve authentication with `await self.request.auser()` and permissions
  with `await user.ahas_perm()` inside async resource operations; Django's lazy
  `request.user` and synchronous permission methods may access the database.
- Use `dispatch(api.resource.operation, ...)` when server rendering needs the
  typed result of an operation. Use `dispatch_for_request(request, ...)` when
  its implementation also needs request-scoped authentication or context.
  Calling the resource method directly bypasses validation and deferred-result
  materialization.
- Synchronous Django views use `dispatch_sync()` and
  `dispatch_for_request_sync()` from `pyjs.server.django` rather than wrapping
  async dispatch at each call site.
- API and resource subclasses are server-only by default. Use an undecorated
  subclass for a separate Django implementation of a client-visible contract;
  mark the subclass `@js` only when it is itself part of the client API.
- Use `pyjs_examples.store` as the reference for section/page bundles, typed
  API branches, Django rendering, and progressive-navigation browser tests.
  Install its optional dependencies with
  `python -m pip install "pyjs-examples[store]"`, then run
  `python -m pyjs_examples.store`. Store retains its Django package layout and
  therefore is a runnable installed application rather than a copyable
  `pyjs template` entry.

## Tests

Small applications may keep tests in the application file:

```bash
python -m pytest -q app.py
python -m pytest -q app.py --pyjs-target=web
python -m pytest -q app.py --pyjs-target=web --pyjs-browser=managed
```

Pass the filename explicitly because pytest's default discovery only searches `test_*.py` files.
Browser tests that must be transpiled should be decorated with `@js`. Larger projects may keep
ordinary and browser tests in a `tests/` directory.

Use `--pyjs-browser=managed` for unattended browser verification. It launches headless Chrome and
automatically adds a screenshot and JSON diagnostics to failed tests. Add `--pyjs-headed` when a
visible browser is useful. Prefer the reusable `mount`, `bubbling_click`, `press_key`, and
`selector_count` helpers from `pyjs.testing.web` in browser-compiled tests. Use
`assert_render(element, "name")` from the same module for stored-image comparisons of ordinary DOM
elements; create or replace baselines with `--pyjs-update-renders` and review the resulting PNGs.
Pass `animation_time_ms=` to pause animations at a deterministic capture point, and use
`await wait_for_frames()` after DOM changes that only need layout and paint to settle.
Use `await wait_for_event(target, name, trigger)` to arm the listener before a synchronous action.

Projects may set recurring browser defaults under `[tool.pytest.ini_options]` using
`pyjs_browser`, `pyjs_headed`, `pyjs_browser_width`, `pyjs_browser_height`,
`pyjs_color_scheme`, `pyjs_artifacts_dir`, `pyjs_timeout`, and `pyjs_retained_iframes`.
Command-line options override project configuration.

Set `PYJS_CHROME_ARGS` only when the environment needs explicit Chrome flags.
For example, containers without sandbox support can opt into
`PYJS_CHROME_ARGS=--no-sandbox`; PyJS never adds that security tradeoff
automatically.

Managed browser failures retain their JavaScript stack and add mapped Python
file, line, and column locations. Start debugging from the Python locations;
keep the generated frames when reporting a suspected source-map problem.

For a NativeScript Android project, give interactive controls a stable `testID` and use
`AndroidTestSession` for UI-tree waits, taps, screenshots, and app-scoped logcat. Android tests are
explicit because they install and drive a real emulator:

```bash
python -m pytest -q tests --pyjs-target=android --pyjs-android-avd=NAME
```

Mark them with `pytest.mark.pyjs_android` and wrap assertions in
`session.artifacts_on_failure(pyjs_artifacts_dir / "android", NAME)`. Inspect both the PNG and XML
artifacts: the screenshot reveals visual regressions, while the hierarchy gives exact text,
test IDs, control classes, state, and bounds. The JSON manifest points to those files and the
app-scoped logcat. See the installed `pyjs_examples.calculator` tests for the
complete build, launch, interaction, and capture pattern.

Inspect the relevant template for current testing patterns. Normal application tree shaking omits
unreferenced test functions from the browser bundle.

## Verification

For a generated project, start with:

```bash
python -m pytest -q
python -m pytest -q --pyjs-target=web --pyjs-browser=managed
python -m PACKAGE
```

Replace `PACKAGE` with the generated package name. Use the run command from a
template's README when it differs.

## Visual inspection

After starting a web application, use `pyjs inspect` to create both a screenshot and a JSON
description of the rendered page. Inspect both artifacts: the image catches layout problems, while
the JSON exposes visible text, interactive elements, geometry, console output, and browser errors.

```bash
pyjs inspect http://127.0.0.1:8000
pyjs inspect http://127.0.0.1:8000 --color-scheme dark --width 390 --height 844
pyjs inspect http://127.0.0.1:8000 --wait-for '[data-testid="results"]'
pyjs inspect http://127.0.0.1:8000 --selector dialog-window
```

The default capture waits for fonts, images, finite animations, and two animation frames. Use a
timed sequence when debugging a transition or animation:

```bash
pyjs inspect http://127.0.0.1:8000 --no-settle --interval 0.1 --duration 1
```

Artifacts default to `screenshots/pyjs-inspect.png` and `screenshots/pyjs-inspect.json`. Use
`--output` to give a task-specific filename and `--json` when another tool will consume the paths.
For multi-page interaction or project-specific assertions, use `pyjs.tooling.browser` directly;
the repository's `scripts/capture_*_screenshot.py` scenarios and
`examples/chat/visual_test.py` are working examples.
Prefer `wait_for_selector`, `wait_for_attribute`, `wait_for_text`, `wait_for_count`, `click`,
`fill`, `submit`, `attribute`, `attributes`, `text`, and `texts` over embedding JavaScript for
ordinary DOM interaction.
