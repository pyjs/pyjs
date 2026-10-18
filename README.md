<p align="center">
  <img src="branding/pyjs-logo.svg" alt="PyJS" width="170">
</p>

# PyJS: Python to JavaScript

[![CI][ci-badge]][ci] [![PyPI][pypi-badge]][pypi]
[![Python][python-badge]][pypi] [![License][license-badge]][license]

**Write typed Python for servers, browsers, and Android—without shipping a
Python runtime to JavaScript targets.**

PyJS statically analyzes reachable Python and emits readable, tree-shaken
JavaScript. The same component can render real HTML on the server, hydrate as a
native custom element in the browser, and share application logic with a
direct-JVM Android app.

PyJS is early-release software: complete applications and tests work today,
while APIs can still change between releases.

Browser JavaScript and direct-JVM Android are the application-facing targets.
The JVM, LLVM, and WebAssembly backends remain experimental; their APIs and
supported subsets may change rapidly.

## See it work in 30 seconds

```bash
python -m pip install "pyjs[examples]"
python -m pyjs_examples.calculator
```

Open the clickable local URL printed by the server. The Calculator is one
Python application targeting the Web, an installable PWA, and Android. Try the
[source](examples/calculator/calculator.py), then inspect its browser and
Android tests beside it.

PyJS keeps the generated result recognizable. Given:

```python
from pyjs import js


@js
def total(prices: list[int]) -> int:
    return sum(prices)


print(total([12, 30]))
```

`pyjs --src -c '...'` emits:

```javascript
export function total(prices) {
    return (prices).reduce((total,value)=>total+value,0);
}

export function main() {
    console.log(total([12, 30]));
}
```

There is no bundled Python interpreter, virtual DOM, or JavaScript project to
maintain.

## Create your first project

Install PyJS and create a project:

```bash
python -m pip install pyjs
pyjs create hello_pyjs
cd hello_pyjs
python -m pip install -e ".[test]"
python -m hello_pyjs
```

Open <http://127.0.0.1:8000/>. The generated project has no Node.js
configuration or JavaScript source: it contains a custom element, server entry
point, Python tests, and a browser test.

Run its test suite on either target:

```bash
ruff check .
python -m pytest -q
python -m pytest -q --pyjs-target=web --pyjs-browser=managed
```

To develop PyJS itself from a source checkout, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Try the experimental native compiler

The LLVM backend compiles a supported subset of typed Python to machine code,
without embedding CPython. During development, try it from a source checkout
with Python 3.14, uv, and a native Clang toolchain installed:

```bash
git clone https://github.com/pyjs/pyjs.git
cd pyjs
uv sync
```

Save this as `try_native.py` in the checkout:

```python
from pathlib import Path

from pyjs.tooling.llvm import LLVM

result = LLVM().run_source('''
def main() -> str:
    squares = [number * number for number in range(6)]
    return "Squares: " + str(squares) + "\\n"
''', directory=Path("native-build"))

print(result.stdout, end="")
if result.returncode:
    raise RuntimeError(result.stderr)
```

Run `uv run python try_native.py`. It prints
`Squares: [0, 1, 4, 9, 16, 25]` and retains the generated `program.ll` and native
executable in `native-build/`. Clang also needs the host's linker and C runtime
development libraries: Xcode Command Line Tools on macOS, or MSVC Build Tools,
the Windows SDK and Clang's compiler-rt on Windows. Use matching 64-bit Python
and compiler architectures. Set `PYJS_CLANG` to a compiler path if it is not on PATH.

This API compiles for the current host, not an arbitrary cross-compilation
target. CI compiles and executes on Linux, macOS and Windows, each on x64 and
arm64, including loading native libraries into Python. The executable entry
point is a zero-argument `main()` returning
`str` (written to stdout) or `int` (used as the process exit status). Arbitrary
Python packages and dynamic Python features are not automatically supported.

## What makes PyJS different

- **Python stays visible.** Generated JavaScript is readable and maps back to
  the original Python in browser DevTools.
- **HTML is the handoff.** Components render on the server, retain small typed
  state in the DOM, and hydrate the elements already on screen.
