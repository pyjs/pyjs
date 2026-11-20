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
`deny_permissions` denies checks and requests. For selective access, install
both `Session.setPermissionCheckHandler` and `setPermissionRequestHandler`;
complete each request callback once. Check the permission and requesting
frame origin/URL, not just the containing window. A check may have no
WebContents or requesting URL. Passing `None` clears a handler and restores
Electron's defaults; it does not deny access. The request details declaration
currently covers common frame fields, not permission-specific extensions.
Navigation/request predicate exceptions cancel before propagating to the host's
error handler. Unset fetch options preserve the input Request's own modes.
For native main-process alerts, use `pyjs.electron.notifications`:
`is_supported()`, `NotificationOptions(title, body=...)` and
`create_notification(options)`. Create after app readiness, retain the object,
and register `on("show", callback)` and `on_failed(notification, callback)`
before `show()`. Ordinary callbacks receive an Electron Event; the failure
helper passes the error string and returns an owned unsubscriber. Keep the
original callback for ordinary `removeListener` cleanup. Handle missing
publication events: support and a returning `show()` do not prove delivery.
`await show_notification(notification, timeout_ms=5000)` dismisses the previous
alert, subscribes before showing, and resolves on native publication. Failure,
early close, timeout and synchronous errors reject with owned listeners removed.
Do not show the same object concurrently; close uncertain alerts after rejection.
The timer cannot preempt synchronous native calls. Electron 45 on Linux uses
blocking libnotify/D-Bus publication, which stalls the main event loop and IPC
if the daemon is slow. Publication can succeed after `timeout_ms` or fail at
the native timeout (observed around 25 seconds). This is not a hard deadline.
`close()` dismisses the owned alert. IDs/groups apply only on macOS/Windows;
Windows limits each to 64 UTF-16 units. Linux cannot guarantee replacement
across process restarts. Apps own consent, signing/OS setup, durable scheduling,
retry/account policy and click routing. Do not expose unrestricted notification
creation to a renderer. Electron 45 persistent service-worker notifications
are not implemented; these main-process APIs do not run after the app exits.
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

- Generated web and Django documents use
  `interactive-widget=resizes-content` in their viewport metadata. Supporting
  browsers resize layout with the software keyboard so viewport-sized widgets
  can keep actions visible. Custom document shells should include that policy;
  browsers that ignore it retain native keyboard behavior. Desktop viewport
  tests do not prove real IME behavior or iOS compatibility.
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
- Use `DialogContent(scrollable=True)` for forms or confirmation content that
  can exceed the viewport height. The surface scrolls with its actions and
  follows the dynamic viewport; centered dialogs retain a small outer margin.
  Native focus scrolls offscreen controls into view. The default remains
  overflow-visible for compositions that require unclipped popup children.
- Use `DialogPanel(label, *children)` for an editor with fixed action areas.
  Compose its public `header`, `body` and `footer` elements; children start in
  the body, which owns scrolling. The panel fills narrow viewports and is
  centered and fits its content up to a height limit on larger screens.
  Set `padded_controls=False` for toolbars with their own spacing.
  Use it with `Dialog`, or handle
  `DialogCloseRequest` and call `show_modal()`/`close()` after application
  save checks. It inserts no close button. A native modal escapes ancestor
  inertness: disable its `dialog_element` explicitly while replacing inputs.
  Standalone modal panels hide the page scrollbar without changing inline
  overflow styles. Opening with `show_modal()` retains an existing page
  gutter without adding one to short pages. The modal fills narrow viewports.
  The lock follows native modal state, including close/removal and
  nested panels; this requires CSS `:has()` support. Panel/backdrop gesture
  containment additionally depends on support for non-scrolling containers.
- Use `Textarea(auto_size=True)` from `pyjs.web.ui.textarea` for multiline
  fields that should fit their wrapped content. It fills its container's
  width and grows or shrinks from a touch-friendly row without input listeners.
  Do not set a fixed height. Browsers without CSS field sizing retain native
  scrolling and vertical resizing; callers still own Enter/submit semantics.
- Floating controls (dropdowns, popovers, tooltips and comboboxes) use native
  manual popovers. Inside a modal dialog they remain in its DOM subtree for
  focus and inertness, while the top layer escapes clipping. Closing or
  removing the dialog resets the controls. This requires the Popover API.
  Custom `FloatingPanel` owners can pass `on_dismiss` to `open()` to reset
  their own state/listeners when a containing dialog closes or is removed.
  Use `DropdownMenuItem.on_select()` for pointer and keyboard actions; keep
  server-rendered controls in `ref()` fields when binding their callbacks.
  Menu contents may change after initialization: append item elements to the
  content or remove them normally. Keyboard navigation follows the current
  order and activates the focused item, including in open submenus.
