---
name: pyjs
description: >-
  Build, modify, run, and test PyJS projects, custom elements, UI components,
  and web/Android applications compiled from Python to JavaScript or JVM code.
---

# PyJS

Use the installed examples as the source of truth for this version of PyJS.

## Workflow

1. Run `pyjs template` to list the templates registered by installed packages.
2. Run `pyjs template NAME` and inspect the closest application or component
   example. Add `--src` to compare it with the transpiled entry-module
   JavaScript.
3. Prefer adapting a working example over inventing framework APIs.
4. Create a project with `pyjs create APP [DESTINATION]`, optionally adding
   `--src-layout` or `--template NAME`.
5. Add `--single-file` and use a file template when the application should be
   one Python file.
6. Probe language support with `pyjs -c CODE`; add `-v` to inspect generated
   JavaScript and get a compiler traceback if the probe fails.
7. Run the Python and relevant platform test targets before considering the
   work complete.

Install the official examples with
`python -m pip install "pyjs[examples]"` if no `pyjs_examples.*` templates are
listed.

```bash
pyjs create my_app
pyjs create my_app .
pyjs create my_app --src-layout
python -m my_app
pyjs create calculator_demo --template pyjs_examples.calculator
pyjs create counter --single-file --template pyjs_examples.counter
```

For a small, Node-compatible language experiment, avoid creating a temporary
file:

```bash
pyjs -c 'print(1 + 2)'
pyjs -v -c 'value = 3 * 3; print(value)'
pyjs --src -c 'print("JavaScript source only")'
pyjs --src -c 'from pyjs.web.events import Event; print(Event("ready").type)'
pyjs --src-all app.py
pyjs --perf -c 'print(sum(range(10)))'
```

`pyjs FILE.py`, `pyjs -m MODULE`, and `pyjs -c CODE` run generated JavaScript
with the managed Node runtime. Imports and decorated declarations in a command
string are analyzed at module scope, while the executable statements become
its entry point. `--src` prints only the entry module; use `--src-all` when
dependency implementations are also relevant. Use `--json` for structured
results and compilation errors. Browser-only APIs still require a browser test
or a served application.

For the experimental native target, install a host Clang/linker toolchain and
use `pyjs --target native app.py` or `pyjs build --target native app.py -o app`.
No decorator is required: reachable typed Python is compiled. Prefer a
zero-argument `main() -> None` and an `if __name__ == "__main__": main()` guard
so the file also runs under CPython without executing the entry during analysis.
`--src` prints LLVM IR. `--perf` checks matching output and successful exits
across repeated CPython/native processes, reporting compilation separately;
startup and captured output count for both targets. It does not benchmark
interactive input or pass program arguments. See the README for a complete
copy/paste example and current native limitations.

For a desktop UI, use `pyjs build my_app:main --target electron -o dist/my-app`
with a new output directory. This packages the hydrated page and Python source
maps with stock Electron; it needs no Python or HTTP server at runtime.
`--electron-runtime PATH` reuses a host-platform distribution offline.
`--electron-host DIRECTORY` compiles an importable Python package's `main.py`
entry `async main(context)` and optional `preload.py` entry `main()` into
self-contained CommonJS bundles. Use typed `pyjs.node` and `pyjs.electron`
bindings; keep Node filesystem/process code out of sandboxed preloads. Legacy
JavaScript hosts with `main.cjs` exporting `async start(context)` remain supported.
For server-backed hosts, `pyjs.electron.session` provides partitioned sessions,
protocol handlers and Chromium fetch. Use the same partition in
`WebPreferences`; opt into `bypassCustomProtocolHandlers` only when forwarding
an intercepted request. `pyjs.electron.window` provides native menus and URL
guards. Its `create_window` leaves navigation policy to the caller, unlike
the blanket blocker in `context.createWindow`; install guards before loading
content. `allow_requests` replaces the session's previous request filter.
Navigation/request predicate exceptions cancel before propagating to the host's
error handler. Unset fetch options preserve the input Request's own modes.
Build-time compilation preserves Python source maps and needs no Python at launch.
`pyjs build my_service:main --target node -o dist/service.cjs` builds a standalone
Node program. Mark Python-authored Node tests with `pytest.mark.pyjs_node` and
`@js`, then run `pytest --pyjs-target=node`. Compiled Node tests are zero-argument
module-level functions; pytest fixtures and parametrized arguments are not
transported, but host-side autouse fixtures can prepare resources.
Keep UI state and DOM work in the renderer and make service IPC coarse-grained.
Existing HTTP backends are not translated automatically. The default renderer
has no Node globals, but its `file://` page can read accessible local files;
only package trusted UI. OS sandbox setup, signing and installers are separate
deployment steps. See the README's stock Electron section.