- **The browser is the framework.** Custom elements, attributes, events, and
  Web APIs remain direct platform primitives rather than a virtual DOM.
- **Types remove runtime weight.** Static analysis specializes Python semantics
  and tree-shakes code from each entry point.
- **Escape hatches stay open.** Typed browser APIs and raw transports remain
  available beneath the UI and full-stack conveniences.

Coding agents can run `pyjs skill` for version-matched guidance and
`pyjs template` to discover complete executable examples. The
[installable PyJS skill](pyjs/skills/pyjs/SKILL.md) is included in the package
and public repository.

## Start from an example

The separately installed examples progress from a one-file counter to composed
full-stack applications:

| Example | Purpose | Principal coverage |
| --- | --- | --- |
| [Counter](examples/counter.py) | Smallest app | DOM, events, tests |
| [Calculator](examples/calculator/) | Universal app | Web, PWA, Android, SSR |
| [Components](examples/components/) | UI reference | Widgets, forms, routing |
| [Notes](examples/notes/) | Personal app | Android, drag/drop, restore |
| [Chat](examples/chat/) | Real-time starter | WebSockets, multi-window |
| [Store](examples/store/) | Business app | Django, JSON:API, streams, themes |
| [Space Invaders](examples/space_invaders/) | GPU game | WebGPU, render tests |

Inspect or copy any of them:

```bash
python -m pip install "pyjs[examples]"
python -m pyjs_examples.calculator
pyjs template
pyjs template pyjs_examples.calculator
pyjs template pyjs_examples.calculator --src
pyjs create my_calculator --template pyjs_examples.calculator
pyjs create counter_demo --template pyjs_examples.counter
pyjs create my_counter --single-file --template pyjs_examples.counter
pyjs create components_demo --template pyjs_examples.components
```

The template catalog contains examples that can be copied safely out of their
installed package. Store is a comprehensive runnable application instead of a
scaffold because its Django package, fixture data, and optional server
dependencies belong together. Run it directly with:

```bash
python -m pip install "pyjs-examples[store]"
python -m pyjs_examples.store
```

`pyjs create NAME` creates a project in `NAME/`, with application code in
`NAME/NAME/NAME.py` and tests in `NAME/tests/`. Pass a destination as the
second positional argument to populate another directory, such as
`pyjs create example .`. Add `--src-layout` to put the package under `src/`.
After installation, `python -m NAME` starts either package layout through its
ordinary Python entry point. `pyjs serve` is also available as a convenience
and uses the application recorded in `pyproject.toml`.

`--single-file` explicitly requests one standalone Python file and requires a
file template when combined with `--template`. The `pyjs-examples`
distribution registers both file and directory templates and contains the
source copied by `pyjs create`; templates are not embedded in the scaffolding
implementation.

## Run or inspect Python as JavaScript

For Node-compatible code, PyJS can compile and run a file, module, or command
string directly with its managed Node runtime:

```bash
pyjs app.py
pyjs -m package.module
pyjs -c 'print(6 * 7)'
pyjs -v -c 'print(6 * 7)'  # generated JavaScript followed by Node output
pyjs --src app.py          # generated source only
pyjs --src-all app.py      # entry source and tree-shaken dependencies
pyjs --perf -c 'print(sum(range(10)))'
```

Use `--json` for structured results or `--perf` to compare Python and generated
JavaScript timing. DOM, WebGPU, and other browser APIs still run through an
application or browser test.

## Build an entry point

The application server builds and serves browser assets automatically. To
write the generated JavaScript, CSS, and HTML explicitly:

```bash
pyjs build hello_pyjs.hello_pyjs:main
```

Use `--only-js` when only the browser bundle is needed.

## Application model

An application entry point returns a server-rendered DOM tree. Classes
decorated with `@js` are available to the browser compiler, and reachable
methods are included in the generated bundle. `CustomElement` subclasses
render on the server and hydrate as browser-native custom elements. `ref()`
reconnects Python attributes to existing server-rendered nodes rather than
recreating them.

Module values cross the same explicit compilation boundary through a `JS`
annotation. Combine it with `Final` for constants, such as
`heartbeat_interval: Final[JS] = 5_000`; unmarked module values remain
server-only and cannot be included by an accidental browser-side reference.

