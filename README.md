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

Save this as `primes.py` in the checkout. It counts primes with a sieve,
exercising list allocation, indexing, loops, branches and a reduction:

```python
def count_primes(limit: int) -> int:
    prime = [True] * (limit + 1)
    prime[0] = prime[1] = False
    factor = 2
    while factor * factor <= limit:
        if prime[factor]:
            for multiple in range(factor * factor, limit + 1, factor):
                prime[multiple] = False
        factor += 1
    return sum(prime)


def main() -> None:
    print(count_primes(2_000_000))


if __name__ == "__main__":
    main()
```

Run the same file with either interpreter or compiler—no decorators or source
strings are needed. Both print `148933`:

```bash
uv run python primes.py
uv run pyjs --target native primes.py
uv run pyjs --target native --perf primes.py
```

The last command compiles once, checks matching output and successful exits on
every run, then reports paired process timings. A Linux x64 run with CPython
3.14.4 and Clang 21 at `-O2` produced these timings (shown with the current
compiler label):

```text
Compilation: 1.818 s (21.1.8, O2)
Output matches: yes
148933
Median of 7 runs after 2 warmups (process startup included):
  CPython 3.14.4: 183.171 ms
  Native: 13.317 ms
  Speedup: 13.75x (compilation excluded)
```

These are measurements, not a universal speed guarantee. Compilation costs
more than a single interpreted run of this example; native execution pays off
when you reuse the binary or run a larger workload. `--perf` alternates which
program runs first, includes process startup and captured output for both,
and excludes compilation and the PyJS CLI's startup from execution timings.
Use `--samples N`, `--warmups N` or `--json` to inspect your own results.
On Windows a small CPython launcher configures UTF-8 output without newline
translation to match native output; its startup is included. Captured output
is compared byte-for-byte, not normalized after execution.

Keep an executable to run repeatedly without recompiling:

```bash
uv run pyjs build --target native primes.py -o primes
./primes
```

On Windows the output is `primes.exe`; run `.\primes.exe`. Native execution also
accepts `-m package.module`, `-c 'print(42)'` and stdin (`-`). Native builds
accept a file or module, optionally followed by `:entry_function`. Use
`pyjs --target native --src primes.py` to inspect the LLVM IR.
Default build output uses the source filename's stem (`__main__` for a package
entry); use `-o build/app` to choose a package executable's name without colliding
with the package's source directory.

Clang also needs the host's linker and C runtime
development libraries: Xcode Command Line Tools on macOS, or MSVC Build Tools,
the Windows SDK and Clang's compiler-rt on Windows. Use matching 64-bit Python
and compiler architectures. Set `PYJS_CLANG` to a compiler path if it is not on PATH.

This compiles for the current host, not an arbitrary cross-compilation
target. CI compiles and executes on Linux, macOS and Windows, each on x64 and
arm64, including loading native libraries into Python. The executable entry
point is a zero-argument `main()` returning `None` (success),
`str` (written to stdout) or `int` (used as the process exit status). Simple
top-level statements can be wrapped automatically. For scripts with helpers or
a `__name__` guard, use the guarded `main()` pattern above; pass configuration
into helpers rather than reading unannotated module globals. This avoids shared
analysis limitations and gives the same behavior under CPython and native execution;
CPython normally ignores a function's returned value. Imports, decorators and
module initialization execute in Python during analysis, so compile only code
you trust. Program command-line arguments are not yet supported. Arbitrary
Python packages and dynamic Python features are not automatically supported.
Initialization output is reported as compilation diagnostics on stderr, or
under `compilation` with `--json`, rather than mixed into the native result or
generated LLVM source.

Embedded hosts can select source implementations of imported interfaces with
`library_mappings=` on `transpile_llvm`, `transpile_llvm_module`,
`LLVM.run_source`, or `LLVM.compile_library` (and their comparison helpers).
Subclass `pyjs.native.analysis.NativeLibraryMappings`, override `resolve(value)`
to return the host implementation for a recognized Python class or function,
and delegate unhandled values to `super().resolve(value)`. Pass the resolver
instance explicitly for each compilation; it applies during analysis and
emission without modifying the default native resolver or Python imports.
The native semantic builtins and ABI remain unchanged. These mappings select
implementations; they do not provide a browser runtime, event loop, or additional
language support. Host implementations must use the supported native subset.