- Add `FilePasteController` from `pyjs.web.ui.file_paste` to an existing
  editor or composer. Connect it during client initialization/reconnection
  and disconnect it on removal. Listen on its host for `files-paste`, cast
  `event.detail` to `PastedFiles` from the same module, and accept with
  `event.preventDefault()` before awaiting storage or uploads. The snapshot
  exposes `files`, clipboard MIME `types`, `has_plain_text`, and `has_html`.
  Plain-text controls can decline `has_plain_text` offers to prefer native
  text. Rich editors that support native HTML paste may also decline
  `has_html`. HTML does not imply plain text: a copied image may carry HTML
  markup without any text a textarea can insert. Acceptance replaces native
  paste, including any text. The consumer owns validation and pending saves;
  accepting a paste does not mean its files were persisted. Components'
  Workspace task description demonstrates a preview-only consumer.
- Use `ImagePreview` and `ImagePreviewQueue` from `pyjs.web.ui.image_preview`
  for viewport-loaded image galleries. Configure alt text, contain/cover fit,
  aspect ratio and maximum thumbnail dimensions; bind an async Blob loader
  with `preview.load_with(loader, queue=gallery_queue)` during client
  initialization. Share the queue across cards to serialize reads/decoding.
  The widget owns loading, retry, stale-result rejection and URL cleanup.
  Leaving the viewport releases its URL; returning loads again. Original
  decoding still needs temporary memory, so consumers must validate input
  size and bound I/O timeouts. An active loader is not cancelled on exit;
  the shared queue waits for it to settle. Sources are unchanged; previews
  are still frames.
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
  Fields needed after hydration must use DOM-backed `state()` or be restored
  from serialized data before `super().initialize()`; plain constructor
  assignments are not automatically replayed.
  Set geometry through `Node.width`/`height`; do not rely on DOM measurement.
  The Components `/diagram-view` example demonstrates this extension.
- For atomic IndexedDB writes, import `transaction_result` and `request_result`
  from `pyjs.web.indexeddb`. Call `transaction_result(transaction, operation)`
  immediately after creating the transaction. The async operation may await
  its IndexedDB requests, but not timers or network I/O. It resolves only after
  commit and aborts on operation failure; request success alone is not a
  durable-save acknowledgement.
- For system sharing, import `ShareData` and `navigator` from
  `pyjs.web.sharing`. Check `hasattr(navigator, "share")`; availability depends
  on the browser, operating system, secure context and permissions policy.
  If present, `navigator.canShare(data)` checks the payload, not whether a
  later share will succeed. Call `await navigator.share(data)` directly from
  a user action, before unrelated asynchronous work consumes activation.
  Handle rejection, including cancellation, without modifying the source.
  A fulfilled promise does not prove that a recipient received the content.
  Offer an explicit alternative such as copying or downloading when sharing
  is unavailable; do not silently copy after cancellation. `ShareData` accepts
  `title`, `text`, `url` and `files`; omitted fields remain absent.

- `Notification.permission` and `Notification.maxActions` in
  `pyjs.web.serviceworker` are native class properties, as is
  `PushManager.supportedContentEncodings`. Capability reads do not request
  permission or post notifications. Keep permission requests in an explicit
  user action and handle denied permission without blocking ordinary app use.

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

`pyjs.android.controls.HorizontalScrollView` hosts one child, typically a
horizontal layout containing multiple actions. Give the viewport a bounded
width; keep essential actions outside it. `set_fill_viewport(True)` expands
short content to the viewport, while `scroll_to(x, y)` clamps to its bounds.
Use `getScrollX()` to inspect the horizontal pixel offset.

For software-keyboard visibility, use `get_insets_controller(window, view)`
and `ime()` from `pyjs.android.insets`, with the AndroidX runtime dependency.
An Activity exposes `get_window()`; its window exposes `get_decor_view()`.
Call `controller.hide(ime())` when finishing an editing task, before detaching
its views. To show the keyboard, focus the editor and call
`controller.show(ime())`. Do not hide it on every focus change. These requests
are asynchronous; they do not prove the keyboard changed visibility.
`root_window_insets(view)` returns `None` for detached views. Otherwise,
`insets.is_visible(ime())` reads the current snapshot. Older Android versions
use AndroidX's compatibility behavior, which can approximate IME visibility.
Robolectric checks bindings and lifecycle boundaries; test real keyboard
transitions on a device or emulator.