Values that must survive rendering and hydration can live on the custom
element as DOM attributes. The `state()` descriptor and `@effect(...)` provide
a small typed reactive layer for updating the DOM imperatively. Server-only
handlers and browser methods can coexist in the same module.

## Feature overview

### Tree shaking

PyJS starts at the selected entry point and includes reachable browser code.
In this example, `sleep()` and `run()` are reachable; `eat()` and `bark()` are
omitted:

```python
from pyjs import js


@js
class Animal:
    def sleep(self):
        pass

    def eat(self):
        pass


@js
class Dog(Animal):
    def run(self):
        pass

    def bark(self):
        pass


def main():
    dog = Dog()
    dog.sleep()
    dog.run()
```

Ordinary event handlers and called methods do not need `include=True`. That
option remains an escape hatch for unusual methods invoked dynamically by
JavaScript.

### Type inference and checking

The analyzer infers types from literals, constructors, calls, and control flow.
Empty collections and public boundaries generally need annotations because
their element or return type cannot be recovered from a value:

```python
from pyjs import js


@js
class Animal:
    def __init__(self, name: str):
        self.name = name

    def get_name(self) -> str:
        return self.name


def main():
    values = {"one": 1, "two": 2}
    animal = Animal("Hazel")
    print(values["one"])
    print(animal.get_name())
```

Type errors are reported during analysis instead of being deferred to generated
JavaScript. Diagnostics are improving and do not yet cover every invalid
program equally well.

### Type narrowing

Union types narrow through `isinstance()`, branches, assertions, and null
checks:

```python
from pyjs import js


@js
def length(items: dict[str, int] | list[int] | str) -> int:
    if isinstance(items, dict):
        return len(items)
    if isinstance(items, list):
        return len(items)
    assert isinstance(items, str)
    return len(items)


def main():
    length(["one"])
    length({"one": 1, "two": 2})
    length("four")
```

`is None` and `is not None` compile to nullish JavaScript comparisons, covering
both JavaScript `null` and `undefined`, while identity comparisons between
ordinary objects retain identity semantics.

### Operator overloading

Built-in operators use their normal JavaScript equivalents for compatible
primitive values and dispatch to Python special methods for user-defined
classes:

```python
from pyjs import js


@js
class ListAdder:
    def __init__(self):
        self.values: list[str] = []

    def __add__(self, other: str):
        self.values.append(other)
        return self

    def __str__(self) -> str:
        return "|".join(self.values)


def main():
    values = ListAdder()
    values += "a"
    values += "b"
    print(values)
```

### Generic types

The analyzer preserves concrete element and key/value types for built-in
collections such as `list[T]`, `dict[K, V]`, and `tuple[...]`. User-defined
generic specialization exists in the analyzer but remains experimental and is
not yet a stable application-facing feature.

Typed tuples and lists can be unpacked into local names. Tuple and literal-list
arity is checked during compilation; dynamic lists retain Python's runtime
arity errors. Nested, starred, and chained unpacking targets are not yet
supported.

### Async code and exceptions

Async functions and `await` lower to JavaScript promises. Typed browser APIs
such as `fetch()`, WebSockets, and WebGPU use the same syntax as asynchronous
Python code. Basic raising and exception handling are supported, but exception
semantics are not yet a complete match for CPython.

### Metaprogramming and compiler extensions

Module and class bodies execute in Python before analysis, so ordinary Python
metaprogramming can construct the definitions that PyJS later analyzes. The
`@js` decorator also supports client replacements and inline call generation
for typed browser API bindings. Compilation extensions can rewrite function
ASTs and inject imports before analysis; the browser-testing integration uses
this mechanism for assertion diagnostics.

These are advanced integration tools. Application code should normally use
typed Python and the APIs already provided by `pyjs.web.dom`,
`pyjs.web.domx`, and `pyjs.web.ui`.

## Web UI and state

`pyjs.web.ui` contains reusable custom-element components inspired by shadcn/ui
and adapted for normal Python imports, subclassing, and imperative DOM
composition. The catalog includes forms, dialogs, menus, popovers, tabs,
accordions, data display, navigation, charts, and layout primitives.

