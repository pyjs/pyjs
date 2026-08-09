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

Run `pyjs --version`, then replace `VERSION` in these version-matched locations:

- Rendered documentation: `https://pyjs.org/docs/VERSION/`
- Markdown source: `https://github.com/pyjs/pyjs/tree/vVERSION/docs`

Prefer released documentation over the `main` branch when behavior may have changed between
versions. Inspect the installed `pyjs` package and the source and tests exposed by installed
templates when the documentation does not cover an advanced case.

## Application model

- PyJS statically analyzes typed Python and emits JavaScript without a Python runtime.
- `CustomElement` classes are browser-native custom elements that can also render on the server.
- Use `@js` for code that must be available in the browser.
- Mark module values needed by compiled code as `JS[T]`; use `Final[JS[T]]` for immutable values.
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
- Inspect the installed components and their examples for the current APIs and
  composition patterns before using them.
- Hand-craft a control only when no suitable component exists or the design
  intentionally requires custom behavior.

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
app-scoped logcat. See the installed `pyjs_examples.nativescript_counter` tests for the complete
build, launch, interaction, and capture pattern.

Inspect the relevant template for current testing patterns. Normal application tree shaking omits
unreferenced test functions from the browser bundle.

## Verification

For a generated project, start with:

```bash
python -m pytest -q
python -m pytest -q --pyjs-target=web
python app.py
```

Use the run command from the template's README when the entry point is not `app.py`.

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
`examples/chatroom/visual_test.py` are working examples.
Prefer `wait_for_selector`, `wait_for_attribute`, `wait_for_text`, `wait_for_count`, `click`,
`fill`, `submit`, `attribute`, `attributes`, `text`, and `texts` over embedding JavaScript for
ordinary DOM interaction.