For styled text, use `SpannableString` or `SpannableStringBuilder` from
`pyjs.android.text`. `StyleSpan` takes `Typeface.BOLD`, `ITALIC`, or
`BOLD_ITALIC` from `pyjs.android.graphics`; `StrikethroughSpan()` and
`TypefaceSpan("monospace")` supply additional styles. Pass the styled object
directly to `TextView.setText()` rather than converting it to a string.
`set_span(span, start, end, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)` uses UTF-16
offsets. Reusing a span object moves its range; create separate objects for
separate ranges. Inclusive/exclusive flags govern inserted text at endpoints.
`get_spans(start, end, StyleSpan)` returns native objects matching that class;
use `isinstance(item, StyleSpan)` or `cast(StyleSpan, item)` before calling
style-specific methods. Class filters require declared native or emitted
classes, not Python builtins such as `str`.
`get_span_start`, `get_span_end` and `get_span_flags` inspect their ranges.
`remove_span` is harmless for an absent object. `SpannableString` has fixed
characters but mutable spans; the builder also supports `append` and
`replace`. Copies retain span objects with independent range tables.
`EditText.get_text()` exposes span operations on its native editable buffer.
These APIs do not parse Markdown or persist formatting; applications own
their document model and source-to-display mapping.
Ordinary Python helpers can use `CharSequence` annotations to pass through
strings and native text without discarding spans.
Native `isinstance` checks use Java's hierarchy: Java strings also implement
`JavaCharSequence`. Check `Spanned` to distinguish styled text; the host-side
Python text shim does not model Java string inheritance.

Native text controls expose `setHorizontallyScrolling()` without modifying
their contents.
Use `LengthFilter` from `pyjs.android.text` in a `JVMArray[InputFilter]` with
`TextView.setFilters()` to bound future input. `InputFilter` comes from
`pyjs.android`. Limits count UTF-16 units, not displayed characters. Installing
a filter does not shorten existing content; an empty array removes filters.
Set filters before initial text when the initial value must also be bounded.
On API 35+, `setUseBoundsForWidth()` and `getUseBoundsForWidth()` select
glyph bounds instead of character advances for layout. Guard calls with
`BuildVersion.SDK_INT >= 35`. Glyph bounds help avoid clipping overhanging
characters, but can make exceptionally long lines expensive to lay out.
For editable fields accepting large pastes, select the policy before their
initial layout: an old DynamicLayout can retain its policy while processing
text changes, even after TextView invalidates it. Advance-based layout trades
overhang-clipping protection for avoiding that bounds computation; neither
setting changes the text.
`getLayout()` returns `TextLayout` or `None`, including between a wrapping
change and the next layout pass. Its `getWidth()` and `increaseWidthTo()` use
pixel widths. Shrinking raises Java's plain `RuntimeException`, caught by
`except Exception`, not Python's `RuntimeError` or `ValueError`, nor Java's
`IllegalArgumentException`. `Editable.replace(start, end, text)` uses UTF-16
offsets and returns the same mutable buffer; it is different from replacing
the field with `setText()`.

For bounded text previews, combine `setMaxLines()` with
`setEllipsize(TruncateAt.END)`; `TruncateAt` comes from `pyjs.android`.
This changes layout without modifying `getText()`. Pass `None` to disable
ellipsizing. `TextLayout.getEllipsisStart(line)` and `getEllipsisCount(line)`
describe omitted UTF-16 units after layout; `getLayout()` may still be `None`
until the next layout pass.

RecyclerView adapters expose `on_view_attached_to_window(holder)`,
`on_view_detached_from_window(holder)`, and `on_view_recycled(holder)`.
Use these native callbacks to manage per-card resources. Detachment is not
permanent: a cached view can reattach without rebinding. Attachment also does
not guarantee viewport visibility. Cancel or invalidate pending work on
rebinding and release owned resources on detach/recycle; late asynchronous
results must still verify their binding before updating a reused holder.
Restore or schedule any detached resources when the holder reattaches;
rebinding is not guaranteed, and loading can still wait for viewport visibility.