```python
from pyjs.web.ui.button import Button
from pyjs.web.ui.card import (
    Card,
    CardContent,
    CardFooter,
    CardHeader,
    CardTitle,
)

profile = Card(
    CardHeader(CardTitle("Profile")),
    CardContent("Update your public details."),
    CardFooter(Button("Save changes")),
)
```

Reactive state is backed by custom-element attributes:

```python
from pyjs import effect, js, state
from pyjs.web.domx import CustomElement, ref, tag


@js
class Counter(CustomElement):
    count = state(0)

    def __init__(self):
        super().__init__()
        self.value = ref(tag("output"))
        tag(self, self.value)

    @effect(count)
    def render_count(self):
        self.value.textContent = str(self.count)
```

Effects run during server rendering. Hydration reuses that rendered result
rather than repeating the initial effect in the browser.

## Testing

PyJS registers a pytest plugin that can run portable tests in Python or compile
them for isolated browser iframes:

```bash
python -m pytest -q
python -m pytest -q --pyjs-target=web
```

Use `pytest.mark.pyjs_web` for tests that should be compiled and run in the
browser. Unmarked tests run only as ordinary Python tests;
`pytest.mark.pyjs_python` can make that intent explicit. A filename such as
`test_browser_dialog.py` is only an organizational convention and has no
implicit behavior.

Browser tests retain console output and errors. Tests that render meaningful
UI retain their iframe preview, and render assertions can compare screenshots
against checked-in PNG baselines.

## Commands

| Command | Purpose |
| --- | --- |
| `pyjs --version` | Show the installed version |
| `pyjs FILE.py`, `pyjs -m MODULE`, `pyjs -c CODE` | Run with managed Node |
| `pyjs --src INPUT` | Print generated JavaScript without running it |
| `pyjs --src-all INPUT` | Include all tree-shaken dependency sources |
| `pyjs --perf INPUT` | Compare Python and generated-JavaScript performance |
| `pyjs create NAME [DESTINATION]` | Create a starter project |
| `pyjs serve [TARGET]` | Serve a configured project, module, or Python file |
| `pyjs template` | List templates registered by installed packages |
| `pyjs template NAME` | Print the complete materialized template source |
| `pyjs template NAME --src` | Print the transpiled entry-module JavaScript |
| `pyjs build MODULE[:ENTRY]` | Write generated JavaScript, CSS, and HTML |
| `pyjs docs build` | Build a static documentation site |
| `pyjs docs serve` | Build and serve documentation locally |
| `pyjs inspect URL` | Capture a screenshot and structured browser diagnostics |
| `pyjs npm sync [TARGET]` | Install exact reachable JavaScript dependencies |
| `pyjs skill` | Print version-matched instructions for coding agents |

The built-in development server is run from Python source with
`pyjs.server.dev.serve(__file__)`; generated starters and examples already
provide this entry point.

Web compatibility modules can declare exact npm dependencies as module
metadata. `pyjs npm sync` analyzes the configured application and installs only
the packages reachable from its client bundle into `.pyjs/npm`; no user-owned
`package.json` or global npm installation is required.

Synchronize an application after adding its first managed JavaScript wrapper,
then build it normally.

## Current limitations and missing features

PyJS is intentionally a typed subset of Python, and the current releases remain
pre-alpha. This section summarizes the current boundary. Run `pyjs skill` for
guidance matching the installed version and inspect the executable templates
with `pyjs template`.

- Multiple inheritance is not supported.
- Reflection, runtime monkey-patching, `eval()`, and arbitrary dynamic imports
  are outside the compilation model.
- Python standard-library and browser API coverage is incomplete; APIs are
  added as typed PyJS definitions.
- User-defined generic class specialization still has unsupported shapes and
  needs dedicated regression coverage before it is considered stable.
- Some invalid programs still produce low-level analyzer errors instead of
  concise diagnostics with precise source locations.
- Generated bundles include source maps back to Python. Mapping coverage and
  browser-runtime presentation will continue to improve.
- The built-in development server rebuilds when it starts, but does not yet
  trigger browser reload itself. Reloadable Django applications can opt into
  the development browser reload client.
