# Contributing to PyJS

PyJS is developed in Python 3.14 with uv. The source checkout is a uv
workspace containing the core `pyjs` distribution and the separately packaged
examples.

## Development environment

From the repository root:

```bash
uv sync
uv run pytest -q
uv run ruff check .
```

`ruff check` is the repository's linting contract. Do not run `ruff format`
across the repository: much of the existing source uses deliberate manual
layout, and formatter-only differences are not review failures. Maintainer
generators may invoke Ruff internally to produce deterministic generated
modules; that does not make formatting a general contribution requirement.

uv creates and maintains `.venv`; activation is optional. Python versions,
dependencies, pytest discovery, and Ruff rules are defined in
`.python-version`, `pyproject.toml`, and `uv.lock`.

The repository contains the complete product suite and example tests:

```bash
uv run pytest -q examples extras
```

Submit changes as pull requests to `pyjs/pyjs`. Include focused regressions,
the checks you ran, and any platform coverage you could not exercise.

## Pull-request CI

Every PR runs the Linux suite on parallel GitHub-hosted runners: core/server,
JS/WGSL, LLVM (four module shards), JVM, WebAssembly, browser, Android
Robolectric, and Android emulator. Browser tests include WebGPU, examples and
extras; managed-tool download tests and a Linux portable npm package build/install
smoke test also run. Core and Store Django settings
are isolated in separate processes. A failure does not cancel sibling targets.

Reproduce a target with `uv run python scripts/ci.py js` (replace `js` with
`core`, `native`, `jvm`, `wasm`, `browser`, `android-robolectric`, or
`android-device`). Add `--collect-only` to inspect selection. Native shards
use `--shard 1 --shards 4`; without those flags, the entire native suite runs.
The workflow installs Clang 21, JDK 21, Node 24, software Vulkan and the Android
35 SDK where needed. Local runs need the corresponding tools; browser runs
need Chrome, and device runs need a running emulator.

JUnit reports, logs and browser/device artifacts are uploaded even after
failures. Skips are visible in the report; a green run is not a claim of
Windows/macOS coverage or support for every Python/browser/Android API.
Empty test selections fail. `CI complete` requires every matrix job to pass.

Compare wall time and total runner use before changing shards. Download the
JUnit artifacts for per-test durations; summarize job and test-step durations
without a GitHub write using:

```bash
gh run view RUN_ID --repo pyjs/pyjs --json jobs,status,headSha,createdAt | python scripts/ci_timings.py
```

The report labels incomplete runs and separates runner-minutes from the elapsed
job span. Runner-minutes are a resource measure, not a billing estimate.

`uv run python scripts/check_distributions.py` builds all workspace source
archives and wheels, installs them into an isolated environment, and exercises
the installed CLI, SSR and example resources. The shared runtime build uses
this check on each release platform before its npm package smoke test.

All external contributors require a maintainer's approval before fork PR
workflows run. Review the proposed code and workflow changes before approving.
PR tests use read-only tokens, no repository secrets, and no self-hosted
runners. Release publishing remains separate and tag-triggered.

## Repository landmarks

- `pyjs/analysis/` contains source analysis, diagnostics, and the typed object
  graph.
- `pyjs/javascript/` contains ECMAScript APIs, emission, source maps, and
  bundle generation; `pyjs/shader/` contains WGSL APIs and emission.
- `pyjs/native/` contains the experimental LLVM emitter, native models and
  Python-authored runtime algorithms, including DOM storage and memory
  management; `pyjs/java/` contains direct JVM class-file emission.
  Native behavior and supported boundaries have executable coverage under
  `tests/native/`.
- `pyjs/web/` contains browser interfaces and web-specific libraries.
- `pyjs/web/ui/` contains reusable web components.
- `pyjs/testing/` contains the browser test runner and pytest integration.
- `tests/transpiler/cases/` contains Python inputs plus expected `.types` and
  `.js` output.