For native HTTP session restoration, `pyjs.java.net.HttpCookie` exposes its
constructor and domain, path, security, HTTP-only, max-age, version, discard
and port-list attributes. `CookieStore.getCookies()` includes cookies whose
paths do not match the origin root. `CookieStore.add()` bypasses response
acceptance policy: restore only validated records for the intended origin.
Persist `getVersion()` and restore it with `setVersion()` as well. Constructed
cookies default to version 1; retaining that default for a version 0 response
cookie changes its outgoing header quoting and metadata.
Use a private CookieManager per account and verify server identity before
resuming authenticated work. Record absolute expiry when accepting cookies;
`getMaxAge()` does not count down, and reusing it after a restart extends the
local lifetime. Do not persist session-only or discard-marked cookies without
an explicit application policy. Android API 21+
`context.get_no_backup_files_dir()` is for state excluded from auto backup;
it does not encrypt data or make it portable. Keep native file I/O on workers.

For Android SQLite storage, `open_database` from `pyjs.android.sqlite` uses
Android's default corruption handler unless passed a custom third argument.
The default can delete corrupt databases and reopen empty ones. For data that
must remain available for recovery, subclass `DatabaseErrorHandler` with a
non-deleting `onCorruption(database)`. Returning normally retains native error
reporting but allows Android to retry an open. Raising
`SQLiteDatabaseCorruptException(message)` prevents that retry and replaces
the original diagnostic with the application's message.
`database.getPath()` identifies the affected database. Keep the callback
synchronous and small; do not reopen the failing database inside it. This
does not repair data or guarantee that every corruption is detected. Retain
independent backups and handle failed opens/queries in the application.

For actual view bounds, implement `OnLayoutChangeListener` from `pyjs.android`
and attach it with `view.addOnLayoutChangeListener(listener)`. Its
`onLayoutChange` receives the view and new/old left, top, right and bottom
coordinates in pixels relative to the parent. This is a layout notification,
not a completed-frame or visibility signal. Keep callbacks small; schedule
layout-affecting work after the current pass when required by the container.
Remove the same listener with `removeOnLayoutChangeListener` when its owner
stops observing. There is no host-side layout simulation for these bindings.

For native encrypted state, use `pyjs.java.crypto` with Android API 23+
parameters from `pyjs.android.keystore`. Create a key with
`provider_key_generator("AES", "AndroidKeyStore")`, then `init_parameters`
with a `KeyGenParameterSpecBuilder` configured for encrypt/decrypt, 256 bits,
GCM and NoPadding. The block modes and paddings are `JVMArray[str]` values.
Serialize alias creation; generating another key for an existing alias can
make earlier ciphertext unreadable. `key_store("AndroidKeyStore").load(None)`
opens the app's store; `getKey(alias, None)` returns a native key or `None`.
Keys are non-exportable; do not assume every device provides hardware backing.

Use a fresh `cipher("AES/GCM/NoPadding")` for each operation. Encryption uses
`init_key(Cipher.ENCRYPT_MODE, key)` and its generated `getIV()`; never reuse
a nonce for another encryption with that key. Decryption uses
`init_parameters(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, iv))`.
Pass identical account/origin context bytes to `updateAAD` before `doFinal`.
Both consume `JVMArray[int8]`; `doFinal` returns authenticated plaintext or
raises `AEADBadTagException` on a mismatched tag. Catch
`GeneralSecurityException` around the entire stored-data decryption path,
including initialization: malformed parameters and invalid keys can also make
stored data unreadable. Recover without returning unauthenticated plaintext.
These APIs have no CPython shim.
Applications own bounded, atomic ciphertext storage and backup exclusions.
Never replace a missing decryption key silently or treat device-bound
ciphertext as a portable backup. Keep key work off the Android main thread.

For staggered-grid drag reordering, subclass
`pyjs.android.reorder.StaggeredGridDragCallback` instead of
`ItemTouchCallback`. It uses Android's target selection and continuous edge
scrolling, prevents a repeated swap with the same holder during transient
relayout, and preserves the staggered viewport when the first card moves.
Keep the container bounds stable during active gestures; progress banners
must not change the pointer's coordinate origin or move its scrolling edge.
Swapping back requires reversing by Android's touch slop along an axis that
passed the preceding target's edge. Motion on an uncrossed axis does not
release the guard. Other targets remain immediately eligible. Implement
movement flags, `on_move`, and `on_swiped` normally; preserve `super()` calls
when overriding selection, target selection, or `on_moved` hooks.

