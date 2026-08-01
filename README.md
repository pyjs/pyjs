# PyJS: Python to JavaScript

> Pre-alpha: useful applications and tests work today, but APIs may change before the first
> release.

PyJS is a statically analyzed Python-to-JavaScript compiler. It turns reachable, typed Python code
into readable, tree-shaken JavaScript without shipping a Python runtime. Its current libraries make
it especially useful for server-rendered web applications and browser-native custom elements:
application code can render on the server, hydrate as native custom elements, and continue running
in the browser. Public APIs and values whose types cannot be inferred need type annotations.

Coding agents can run `pyjs skill` for version-matched instructions, then use `pyjs template` and
`pyjs template NAME` to discover installed examples and inspect their complete source. The
[installable PyJS skill](https://github.com/pyjs/pyjs/tree/main/pyjs/skills/pyjs) is also available
directly from the public repository.

## Goals

- No Python runtime in generated JavaScript
- Readable, performant JavaScript comparable to handwritten output
- Server rendering and browser behavior expressed with the same typed Python objects
- Browser-native custom elements as the application framework
- Enough well-defined Python semantics to build productive applications

## Non-goals

- Reimplement every Python feature or the complete standard library in JavaScript
- Preserve highly dynamic behavior such as runtime monkey-patching, `eval()`, or arbitrary imports
- Infer types when the source contains no usable type information
- Replace a production web server or a general-purpose Python test runner

## Getting started

Install PyJS and create a project:

```bash
python -m pip install pyjs
pyjs create hello_pyjs
cd hello_pyjs
python -m pip install -e ".[test]"
python -m hello_pyjs
```

Open <http://127.0.0.1:8000/>. The generated project has no Node.js configuration or JavaScript
source: it contains a custom element, server entry point, Python tests, and a browser test.

Run its test suite on either target:

```bash
python -m pytest -q
python -m pytest -q --pyjs-target=web
```

To work on PyJS from a source checkout:

```bash
python -m pip install -e .
```

Install the separate examples distribution when working on the examples:

```bash
python -m pip install -e examples
```

## Start from an example

PyJS distinguishes complete applications from small, focused samples:

```bash
python -m pip install "pyjs[examples]"
python -m pyjs_examples.calculator
pyjs template
pyjs template pyjs_examples.calculator
pyjs template pyjs_examples.calculator --src
pyjs create my_calculator --template pyjs_examples.calculator
pyjs create counter_demo --template pyjs_examples.counter
pyjs create my_counter --single-file --template pyjs_examples.counter
pyjs create state_counter_demo --template pyjs_examples.samples.state_counter
pyjs create dialog_demo --template pyjs_examples.samples.ui_dialog
```

`pyjs create NAME` creates a project in `NAME/`, with application code in
`NAME/NAME/NAME.py` and tests in `NAME/tests/`. Pass a destination as the second positional argument
to populate another directory, such as `pyjs create routine .`. Add `--src-layout` to put the
package under `src/`. After installation, `python -m NAME` starts either package layout.
`--single-file` explicitly requests one standalone Python file and requires a file template when
combined with `--template`. The `pyjs-examples` distribution registers both file and directory
templates and contains the source copied by `pyjs create`; templates are not embedded in the
scaffolding implementation.

## Run or inspect Python as JavaScript

For Node-compatible code, PyJS can compile and run a file, module, or command string directly with
its managed Node runtime:

```bash
pyjs app.py
pyjs -m package.module
pyjs -c 'print(6 * 7)'
pyjs -v -c 'print(6 * 7)'  # generated JavaScript followed by Node output
pyjs --src app.py          # generated source only
pyjs --src-all app.py      # entry source and tree-shaken dependencies
pyjs --perf -c 'print(sum(range(10)))'
```

Use `--json` for structured results or `--perf` to compare Python and generated-JavaScript timing.
DOM, WebGPU, and other browser APIs still run through an application or browser test.

## Build an entry point

The application server builds and serves browser assets automatically. To write the generated
JavaScript, CSS, and HTML explicitly:

```bash
pyjs build hello_pyjs.hello_pyjs:main
```

Use `--only-js` when only the browser bundle is needed.

## Application model

An application entry point returns a server-rendered DOM tree. Classes decorated with `@js` are
available to the browser compiler, and reachable methods are included in the generated bundle.
`CustomElement` subclasses render on the server and hydrate as browser-native custom elements.
`ref()` reconnects Python attributes to existing server-rendered nodes rather than recreating them.

Values that must survive rendering and hydration can live on the custom element as DOM attributes.
The `state()` descriptor and `@effect(...)` provide a small typed reactive layer for updating the
DOM imperatively. Server-only handlers and browser methods can coexist in the same module.

## Feature overview

### Tree shaking

PyJS starts at the selected entry point and includes reachable browser code. In this example,
`sleep()` and `run()` are reachable; `eat()` and `bark()` are omitted:

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

Ordinary event handlers and called methods do not need `include=True`. That option remains an
escape hatch for unusual methods invoked dynamically by JavaScript.

### Type inference and checking

The analyzer infers types from literals, constructors, calls, and control flow. Empty collections
and public boundaries generally need annotations because their element or return type cannot be
recovered from a value:

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

Type errors are reported during analysis instead of being deferred to generated JavaScript.
Diagnostics are improving and do not yet cover every invalid program equally well.

### Type narrowing

Union types narrow through `isinstance()`, branches, assertions, and null checks:

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

`is None` and `is not None` compile to nullish JavaScript comparisons, covering both JavaScript
`null` and `undefined`, while identity comparisons between ordinary objects retain identity
semantics.

### Operator overloading

Built-in operators use their normal JavaScript equivalents for compatible primitive values and
dispatch to Python special methods for user-defined classes:

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

The analyzer preserves concrete element and key/value types for built-in collections such as
`list[T]`, `dict[K, V]`, and `tuple[...]`. User-defined generic specialization exists in the
analyzer but remains experimental and is not yet a stable application-facing feature.

### Async code and exceptions

Async functions and `await` lower to JavaScript promises. Typed browser APIs such as `fetch()`,
WebSockets, and WebGPU use the same syntax as asynchronous Python code. Basic raising and exception
handling are supported, but exception semantics are not yet a complete match for CPython.

### Metaprogramming and compiler extensions

Module and class bodies execute in Python before analysis, so ordinary Python metaprogramming can
construct the definitions that PyJS later analyzes. The `@js` decorator also supports client
replacements and inline call generation for typed browser API bindings. Compilation extensions can
rewrite function ASTs and inject imports before analysis; the browser-testing integration uses this
mechanism for assertion diagnostics.

These are advanced integration tools. Application code should normally use typed Python and the
APIs already provided by `pyjs.web.dom`, `pyjs.web.domx`, and `pyjs.web.ui`.

## Web UI and state

`pyjs.web.ui` contains reusable custom-element components inspired by shadcn/ui and adapted for
normal Python imports, subclassing, and imperative DOM composition. The catalog includes forms,
dialogs, menus, popovers, tabs, accordions, data display, navigation, charts, and layout primitives.

```python
from pyjs.web.ui.button import Button
from pyjs.web.ui.card import Card, CardContent, CardFooter, CardHeader, CardTitle

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

Effects run during server rendering. Hydration reuses that rendered result rather than repeating
the initial effect in the browser.

## Testing

PyJS registers a pytest plugin that can run portable tests in Python or compile them for isolated
browser iframes:

```bash
python -m pytest -q
python -m pytest -q --pyjs-target=web
```

Use `pytest.mark.pyjs_web` for tests requiring native browser behavior and
`pytest.mark.pyjs_python` for tests that cannot be compiled. A filename such as
`test_browser_dialog.py` is only an organizational convention and has no implicit behavior.

Browser tests retain console output and errors. Tests that render meaningful UI retain their iframe
preview, and render assertions can compare screenshots against checked-in PNG baselines.

## Commands

| Command | Purpose |
| --- | --- |
| `pyjs --version` | Show the installed version |
| `pyjs FILE.py`, `pyjs -m MODULE`, `pyjs -c CODE` | Compile and run with managed Node |
| `pyjs --src INPUT` | Print generated JavaScript without running it |
| `pyjs --src-all INPUT` | Include all tree-shaken dependency sources |
| `pyjs --perf INPUT` | Compare Python and generated-JavaScript performance |
| `pyjs create NAME [DESTINATION]` | Create a starter project |
| `pyjs template` | List templates registered by installed packages |
| `pyjs template NAME` | Print the complete materialized template source |
| `pyjs template NAME --src` | Print the transpiled entry-module JavaScript |
| `pyjs build MODULE[:ENTRY]` | Write generated JavaScript, CSS, and HTML |
| `pyjs docs build` | Build a static documentation site |
| `pyjs docs serve` | Build and serve documentation locally |
| `pyjs skill` | Print version-matched instructions for coding agents |

The built-in application server is run from Python source with `serve(__file__)`; the generated
starter and examples already provide this entry point.

## Current limitations and missing features

PyJS is intentionally a typed subset of Python, and the first release remains pre-alpha:

- Multiple inheritance is not supported.
- Reflection, runtime monkey-patching, `eval()`, and arbitrary dynamic imports are outside the
  compilation model.
- Python standard-library and browser API coverage is incomplete; APIs are added as typed PyJS
  definitions.
- User-defined generic class specialization still has unsupported shapes and needs dedicated
  regression coverage before it is considered stable.
- Some invalid programs still produce low-level analyzer errors instead of concise diagnostics with
  precise source locations.
- Source maps from generated JavaScript back to Python are not implemented yet.
- The development server rebuilds when it starts, but browser hot reload is not implemented.
- Browser-target pytest fixtures and helpers are a subset of normal pytest; compatibility work such
  as browser-side `pytest.raises` remains planned.
- Tree shaking still has an `include=True` escape hatch for unusual methods reached only through
  opaque JavaScript dispatch.
- Reactive effects run immediately for each attribute mutation; updates are not currently batched.
- The bundled HTTP server and documentation server are development tools, not production servers.
- NativeScript output is experimental; the first proof of concept currently targets Android and
  covers a small set of core views.

See [TESTING.md](TESTING.md) and [TREE_SHAKING.md](TREE_SHAKING.md) for focused implementation
status. The broader guides and references live in [docs/](docs/).

## Development from a checkout

PyJS currently requires Python 3.14:

```bash
python -m pip install -e .
python -m pytest -q
```

The examples are a separate distribution:

```bash
python -m pip install -e examples
cd examples
python -m pytest -q
```

Run Ruff against changed Python files before submitting changes. Generated `.main.js`, `.main.css`,
and `.main.html` files are build artifacts rather than hand-authored source.

PyJS is distributed under the [BSD 3-Clause License](LICENSE).