## Documentation

Run `pyjs --version`, then use the resources shipped with that installed
version first:

- Installed framework guidance: `pyjs skill`
- Installed examples: `pyjs template` and `pyjs template NAME`
- Public source and README: `https://github.com/pyjs/pyjs/`

Until versioned documentation is published, use the installed package,
guidance, and templates when compatibility matters. Tagged public source is
available for every released version.

## Application model

- PyJS statically analyzes typed Python and emits JavaScript without a Python
  runtime.
- `CustomElement` classes are browser-native custom elements that can also
  render on the server.
- Use `@js` for code that must be available in the browser.
- Mark module values needed by compiled code as `JS`; non-empty static values
  infer their types. Use `JS[T]` when an empty collection needs an explicit
  type and `Final[JS]` for immutable bindings.
  Unmarked module values remain server-only.
- Treat the custom element and its DOM as application state when that state
  must survive server rendering and hydration.
- Use `state()` and `@effect(...)` for reactive values when they make
  imperative DOM updates clearer.
- Run an installed project or example through its normal Python entry point
  with `python -m PACKAGE`. Use `pyjs serve` in a configured project or
  `pyjs serve app.py` as a convenient alternative, particularly when PyJS was
  installed through npm.
- Use fixed-width root types such as `int8`, `uint32`, and `int64` when values
  must wrap consistently across backends. Use plain `int` for Python integer
  semantics. Convert explicitly between different fixed widths. Use
  `StaticArray[T, N]` when array length is part of a portable layout. Shader
  code instead uses the distinct scalar and array types in `pyjs.shader`;
  plain literals are contextual, but `int` and `float` annotations are not
  shader types.
  Import `Decimal` from `pyjs.stdlib` for exact finite decimal arithmetic.
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
- For node-and-edge diagrams, use `DiagramCanvas` from `pyjs.web.ui.diagram`
  with snapshot models and `DiagramEditor` from `pyjs.ui.diagram`. Configure a
  graph, then read committed content on `diagram-change`. Programmatic edits
  call `state.commit(graph)` followed by `changed()`; selection and viewport
  changes only need `draw()`. Do not mutate published snapshots. Use
  `tree_layout()` from `pyjs.ui.diagram_layout` explicitly for directed forests;
  it rejects cycles and multiple parents. See Components' `/diagrams` example
  for toolbars, history, controls and current routing limitations.
- Use `DiagramView` from `pyjs.web.ui.diagram_view` for read-only diagrams
  without editor code in their bundles, or `diagram_svg()` for script-free
  server rendering. Subclass the view or editor and override
  `render_node(node, previous)` for HTML node content; ordinary `Widget`
  subclasses work here. Reuse previous content to preserve input state.
  The base constructor renders a supplied graph immediately. If your hook
  needs subclass fields, initialize without a graph, set the fields, then
  call `configure(graph)`; this also works for server-rendered content.
  Set geometry through `Node.width`/`height`; do not rely on DOM measurement.
  The Components `/diagram-view` example demonstrates this extension.
- For atomic IndexedDB writes, import `transaction_result` and `request_result`
  from `pyjs.web.indexeddb`. Call `transaction_result(transaction, operation)`
  immediately after creating the transaction. The async operation may await
  its IndexedDB requests, but not timers or network I/O. It resolves only after
  commit and aborts on operation failure; request success alone is not a
  durable-save acknowledgement.

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
- Use a synchronous `@stream` operation returning `Stream[T]` for ordered
  event data such as logs. Pair a durable `StreamHistory` adapter with the
  short live tail through `StreamFeed`; its snapshot query returns
  `StreamSnapshot[T]`,
  call `resume_after(snapshot.sequence)`, and replace the snapshot after a
  resync. Streams are at-least-once, so suppress overlap with stable event
  identities. `StreamHub` is process-local; multi-process deployments can
  inject chosen synchronous and asynchronous clients into
  `ValkeyStreamBackend` without adding a Valkey client dependency to PyJS.