- `examples/` is both a browsable source tree and the `pyjs-examples`
  distribution.
- `scripts/` contains maintainer utilities; `external/` contains ignored
  research checkouts rather than product code.

The implementation is authoritative when prose and behavior disagree. CLI
behavior begins in `pyjs/cli.py`; public API behavior should also be covered by
tests and user documentation.

## Change discipline

Keep correctness fixes focused on the failing behavior. Avoid combining them
with unrelated refactors or formatting churn. Preserve user work in a dirty
checkout and distinguish hand-authored sources from generated artifacts such
as `.main.js`, `.main.css`, and `.main.html` files.

Match verification to the affected area. Run focused tests while iterating and
the broader relevant suite before handing off a change. Browser and visual
changes require managed-browser verification and inspection of captured
artifacts.

### Browser and platform verification

Run browser tests autonomously with the managed Chrome runner:

```bash
uv run pytest -q -m pyjs_web --pyjs-target=web --pyjs-browser=managed
uv run pytest -q examples -m pyjs_web --pyjs-target=web --pyjs-browser=managed
```

Use `uv run python scripts/capture_runner_screenshot.py` when changing the
runner UI, and inspect the PNG and JSON outputs rather than relying only on the
exit status. The README testing section and example tests demonstrate the
public testing model, markers, render assertions, and artifact behavior.

Android tests are opt-in. Use compiled Robolectric tests for host-side UI
checks, then a configured emulator for gestures and system UI. Run the
relevant tier when Android APIs, tooling, or shared test artifacts change.

## Compiler changes

The analyzer AST, typed output, and generated JavaScript are separate
contracts. Preserve the correct structure in the analyzed tree rather than
repairing it only while printing JavaScript.

For analyzer or transpiler changes:

1. Add focused source and type-analysis coverage.
2. Inspect generated JavaScript, not only Python-side behavior.
3. Update matching golden `.types` or `.js` files when the contract changes.
4. Prefer a narrow exceptional branch over restructuring shared analysis.
5. Run the relevant modules under `tests/transpiler/`.

Add reachability and inheritance regression coverage when a change affects
tree shaking or virtual dispatch.

Define a typed inline interface before its source generator when that generator
belongs to only one operation:

```python
@js
def operation(value: str) -> str: ...


@operation.inline(dependencies={"helper": helper})
def operation(value, helper, **kwargs):
    return f"{helper}({value})"
```

Keep a separately named generator only when multiple operations reuse it. This
ordering keeps the public compiler contract prominent and the implementation
local without leaving a one-use helper in the module namespace.

## Browser API changes

`pyjs.web` is reserved for web-platform APIs and web-specific libraries.
Testing conveniences and application-specific behavior do not belong on
browser globals.

Many browser declarations originate in WebIDL but remain intentionally
editable Python. WebIDL refreshes are maintainer-coordinated and must preserve
CPython implementations and deliberate type improvements. After substantial
core web API changes, run browser tests for every affected module.

Before committing a WebIDL-backed declaration change, run
`uv run python scripts/update_webidl.py --validate`, inspect the complete
`pyjs/web/` diff, and rerun it to confirm the patch is stable. Do this after
manual type or implementation improvements too, not only when adding an API
through the generator. If synchronization repeatedly overwrites an intentional
customization, fix the general merge rule and add a synchronization regression;
do not silently discard the unrelated diff or encode per-run approval state.

## User-facing changes

Document behavior where its consumers will find it:

- `README.md` for installation, positioning, and the first workflow;
- example READMEs for running and testing a particular application; and
- `pyjs/skills/pyjs/SKILL.md` for coding agents building with PyJS.

Describe notable user-facing behavior and compatibility changes from an
application developer's perspective rather than repeating the commit message.
Collect those notes in `CHANGELOG.md`. Small
examples are welcome when they make a compiler improvement or removed
workaround clear.

Keep framework usage instructions with the public documentation and examples.
