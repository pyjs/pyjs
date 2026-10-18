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

Submit changes as pull requests to `pyjs/pyjs`, with focused regressions in the
patch. Keep PR descriptions focused on purpose, behavior, and compatibility
limits. Do not include local test commands, pass counts, environment reports,
or CI summaries; GitHub checks provide the test evidence.

## Pull-request CI

Every PR runs the full Linux corpus plus targeted Windows/macOS coverage on
standard GitHub-hosted runners. A failure does not cancel sibling targets.

| Runner | Coverage |
| --- | --- |
| Ubuntu x64 | Core/server, JS generation and semantics, WGSL, native WebGPU, JVM, WebAssembly, browser/WebGPU, Android Robolectric and emulator |
| Ubuntu x64, six LLVM shards | Every native test, including optimization variants, sanitizers and memory contracts; two processes per shard |
| Windows x64 and macOS arm64 | JS semantics, JVM/WASM execution, CLI/scaffolding, server lifecycle, tool downloads, browser DOM/platform APIs |
| Linux, Windows and macOS, each x64 and arm64 | Existing LLVM executable, shared-library, runtime algorithm, GC, exception, formatting and tooling contracts at O0/O2 |
| Linux x64/arm64, Windows x64, macOS x64/arm64 | Python source/wheel build and isolated install; portable npm runtime build/install smoke tests |

The portability lane does not duplicate compiler golden tests, GPU rendering or
Android SDK execution. Its three SDK-dependent classpath checks may skip; they
execute on Linux with the SDK installed. Native execution has its own
six-platform workflow, reusing test modules rather than copying tests per OS.
Linux runs the complete native corpus; the other hosts run a representative
selection including every Python-authored runtime module. Linux and macOS
retain sanitizer coverage. The hosted Windows toolchains lack complete
sanitizer runtimes: ordinary memory scenarios still run, while sanitizer-only
tests and POSIX descriptor inheritance explicitly skip there.
Core and Store Django settings are isolated in separate processes. Linux
browser coverage includes examples and extras, and managed-tool download tests
run on all three operating systems.

Reproduce a target with `uv run python scripts/ci.py js` (replace `js` with
`core`, `native`, `jvm`, `wasm`, `browser`, `android-robolectric`, or
`android-device`, or `portable`). Add `--collect-only` to inspect selection.
Native CI shards use `--shard 1 --shards 6 --workers 2`; without those flags,
the entire native suite runs sequentially. Modules are assigned by measured
cost, not filename count, and each module stays within one worker. Discovery
always includes new test modules even without recorded timings.
The main workflow installs Clang 21, JDK 21, Node 24, software Vulkan and the Android
35 SDK where needed. Native portability additionally exercises the runners'
preinstalled Clang/Apple Clang toolchains and records their versions and process
architecture. Windows requires the MSVC linker, Windows SDK and compiler-rt.
Local runs need the corresponding tools; browser runs
need Chrome, and device runs need a running emulator.

JUnit reports, logs and browser/device artifacts are retained for seven days,
including after failures. Native tests print diagnostic stacks after two
minutes in one test. Browser suites stop after ten failures to avoid retrying
one broken shared bundle hundreds of times; an interrupted suite is a failure,
not completed coverage. Skips remain visible. Empty selections fail.
Before merge, require both `CI complete` (all general test/package jobs) and
`Native platforms complete` (all six native hosts). Releases call both
workflows and cannot publish if either fails. The native workflow's test
command can also be run locally; see `.github/workflows/native-platforms.yml`.

Target elapsed time is below 30 minutes; investigate runs above 45 minutes.
These are tuning targets, not cutoffs: test and package jobs have a 120-minute
backstop and no per-step timeout. Queue delays are separate from execution time.
At most 12 test jobs and three package jobs run concurrently, with at most three macOS
jobs. The separate native matrix runs at most three jobs concurrently.
Superseded PR runs are cancelled. Only standard hosted runners are used;
no paid runner or increased cache allowance is required.

Compare wall time and total runner use before changing shards. Download the
JUnit artifacts for per-test durations; summarize job and test-step durations
without a GitHub write using:

```bash
gh run view RUN_ID --repo pyjs/pyjs --json jobs,status,headSha,createdAt | python scripts/ci_timings.py
```

The report labels incomplete runs and separates runner-minutes from the elapsed
job span. Runner-minutes are a resource measure, not a billing estimate.
The initial serial LLVM shards took 51–75 minutes. The checked-in module costs
come from that complete run; six balanced shards plus two workers preserve the
corpus while reducing idle runner capacity. Reassess both elapsed time and
aggregate runner use after changes. To refresh the scheduling estimates from
one complete run's downloaded JUnit artifacts:

```bash
python scripts/ci_timings.py --native-weights ARTIFACT_DIRECTORY
```

Review that JSON before replacing `scripts/ci_native_seconds.json`. Do not mix
runs or use truncated selections as representative timing measurements.

`uv run python scripts/check_distributions.py` builds all workspace source
archives and wheels, installs them into an isolated environment, and exercises
the installed CLI, SSR and example resources. The shared runtime build uses
this check on each release platform before its npm package smoke test.

All external contributors require a maintainer's approval before fork PR
workflows run. Review the proposed code and workflow changes before approving.
PR tests use read-only tokens, no repository secrets, and no self-hosted
runners. Release publishing remains protected and tag-triggered: it calls the
same CI workflow and publishes only after all tests/builds pass, without
rebuilding the tested npm archives. Release archives are retained for three
days; PR package checks avoid archive uploads. Manual single-platform builds
never publish and are not substitutes for the full release gate.

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