For native date/time selection, import `DatePickerDialog`, `TimePickerDialog`,
`DateSetListener` and `TimeSetListener` from `pyjs.android.pickers`. Create
dialogs with an Activity context and call `show()` on the main thread.
Picker months are zero-based; `java.time` months are one-based. Use
`is_24_hour_format(context)` to follow the device's time-display preference.
The dialogs support API 21; the `TimePicker` hour/minute getters and setters
require API 23 or newer.
Only a selection callback commits a choice; Back/cancellation is separate
through `DialogCancelListener` from `pyjs.android.dialogs`. Retain drafts
outside dialogs and dismiss owned dialogs when their Activity is destroyed.
Notes demonstrates a two-step preview without scheduling notifications.

For labels, use `format_date_time(context, epoch_milliseconds, flags)` from
`pyjs.android.dates`. Combine `DateFormatFlags.SHOW_DATE`, `SHOW_YEAR`,
`SHOW_TIME` and optionally `ABBREV_MONTH`. Android uses the default locale and
time zone; omitting `HOUR_12`/`HOUR_24` respects the device clock preference.
Reformat after configuration changes rather than persisting the display text.
These native bindings do not parse input or change the stored instant.

`pyjs.java.time` exposes `local_date_time`, `system_zone` and zoned/instant
conversion on Android API 26+ and the JVM. `LocalDateTime.atZone()` follows
Java's policy: a nonexistent local time moves forward by the clock gap, and
an ambiguous time selects the earlier offset. Compare the resolved
`toLocalDateTime()` with the input when silently adjusting a time would be
incorrect. `withEarlierOffsetAtOverlap()` and `withLaterOffsetAtOverlap()`
expose both occurrences; persist epoch milliseconds when storing an instant.
Changing the device zone does not change that stored instant. These are native
bindings, not CPython implementations or a recurring-reminder scheduler.

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

For native binary files, `FileInputStream(File(path))` from `pyjs.java.io`
supports bounded `read(buffer)` and explicit `close()`. Missing or unreadable
files raise native `IOException`. Use `ZipOutputStream(stream)` and
`ZipEntry(name)` from `pyjs.java.zip` for streaming archives. Call
`putNextEntry`, write byte ranges, and `closeEntry` for each member; `finish`
writes the central directory without closing the underlying output.
Closing the ZIP stream normally closes its underlying stream. A failed close
can leave that stream open, including on JDK 21. Close the ZIP wrapper once in
an inner `finally` and the owned underlying stream in an outer `finally`;
retrying the failed ZIP close is not a reliable cleanup strategy.
`ZipInputStream(stream).getNextEntry()` returns a native entry or `None`;
`read(buffer)` returns -1 at that entry's end. It reads local headers rather
than validating the complete central directory. Applications own worker
execution, entry/decompressed-byte limits, safe extraction paths, and partial
output handling. The bindings neither extract files nor provide encryption.

For strict text input, wrap the owned stream in `InputStreamReader` from
`pyjs.java.io` with `charset_for_name("UTF-8").newDecoder()` from
`pyjs.java.charset`. Call `read(buffer, offset, length)` with a bounded
`JVMArray[uint16]`; -1 means EOF. Counts are UTF-16 code units, not Python
characters. `string_from_chars` from `pyjs.java` copies a character-array
range; join chunks before interpreting split surrogate pairs. Invalid or
truncated bytes raise `IOException`. Close the reader in `finally`; it closes
the underlying stream too. The caller still enforces total/record-size limits
before accumulating content and publishes imported data only after validation.

Use ordinary `for value in array` loops with native `JVMArray[T]` values.
The source expression is evaluated once; later element mutations are visible
when reached. Primitive widths and nested array layouts are preserved, so
loop values can be passed directly to matching native arguments. Native arrays
have fixed length. This does not provide a first-class Python iterator object.
Iterable membership without `__contains__`, `list(array)` and wrapped
iterators such as `enumerate(array)` remain unsupported on JVM. Specialized
helpers can consume arrays directly; for example, `set(array_of_strings)`
works. Use an explicit loop for unsupported consumers.

JVM strings support `str.zfill(width)` with an integer or boolean positional
width. Padding counts Unicode code points and follows a leading ASCII sign.
Widths beyond JVM string capacity raise `MemoryError` before allocation.