- Use `StreamingLog` from `pyjs.web.ui.streaming_log` for bounded plain-text
  output with pause and follow-tail behavior. Use `StreamingList` for
  structured activity rows.
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
```

Pass the filename explicitly because pytest's default discovery only searches
`test_*.py` files. Browser tests that must be transpiled should be decorated
with `@js`. Larger projects may keep ordinary and browser tests in a `tests/`
directory.

Browser tests default to isolated headless Chrome. Install it with
`sdkmgr browser install`, or set `CHROME_BIN` to an existing Chrome or Chromium
executable. Use `--pyjs-headed` to inspect the isolated window. Only use
`--pyjs-browser=system` when the user explicitly requests their normal browser;
close the test tabs you open. Keep unattended tests in managed mode.

Managed-browser failures automatically include a screenshot and JSON
diagnostics. Prefer the reusable `mount`, `bubbling_click`, `press_key`, and
`selector_count` helpers from `pyjs.testing.web` in browser-compiled tests. Use
`assert_render(element, "name")` from the same module for stored-image
comparisons of ordinary DOM elements; create or replace baselines with
`--pyjs-update-renders` and review the resulting PNGs. Pass
`animation_time_ms=` to pause animations at a deterministic capture point, and
use `await wait_for_frames()` after DOM changes that only need layout and paint
to settle. Use `await wait_for_event(target, name, trigger)` to arm the listener
before a synchronous action.

Projects may set recurring browser defaults under `[tool.pytest.ini_options]`
using
`pyjs_browser`, `pyjs_headed`, `pyjs_browser_width`, `pyjs_browser_height`,
`pyjs_color_scheme`, `pyjs_artifacts_dir`, `pyjs_timeout`, and
`pyjs_retained_iframes`. Command-line options override project configuration.

Run `pyjs npm sync [MODULE[:ENTRY]]` when a reachable PyJS compatibility
module wraps an npm package. PyJS owns `.pyjs/npm`, pins exact versions, and
does not require a project-authored `package.json`.

Set `PYJS_CHROME_ARGS` only when the environment needs explicit Chrome flags.
For example, containers without sandbox support can opt into
`PYJS_CHROME_ARGS=--no-sandbox`; PyJS never adds that security tradeoff
automatically.

Managed browser failures retain their JavaScript stack and add mapped Python
file, line, and column locations. Start debugging from the Python locations;
keep the generated frames when reporting a suspected source-map problem.

Android examples use native JVM APIs. Run Calculator or Notes with
`python -m pyjs_examples.calculator --android` or
`python -m pyjs_examples.notes --android`. The builder requires the Android SDK
and a JDK. Host-driven ADB tests use `pytest.mark.pyjs_android` and
`AndroidTestSession` with an explicit activity; preserve failure artifacts
with `session.artifacts_on_failure(...)`.
`wait_for_element(description="Note text", focused=True)` waits for an
accessibility label and focus together, retrying transient UI-tree failures.
Selectors are exact and combined; `focused=None` leaves focus unrestricted.
For launcher or system flows that can precede the target process, explicitly
pass `require_running=False`. Ordinary waits retain early app-exit reporting.

Native text controls expose `setHorizontallyScrolling()` without modifying
their contents.
`getLayout()` returns `TextLayout` or `None`, including between a wrapping
change and the next layout pass. Its `getWidth()` and `increaseWidthTo()` use
pixel widths. Shrinking raises Java's plain `RuntimeException`, caught by
`except Exception`, not Python's `RuntimeError` or `ValueError`, nor Java's
`IllegalArgumentException`. `Editable.replace(start, end, text)` uses UTF-16
offsets and returns the same mutable buffer; it is different from replacing
the field with `setText()`.

For Android images, read a selected document with
`context.get_content_resolver().open_input_stream(uri)` and close the stream
in `finally`. It may return `None` or raise a native I/O or permission error.
Bound the bytes before accumulating them; `ByteArrayOutputStream.toByteArray()`
returns a copy, so account for that extra allocation. Use `BitmapOptions` and
`decode_bitmap` from `pyjs.android.graphics`: first set `inJustDecodeBounds`
to inspect `outWidth`, `outHeight`, and `outMimeType` without allocating pixels.
That call returns `None`, as does invalid data. Then disable bounds-only mode
and choose `inSampleSize` for a smaller preview. Input limits, pixel limits,
background decoding, and bitmap lifetime remain application responsibilities.
Use `ImageView.set_image_bitmap()` to display the result and
`set_image_drawable(None)` to detach it before recycling an unshared bitmap.
Passing `None` to `set_image_bitmap()` may retain an empty native drawable.
For binary exports, `OutputStream.write(buffer, offset, length)` writes native
byte-array ranges without text conversion. It dispatches to the concrete
stream, including document-provider streams. Close owned outputs in `finally`;
range/I/O failures propagate and can leave partial output. A successful write
is not an atomic publication or a disk-synchronization guarantee.

Resolve Android resources for configurable application package names with
`context.get_resources().get_identifier(name, kind, package)`. Missing names
return zero; check before constructing views. Prefer generated `R` bindings
when the package is fixed. `RemoteViews.apply(context, parent)` inflates the
widget layout and applies its actions for a local preview; `parent` may be
`None`. Publishing to a launcher still uses `AppWidgetManager`.

For direct-JVM Android UI tests, mark module-level functions with
`pytest.mark.pyjs_android_jvm` and use `pyjs.android.testing`. Run the fast
AndroidJUnit4, Robolectric, and Espresso tier with
`--pyjs-android-runtime=robolectric`. Run the same test in a managed emulator
with `--pyjs-android-runtime=device --pyjs-android-avd=NAME`; add
`--pyjs-android-headless` for a deterministic cold boot without a window.
Keep compiled tests self-contained and zero-argument; pytest fixtures,
parametrization, and per-item setup or skip behavior are not yet transported.
Use `launch_intent(intent)` for share/deep-link startup tests. Build an explicit
intent with `Intent().set_class(application_context(), YourActivity)` and add
the action, MIME type and extras before launching. Activities receive later
deliveries through `on_new_intent()`; call the superclass and `set_intent()`
when future reads and configuration changes should use the new intent.
This does not change Android's launch record; process death may restore the
original launch intent. Persist capture identities and contents separately
and make processing idempotent. Read shared text with
`get_char_sequence_extra()` and `to_string()` to accept styled text too.
Use `finish()` to close a completed capture Activity; `is_finishing()` reports
whether finishing was requested, not whether content was saved. Wait for a
durable save acknowledgement before closing a form that promises persistence.
Keep application Activities in modules imported by the selected test module so
the device packager can preserve Android's target/instrumentation APK boundary.
Add `pytest.mark.pyjs_android_dependencies("androidx")` when the target uses
PyJS's pinned AndroidX runtime. The dependency is resolved for both Robolectric
and device
tests. Register project-specific checksum locks as `NAME=PATH` entries in
`pyjs_android_dependency_sets`, then select them with the same marker.
Use `pyjs.android.uiautomator` with the additional
`pytest.mark.pyjs_android_device` marker only for system UI and cross-app
interactions; Robolectric excludes device-only tests.

Inspect the relevant template for current testing patterns. Normal application
tree shaking omits unreferenced test functions from the browser bundle.

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

After starting a web application, use `pyjs inspect` to create both a screenshot
and a JSON description of the rendered page. Inspect both artifacts: the image
catches layout problems, while the JSON exposes visible text, interactive
elements, geometry, console output, and browser errors.

```bash
pyjs inspect http://127.0.0.1:8000
pyjs inspect http://127.0.0.1:8000 --color-scheme dark --width 390 --height 844
pyjs inspect http://127.0.0.1:8000 --wait-for '[data-testid="results"]'
pyjs inspect http://127.0.0.1:8000 --selector dialog-window
```

The default capture waits for fonts, images, finite animations, and two
animation frames. Use a timed sequence when debugging a transition or
animation:

```bash
pyjs inspect http://127.0.0.1:8000 --no-settle --interval 0.1 --duration 1
```

Artifacts default to `screenshots/pyjs-inspect.png` and
`screenshots/pyjs-inspect.json`. Use `--output` to give a task-specific filename
and `--json` when another tool will consume the paths. For multi-page
interaction or project-specific assertions, use `pyjs.tooling.browser`
directly; the repository's `scripts/capture_*_screenshot.py` scenarios and
`examples/chat/visual_test.py` are working examples. Prefer
`wait_for_selector`, `wait_for_attribute`, `wait_for_text`, `wait_for_count`,
`click`, `fill`, `submit`, `attribute`, `attributes`, `text`, and `texts` over
embedding JavaScript for ordinary DOM interaction.
