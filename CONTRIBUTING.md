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

uv creates and maintains `.venv`; activation is optional. Python versions,
dependencies, pytest discovery, and Ruff rules are defined in
`.python-version`, `pyproject.toml`, and `uv.lock`.

The private development checkout contains the complete test suite. The public
release mirror intentionally contains only release files and example tests.
From that checkout, run:

```bash
uv run pytest -q examples
```

Public contributions are integrated into the authoritative development
checkout and validated against the full suite before the next public sync.

## Repository landmarks

- `pyjs/transpiler/` contains analysis, type modeling, JavaScript emission,
  source compilation, and bundle generation.
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
exit status. The user-facing testing model, markers, render assertions, and
artifact behavior are documented in [the testing guide](docs/guide/testing.md).

Android tests are opt-in and require a configured emulator. Run them when a
change affects `pyjs.nativescript`, Android tooling, or shared test artifacts.

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

## User-facing changes

Document behavior where its consumers will find it:

- `README.md` for installation, positioning, and the first workflow;
- `docs/` for concepts and API guidance;
- example READMEs for running and testing a particular application; and
- `pyjs/skills/pyjs/SKILL.md` for coding agents building with PyJS.

Add notable user-facing behavior and compatibility changes to the `Unreleased`
section of [CHANGELOG.md](CHANGELOG.md). Describe what changed for an
application developer rather than repeating the commit message. Small examples
are welcome when they make a compiler improvement or removed workaround clear.

Do not put framework usage instructions in the private repository
`AGENTS.md`.