JVM value-returning `and` and `or` support matching integer or floating
operands, preserving the selected value and skipping unused expressions.
Mixed integer/floating result unions remain unsupported.

JVM `min()` and `max()` accept two or more positional operands with matching
integer or floating storage. Floating ties and unordered NaN comparisons
retain the earlier operand. Iterable and `key` forms remain unsupported.

JVM callbacks support emitted module functions and non-capturing lambdas with
fixed positional `Callable[[...], ...]` signatures. They can be passed, stored
and returned; callback exceptions propagate through ordinary Python handlers.
Defaults, bound methods, captures, represented numeric signatures and adaptation
between different runtime signatures remain unsupported. Inline-only builtins
cannot be passed as values unless they have a backend value implementation.

JVM `sorted()` accepts a list, string, set or dictionary key collection, with
optional `key` callbacks and `reverse`. It is stable in either direction,
materializes the source before calling keys, and evaluates each key once in
input order. Sorting does not mutate the input, though callbacks can. Fixed-width
item representations, arbitrary iterators and union containers are unsupported.

JVM lists support `==`, `!=`, `__eq__()` and `__ne__()` between lists with
matching integer, boolean or string storage, including nullable strings.
They compare item values and logical length, not backing capacity or identity.
Floating, nested, erased-object and mismatched-storage list comparisons remain
unsupported and receive compilation diagnostics.

Resolve Android resources for configurable application package names with
`context.get_resources().get_identifier(name, kind, package)`. Missing names
return zero; check before constructing views. Prefer generated `R` bindings
when the package is fixed. `RemoteViews.apply(context, parent)` inflates the
widget layout and applies its actions for a local preview; `parent` may be
`None`. Publishing to a launcher still uses `AppWidgetManager`.

`Context.start_activity(intent)` exposes the framework's `startActivity()`.
Application and service contexts require `Intent.FLAG_ACTIVITY_NEW_TASK`.
It does not bypass Android's background activity launch restrictions; use an
appropriate user-initiated flow, such as a launcher-delivered PendingIntent.
The foreground Context example tests dispatch and extras, not permission to
launch from an arbitrary background process.

For short background work started by a `BroadcastReceiver`, call `go_async()`
inside `on_receive()` and transfer the returned `BroadcastPendingResult` to
the worker. It may be `None` outside a delivery or after detaching it already.
Call `finish()` exactly once in `finally`, including when the work fails; if
starting the worker fails, finish it on the receiving thread. This retains the
delivery, not an unlimited execution window: keep work well below ten seconds
and schedule longer work separately. A bare thread is not protected after the
receiver returns. Keep blocking I/O off the main thread.
`Context.register_receiver(receiver, IntentFilter(action), flags)` uses the
API 26 overload. `Context.RECEIVER_NOT_EXPORTED` requires API 33; use it for
app-private dynamic receivers and unregister them with their owning lifecycle.
`Intent.set_package()` restricts a broadcast's destination package.
`send_ordered_broadcast()` accepts a final receiver and optional Handler;
`pending.set_result_data()` and `receiver.get_result_data()` carry ordered
delivery results. Do not use result data on an unordered broadcast.

For direct-JVM Android UI tests, mark module-level functions with
`pytest.mark.pyjs_android_jvm` and use `pyjs.android.testing`. Run the fast
AndroidJUnit4, Robolectric, and Espresso tier with
`--pyjs-android-runtime=robolectric`. Run the same test in a managed emulator
with `--pyjs-android-runtime=device --pyjs-android-avd=NAME`; add
`--pyjs-android-headless` for a deterministic cold boot without a window.
Keep compiled tests self-contained and zero-argument; pytest fixtures,
parametrization, and per-item setup or skip behavior are not yet transported.
Select views with `by_text()`, `by_id()` or exact accessible names with
`by_description()`. These use Espresso matchers and normal action visibility
constraints; descriptions also let tests target images and icon controls.
`View.setClickable(False)` marks a view nonclickable without removing its
click listener, letting a parent handle taps on an otherwise inert child.
`setOnClickListener()` makes the view clickable again, so apply
`setClickable(False)` after assigning or replacing its listener.
Long-click and custom touch handlers remain independent.
Use `isClickable()` to inspect that state; disabled and nonclickable views are
not interchangeable for touch dispatch.
`--pyjs-android-timeout` bounds the entire compiled suite, not each test.
For large device suites, `--pyjs-android-batch-size=40` compiles and installs
once, then selects at most 40 tests per instrumentation process. The timeout
applies separately to each batch; compilation and installation are outside
that limit. Batches run sequentially and print their progress. Application
process state restarts between batches, but stored files and databases remain;
tests must initialize their own state. Within a batch, JUnit controls order.
Without the option, the existing single-suite execution is unchanged.
Robolectric and host-driven tests do not use this device-only option.
For shadow-based checks, add `pytest.mark.pyjs_android_robolectric` alongside
`pyjs_android_jvm`. Those functions are excluded from device compilation;
Robolectric classes must not be imported by device-reachable test helpers.
Do not combine this marker with `pyjs_android_device`.
Device timeouts retain completed results and fail unfinished tests with the
last started test and bounded output. A timeout after all results were reported
fails the last reported test to expose incomplete instrumentation teardown.
The runner stops its test packages on the selected device after a timeout;
later batches still run if cleanup succeeds. Cleanup errors fail remaining
unstarted tests without launching another batch. The emulator remains running
for reuse. No failed or timed-out test is retried automatically.