The native backend supports `async def` and nested `await` through managed
coroutine frames. Calling an async function creates a coroutine without running
its body. A synchronous driver can obtain `coroutine.__await__()` and advance
that iterator with `next`, `send`, `throw`, and `close`; completion arrives as
`StopIteration.value`. Custom awaitables can define `__await__` returning a
typed `Generator` and use their concrete class as the annotation. Native
`Awaitable[T]` storage currently represents coroutine results only; inheriting
from `Awaitable` is rejected rather than reinterpreting an application object
as a coroutine frame. Async callbacks and methods use the same call machinery.
The compiler does not supply an event loop or `asyncio` implementation. Native
executable and library entry points remain synchronous, and async generators
are not implemented. A host scheduler must own pending coroutine iterators,
resume them when operations finish, and close them before disposing its heap.

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

Node provisioning uses [sdkmgr](https://github.com/pyjs/sdkmgr), which reuses
mise or nvm and installs the requested version only when necessary. Explicit
`Node(executable=...)` and `PYJS_NODE` selections still take precedence and
require Node 20 or newer. Previous PyJS-managed Node caches are left untouched;
new installations belong to the selected manager. Configure mirrors through
that manager, not the retired `PYJS_NODE_MIRROR` setting. Constructing a `Node`
does not install anything; `ensure()` provisions it before execution. Path
properties only discover existing installations and report a missing runtime.
The optional `root` argument now controls sdkmgr's manager-bootstrap storage,
not the Node installation directory.

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

Use `pyjs.web.async_lock.AsyncLock` to serialize overlapping browser callbacks
that read state, await a request, and then update that state. Acquire before
reading the shared state, and release in `finally` so errors cannot strand the
queue:

```python
await lock.acquire()
try:
    await save_changes()
finally:
    lock.release()
```

Acquisition is FIFO and non-reentrant. The browser implementation does not
provide task cancellation or cross-thread synchronization; host-side tests use
an `asyncio.Lock` with the same acquire/release interface. Create host locks
per event loop; do not reuse a contended lock across separate `asyncio.run()`
calls.

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
- `AndroidJVMApplication.permissions` explicitly requests manifest permissions
  such as `("android.permission.INTERNET",)`. No permissions are added by
  default. `network_security_config="@xml/network_policy"` links an app-owned
  XML resource from `resources`; Android 7 and newer apply that policy instead
  of the manifest's default `usesCleartextTraffic="false"`. For local HTTP
  testing, allow only the emulator host `10.0.2.2` in a development resource,
  not all hosts. Supply a production policy when building for deployment.
  See the [Android network-security guide][android-network-security].
- JVM exception handling supports ordered handlers, reraising, assertions,
  and `finally`, including cleanup across returns, breaks and continues.
  Builtin exceptions can be constructed, stored in fields or collections,
  passed and returned, then raised repeatedly without losing identity. They
  accept an optional string, integer or Boolean message. A nullable string
  or Boolean containing `None` renders as `None`, distinct from omission.
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
- JVM strings support code-point iteration, `ord`, `chr`, `hex`, `replace`
  with optional positional or keyword `count`, and slices with a literal unit
  step or omitted step. Dynamic or non-unit steps remain unsupported.
  These operations retain the UTF-16 surrogate limitation described below.
  String ordering compares Unicode code points, not UTF-16 units. Chained
  comparisons short-circuit and evaluate each reached operand once, including
  nested chains and application comparison methods.
- JVM Python property getters support inherited virtual dispatch and retain
  their declared numeric representation. This does not add property setters
  or properties overriding ordinary instance fields.
- JVM application functions, methods, and constructors accept keyword and
  keyword-only arguments while preserving source evaluation order. Defaults
  must be immutable literals. Variadic parameters and keyword arguments to
  native Java declarations remain unsupported.
- Plain Pydantic 2 models compile as typed JVM field containers, with
  keyword-only construction, inherited fields, scalar defaults, nested models,
  and supported JVM collection types. Compiler type checks apply; Pydantic
  coercion and `Field` constraints remain server-side, not JVM validators.
  Custom validators/serializers, initialization hooks, aliases, generic models,
  mutable defaults/factories, frozen fields, and dynamic extras are rejected.
  Field access is supported; model equality, dumping, and JSON validation are
  not yet implemented. This is groundwork for typed API proxies, not parity
  with Pydantic's host runtime.
- `pyjs.server.jvm.JVMTransport` implements the existing `ClientTransport`
  HTTP interface using native Java HTTP(S), including on Android. It sends
  UTF-8 JSON and retains status/body for errors. Headers are explicit;
  redirects are not followed. Responses default to an 8 MiB byte limit.
  Set a finite request timeout for network operations; zero disables the
  connect/read timeouts. These are not total-request deadlines.
  Calls block the calling JVM thread despite the async interface: use an
  explicit worker, never Android's UI thread. This is a transport foundation,
  not yet generated JVM API proxies, Pydantic decoding, session management,
  cancellation, or lifecycle-aware delivery. Native I/O exceptions propagate.
- `pyjs.java.json.JSONReader` provides typed JSON tokens for schema-directed
  decoding without building an untyped object tree. Call `finish()` after
  reading the root value. `skip()` validates unknown values with a default
  nesting limit of 64 containers; number tokens keep their original spelling
  for the schema decoder to check range and precision. Diagnostic positions
  count UTF-16 units. `quote()` produces an ASCII-escaped JSON string.
  `integer()` requires a signed 64-bit integer token; `floating()` accepts
  finite binary64 values, preserving negative zero and ordinary underflow.
  Both reject overflow instead of silently wrapping or producing infinity.
  These helpers do not yet implement Pydantic decoding or typed API proxies.
- JVM dictionaries support ordinary integer, float, Boolean and reference
  values with reference keys. Iteration and live, reusable key views preserve
  insertion order. Updating values does not invalidate an iterator; changing
  its key set raises `RuntimeError`. Scalar `get` requires a matching default;
  omitted/`None` defaults for scalar values remain explicit boundaries.
  Dictionary subscription raises `KeyError` for missing keys without
  evaluating the mapping or key twice. Present `None` values remain valid.
  String and nullable-string keys retain Python-style quoted messages;
  `KeyError()` and `KeyError("")` remain distinct. Formatting uses pinned
  Unicode 16 printability rather than the host JDK's Unicode version.
  The existing UTF-16 representation conflates adjacent high/low surrogate
  code points with the corresponding astral character; quoting cannot recover
  that distinction. Isolated surrogates are escaped.
  Other reference-key lookups are catchable but currently use the generic
  message `key not found`; their original keys remain available through `.args`.
- JVM nullable integers, floats, and Booleans use boxed storage in parameters,
  returns, fields, and collections. `None` stays distinct from zero; equality
  keeps integer precision, including above `2**53`. Truth tests accept absence,
  zero, and NaN. Narrow with `is not None` before arithmetic or formatting.
  Represented values retain their wrapping and rounding rules. Mixed numeric
  unions such as `int | float | None` and scalar `isinstance` remain unsupported.
  Numeric identity checks only support comparison against `None`; nullable
  numeric dictionary keys remain unsupported.
  Explicit casts from present nullable numbers use the scalar ABI without
  losing integer precision. As with other static casts, callers must ensure
  the value is not `None` before casting to a non-null type.
- JVM list membership supports matching integer or Boolean items; strings,
  floats and mixed item domains remain explicit unsupported boundaries.
  Dictionary membership checks keys, including nullable strings/Booleans,
  independently of their values. Existing reference-key storage restrictions
  still apply. Membership syntax evaluates the needle before the container,
  including application and declared native `__contains__` methods. Explicit
  method calls retain receiver-first evaluation order.
- JVM `tuple[T, ...]` supports reference-valued items, including nullable
  references and nested tuples. Literals, calls, returns and fields retain
  identity; `len`, signed integer/Boolean indexing and `for` loops work.
  Primitive items, fixed-to-variable tuple conversions, slicing, repetition,
  membership, unpacking and structural equality remain unsupported.
  Equality on a reference array erased to `object` raises `TypeError` rather
  than using Java array identity; `is` and `is not` remain available.
  Use explicit `cast(object, value)` when erasing reference items to `object`;
  this does not add general primitive boxing.
- JVM synchronous context managers support nested cleanup, suppression and
  abrupt exits. Exceptional `__exit__` calls receive a Java class token, the
  actual throwable and a JVM stack-trace array, not Python traceback objects.
  Normal exits receive three `None` values. Nullable Boolean results preserve
  the distinction between `None`, `False` and `True`.
  Native exception construction requires an explicit Java constructor
  declaration. Python's base-exception initializer does not specify Java
  overloads; inherited native declarations are trusted to describe the actual
  Java constructor signatures.
  Writable chaining state, builtin literal `None` messages
  and `UnicodeDecodeError` payloads remain unsupported. Explicit
  reraising keeps the original JVM stack trace rather than adding a Python
  traceback frame. Async context managers remain unsupported.
- JVM managed exceptions expose read-only `.args` containing original
  positional values, independently of formatted text. Keywords and defaulted
  parameters are excluded; a base initializer replaces the tuple without
  changing previously saved tuples. Original references and currently
  supported numeric constructor payloads retain their values, including
  custom float and JVM-width arguments. This does not broaden default
  exception text or builtin constructor signatures. Native Java exceptions
  have no Python argument tuple: concrete access is rejected, while widened
  access raises `TypeError`. Tuple operations retain the limits above.
  Erased numeric payloads compare with Python's numeric equality, but cannot
  be dictionary keys yet: numeric and reference-array keys through an `object`
  view raise `TypeError` instead of using incompatible Java hashing.
- Native Java file bindings and Android `Context.getFilesDir()` support
  app-private storage. The Notes example demonstrates bounded card-order
  snapshots, checked replacement, failure reporting and retry without
  overwriting an unreadable snapshot. See its README for durability and
  host-platform limits.
- `pyjs.android.json.JsonWriter` writes structured JSON through native Java
  character writers. Use `StringWriter` for in-memory output or wrap a
  document provider's `ContentResolver.open_output_stream(uri, "wt")` in an
  `OutputStreamWriter(stream, "UTF-8")`. The resolver may return `None` or
  raise a native I/O/security exception. Close owned writers and streams in
  `finally`; closing `JsonWriter` also closes its underlying writer. A provider
  failure can leave partial output, so do not report success before close.
- Android packages can set `AndroidJVMApplication.application_class` to a
  source-defined `Application` subclass. Initialize framework-owned state in
  `onCreate`, not Python `__init__` (including inherited initializers).
  Compiled tests select the single most-derived Application owner; unrelated
  owners require separate test selections. Application state lasts only for
  the current process, not across process termination.
- `pyjs.java.concurrent` provides native `Runnable` and `Thread`;
  `pyjs.android.dispatch` provides `Handler` and `main_looper()`.
  `Handler.post()` reports queue acceptance, not completed or durable work.
  Keep UI state on the main thread, pass detached snapshots to workers, and
  acknowledge results on the main loop. These are not durable Android jobs.
  Compiled tests can use `pyjs.android.testing.run_on_main()` without a
  visible Activity.
- Notes demonstrates serialized background saves, detached snapshots,
  main-loop acknowledgements and Activity-scoped status observers.
  `pyjs.java.concurrent.AtomicBoolean` provides release/acquire publication
  for worker results; pending edits still require successful persistence to
  survive process termination.
- JVM `list(existing_list)` copies the list storage while retaining shared
  references to its items. Empty copies can grow normally. Source and result
  must have matching item storage and representation; converting other
  iterable kinds or item layouts remains unsupported.
- JVM custom Python exception classes retain inherited catches, typed fields,
  owned identity, custom initializers and module-scoped class identity.
  String/integer/Boolean positional arguments supply text without `super()`;
  keywords and defaulted parameters do not become that original text.
  `super().__init__(message)` can replace the text. Custom `__str__` methods
  keep virtual dispatch through base-typed and union-typed references.
  Field-only non-scalar arguments remain valid. Consuming their unsupported
  default text raises a focused `TypeError`; replacing it with a scalar message
  or providing a custom formatter avoids that unsupported operation.
  Java logging preserves the exception and stack trace if formatting fails,
  using `<exception str() failed>` as its message. Explicitly raised custom
  exceptions retain their formatters even without a Python `str()` call.
  The same applies to exceptions passed to native Java calls, exposed through
  native views, stored in native fields, or returned by Java callbacks,
  including typed map contents, `cast(object, ...)` and nullable native views.
  Conditional values retain a shared custom exception base when returning
  through that base. Raw sibling unions also retain formatting in conditional
  locals, list items and multi-type exception handlers.
  Optional exceptions format absent values as `None` through `str()`, f-strings
  and no-argument `__str__()` calls; present values keep custom dispatch.
  Python-authored subclasses of native Java throwables keep their formatters
  through these Python text operations, including mixed exception unions.
  Their Java `getMessage()` behavior is unchanged.
  `raise error from cause` retains cause identity for Python-managed
  exceptions; `from None` clears it and sets suppression. Read-only
  `__cause__` and `__suppress_context__` expose this state. Replacing causes,
  self-cycles, cleanup and reraising preserve Python semantics; Java stack
  traces show explicit causes. Native Java failures may be causes, but cannot
  receive Python-managed chaining state: concrete native targets are rejected
  at compile time, and widened targets raise `TypeError`. Foreign exceptions
  expose their existing Java cause and report no Python suppression flag.
  On managed exceptions, Java `initCause()` remains visible until Python
  explicitly sets or clears the cause; that Python state then takes priority.
  Use exception instances rather than classes for the raise/cause operands.
  Read-only `__context__` retains the active handled exception when a Python
  raise or runtime check fails, including in called helpers and cleanup.
  `from None` suppresses reporting without discarding this context. Nested
  handlers restore their enclosing state on return and unwind, and separate
  threads never share active handlers. Reusing exceptions breaks implicit
  context cycles without altering explicit causes. Native Java failures may
  be context values, but expose no Python context themselves.
  `pyjs.java.format_exception(error)` renders causes or unsuppressed context
  oldest-first, with Java frames, generated class names and native suppressed
  details. Managed exceptions use that rendering in all Java `printStackTrace`
  overloads too. Native roots keep Java's printer; use `format_exception` to
  include Python context beneath them. Reports handle cycles iteratively and
  do not mutate exception relationships or stack traces. Native suppressed
  subtrees retain Java's cause traversal. Invalid managed formatters render
  `<exception str() failed>` without losing the original failure.
  Reports use the host line separator and preserve PrintWriter auto-flush
  settings. For uncaught chains, Java's thread prefix precedes the oldest
  entry; the escaping exception appears last, following Python chain order.
  Assignment to chaining attributes remains unsupported.
  Explicit optional calls require string-compatible formatter results; narrow
  the receiver before consuming a differently typed custom result.
  `object` locals retain existing inferred union/collection storage, but
  cannot erase exception values or exception-bearing containers. Other plain
  `object` initializers remain unsupported unless the value is already erased,
  such as an argument-tuple item or explicit cast. Use explicit casts to expose
  supported reference values to Java.
  Explicit `__str__()` calls through base views require compatible override
  result types; narrow to the concrete type for a differently typed result.
  Local `super()` aliases keep lexical dispatch; mixed or escaping proxies
  receive a focused compilation diagnostic.
  Python methods are isolated from native Throwable method names. Custom
  `__new__`, unbound builtin initialization and multiple exception bases remain
  unsupported. Construct a custom-initializer class before raising it.

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
[android-network-security]:
  https://developer.android.com/privacy-and-security/security-config
