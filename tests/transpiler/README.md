# Transpiler tests

Focused modules in this directory cover analyzer types, diagnostics, emitted
JavaScript, tree shaking, source maps, and compiler APIs. Add a regression to
the narrowest module that owns the behavior.

`cases/` contains end-to-end golden inputs. Each Python source can have:

- a `.types` file for the analyzed, typed Python tree; and
- a `.js` file for the complete emitted JavaScript module.

Use a golden case when several language features must compose across a full
module. Use a focused unit test when one expression, diagnostic, or lowering
rule is the contract under test.

Observable CPython and managed-Node parity belongs in `tests/semantics/`.
Browser-only behavior belongs in `tests/web/` or the owning example.

Prefer the transpiler assertion helpers and compare complete output. A narrow
substring assertion is appropriate only when unrelated generated scaffolding
would make the expected value obscure the behavior being tested.

Run a focused module while iterating:

```bash
pytest -q tests/transpiler/test_assignment.py
pytest -q tests/transpiler/test_cases.py -k CASE_NAME
```

Run `pytest -q tests/transpiler` before handing off a broad compiler change,
subject to the repository's test resource-safety guidance.