After `background()`, `resume()` waits for the Activity's resumed lifecycle
and, on API 29+, Android's window/input transaction barrier. This prevents a
temporary backgrounding Activity's input sink from consuming the next tap.
The barrier uses an instrumentation-only Android test API, preserves existing
accessibility services, and fails if its UiAutomation connection is missing.
It does not wait for application-specific asynchronous loading; assert that
the desired controls are ready separately. Earlier APIs retain lifecycle-only
synchronization.

Activities can override `onRestoreInstanceState(state)` and call the superclass
after asynchronously loaded controls exist. Retain the original bundle until
then; restoring into a loading placeholder cannot restore absent views.
Use `Bundle.put_bundle()` and `get_bundle()` to carry that pending state through
another recreation. Stable view IDs remain necessary. Do not replay a prior
account's native field state into another account's controls.

Use `saved_state_size(bundle)` from `pyjs.android.testing` to measure native
serialized Bundle bytes in Robolectric or device tests. It does not include
the surrounding Binder transaction or guarantee that a transaction will fit.
Keep large documents in durable storage rather than saved instance state;
`EditText` saves its full text by default. If disabling that with
`setSaveEnabled(False)`, explicitly retain any required focus, selection and
viewport metadata. `View.scroll_to(x, y)` dispatches to the native view;
subclasses may clamp offsets to their content bounds.

For Android reminders, obtain `"alarm"` or `"notification"` through
`Context.get_system_service()` and check the returned object's type against
`AlarmManager` from `pyjs.android.alarms` or `NotificationManager` from
`pyjs.android.notifications`. Services may be unavailable.
Use `NotificationChannel` and `NotificationBuilder` on API 26+. Channel
importance and global notification permission are separate; inspect both
`manager.are_notifications_enabled()` and `channel.get_importance()`.
On API 33+, declare `android.permission.POST_NOTIFICATIONS` and request it
from a user action with `Activity.request_permissions(JVMArray[str], code)`.
Handle `on_request_permissions_result`; an empty results array is possible.
Do not interpret a permission request or `notify()` return as visible delivery.

Alarm times use epoch milliseconds for `RTC`/`RTC_WAKEUP` and elapsed realtime
for the other clock types. Inexact `set_and_allow_while_idle()` may be delayed.
On API 31+, check `can_schedule_exact_alarms()` before using
`set_exact_and_allow_while_idle()`, and configure the required special app
access separately; ordinary runtime permission requests do not grant it.
Even after a positive check, handle a scheduling permission failure.
Use explicit immutable PendingIntents and distinct identities for unrelated
schedules. Extras alone do not distinguish PendingIntents. Cancel stale
operations and verify the current durable schedule before posting a reminder.
Apps own rescheduling after reboot, permission changes and account switches;
these declarations do not persist or reconcile schedules automatically.