- Browser-target pytest fixtures and helpers are a subset of normal pytest.
  Browser tests support `pytest.raises()` as a context manager, including its
  `match` argument and captured exception value.
- Tree shaking still has an `include=True` escape hatch for unusual methods
  reached only through opaque JavaScript dispatch.
- Reactive effects run immediately for each attribute mutation; updates are
  not currently batched.
- The bundled HTTP server and documentation server are development tools, not
  production servers.
- Android uses direct JVM bytecode and native framework/AndroidX APIs.
  Calculator and Notes demonstrate the supported subset; Notes editor parity
  and broader platform coverage remain in progress.
- JVM exception handling supports ordered handlers, reraising, assertions,
  and `finally`, including cleanup across returns, breaks and continues.
  Builtin exceptions can be constructed, stored in fields or collections,
  passed and returned, then raised repeatedly without losing identity. They
  accept an optional string, integer or Boolean message. A nullable string
  containing `None` renders as `None`, distinct from an omitted message.
  Integers retain their signed 64-bit value and
  Booleans use Python's `True`/`False` spelling. Assertion messages use the same
  conversion and are evaluated only on failure. Float and container messages
  remain unsupported. Caught values support `str()`, identity and
  `isinstance()`.
  Native Java exceptions retain their native category: `Exception` catches
  Java exceptions, while `BaseException` also catches Java errors. Declare
  specific Java exception classes with `@jvm.native` to catch them directly.
  Controlled Python operations raise Python categories for invalid indexing,
  division by zero, negative shifts, invalid integer parsing and storage
  limits; arbitrary Java API failures are not relabeled.
- JVM dictionary subscription raises `KeyError` for missing keys without
  evaluating the mapping or key twice. Present `None` values remain valid.
  String and nullable-string keys retain Python-style quoted messages;
  `KeyError()` and `KeyError("")` remain distinct. Formatting uses pinned
  Unicode 16 printability rather than the host JDK's Unicode version.
  The existing UTF-16 representation conflates adjacent high/low surrogate
  code points with the corresponding astral character; quoting cannot recover
  that distinction. Isolated surrogates are escaped.
  Other reference-key lookups are catchable but currently use the generic
  message `key not found`; original exception payloads remain unsupported.
- JVM list membership supports matching integer or Boolean items; strings,
  floats and mixed item domains remain explicit unsupported boundaries.
  Dictionary membership checks keys, including nullable strings/Booleans,
  independently of their values. Existing reference-key storage restrictions
  still apply. Membership syntax evaluates the needle before the container,
  including application and declared native `__contains__` methods. Explicit
  method calls retain receiver-first evaluation order.
- JVM synchronous context managers support nested cleanup, suppression and
  abrupt exits. Exceptional `__exit__` calls receive a Java class token, the
  actual throwable and a JVM stack-trace array, not Python traceback objects.
  Normal exits receive three `None` values. Nullable Boolean results preserve
  the distinction between `None`, `False` and `True`.
  Native exception construction requires an explicit Java constructor
  declaration. Python's base-exception initializer does not specify Java
  overloads; inherited native declarations are trusted to describe the actual
  Java constructor signatures.
  Custom Python exception raising, chaining, `.args`, literal `None` messages
  and `UnicodeDecodeError` payloads remain unsupported. Explicit
  reraising keeps the original JVM stack trace rather than adding a Python
  traceback frame. Async context managers remain unsupported.

Run `pyjs skill` for the installed-version guidance and `pyjs template` for
complete executable examples.

## Contributing

The development environment, repository structure, compiler contracts, and
verification workflow are documented in [CONTRIBUTING.md](CONTRIBUTING.md).

PyJS is distributed under the [BSD 3-Clause License](LICENSE).

[ci]: https://github.com/pyjs/pyjs/actions/workflows/ci.yml
[ci-badge]: https://github.com/pyjs/pyjs/actions/workflows/ci.yml/badge.svg
[pypi]: https://pypi.org/project/pyjs/
[pypi-badge]: https://img.shields.io/pypi/v/pyjs.svg
[python-badge]: https://img.shields.io/pypi/pyversions/pyjs.svg
[license]: LICENSE
[license-badge]: https://img.shields.io/pypi/l/pyjs.svg