Use `launch_intent(intent)` for share/deep-link startup tests. Build an explicit
intent with `Intent().set_class(application_context(), YourActivity)` and add
the action, MIME type and extras before launching. Activities receive later
deliveries through `on_new_intent()`; call the superclass and `set_intent()`
when future reads and configuration changes should use the new intent.
This does not change Android's launch record; process death may restore the
original launch intent. Persist capture identities and contents separately
and make processing idempotent. Read shared text with
`get_char_sequence_extra()` and `to_string()` to accept styled text too.
For a single shared attachment, read
`intent.get_parcelable_extra(Intent.EXTRA_STREAM)`. Check `isinstance(value,
Uri)` and `value.get_scheme()` before opening it. A parcelable extra is not
necessarily a URI; reject unsupported schemes rather than treating arbitrary
file paths as trusted input. `put_parcelable_extra()` accepts a declared
`Parcelable` binding, such as `Uri` or `Intent`, or `None`; not every Android
parcelable type has a corresponding binding. Android controls URI grants: read
permission is not persistent ownership, and the claimed MIME type is not
content validation. Copy accepted bytes into app-owned storage before
acknowledging a durable import. These bindings do not copy bytes or grant
permissions themselves.

For outgoing files, subclass `pyjs.android.files.FileProvider` and register
the generated subclass in a manifest overlay with `exported="false"` and
`grantUriPermissions="true"`. Keep the subclass reachable by constructing it
in `main()`, for example `SharingProvider()`. A manifest entry does not retain
a compiled class. Android constructs its own provider instance; do not define
a Python `__init__`, including on a Python base class. APK packaging rejects
missing generated provider classes and Python-initialized providers before
resource linking. External library providers are resolved by Android's tools.
Its `android.support.FILE_PROVIDER_PATHS`
metadata must reference a paths XML resource with a narrow sharing directory,
for example `<cache-path name="copies" path="outgoing/" />`. Do not expose
the whole cache, files directory, or filesystem. Include the AndroidX runtime.
Prepare a unique copy under `context.get_cache_dir()` with Java `File` and
`FileOutputStream`, closing the writer before handoff. Perform large writes
off the UI thread. `uri_for_file(context, authority, file)` returns the URI;
attach it as `Intent.EXTRA_STREAM` and as
`uri_clip_data(context.get_content_resolver(), label, uri)` using
`intent.set_clip_data(...)`. This setter returns `None`. Add only
`Intent.FLAG_GRANT_READ_URI_PERMISSION` for read-only copies. Large contents
belong in the file, not another text extra. Keep copies available while a
recipient may be reading them; chooser dismissal is not proof of delivery
or completion. Applications own bounded cache retention and failure UI.

For outgoing text, construct an `Intent` with `ACTION_SEND`, `text/plain`,
`EXTRA_TEXT` and an optional `EXTRA_SUBJECT`. From a user action, pass
`create_chooser(intent)` to the Activity's `start_activity()`. Import
`create_chooser` from `pyjs.android`; an optional title accepts a string,
native `CharSequence`, or `None`. Android may supply its own share title.
The chooser wraps the target without changing it. Dismissal is not proof of
delivery. Keep large documents out of Binder extras; share files through
content URIs with appropriate read grants instead. The helper does not create
a file provider or grant access to private files.
For anchored actions, use `pyjs.android.menus.PopupMenu(context, anchor)`.
Add entries through `get_menu().add(group_id, item_id, order, title)`, then
attach an `OnMenuItemClickListener` and call `show()`. Return whether the
selection was handled. `OnMenuDismissListener` also runs after cancellation;
do not interpret dismissal alone as a selected action. Menu items support
enabled/visible state; either listener can be set to `None` to detach it.
Use `finish()` to close a completed capture Activity; `is_finishing()` reports
whether finishing was requested, not whether content was saved. Wait for a
durable save acknowledgement before closing a form that promises persistence.
For caller-owned selection or widget configuration, set a cancellation default
with `set_result(Activity.RESULT_CANCELED)`. After successful completion, call
`set_result(Activity.RESULT_OK, result_intent)` before `finish()`. Result data
may be omitted or `None`; the caller receives it in `on_activity_result()`.
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
Use `device().press_back()` from that module to dismiss system screens such as
the Sharesheet. Espresso's `press_back()` requires a resumed app Activity and
is not a substitute while another app owns the foreground.

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
Use `Browser(hide_scrollbars=False)` for scrollbar and viewport-layout checks;
the default hides scrollbars to keep existing visual snapshots stable.

Use `await browser.restart()` inside a `Browser` context to verify durable
state across a real Chrome process restart. It closes existing pages and their
DevTools sessions but retains the owned temporary profile. Open fresh pages
afterward; normal context exit removes the profile. Forced termination can
leave temporary profile files. This does not simulate a crash. For offline
restart checks, stop the owned test server rather than
relying on a page's CDP network override, which ends with that page.
