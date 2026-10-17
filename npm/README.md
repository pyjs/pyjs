# PyJS npm packaging

This directory builds the separately published `@pyjsdev/cli` package for
people who want to try PyJS with Node.js without installing or configuring
Python. The npm package contains a portable CPython runtime and the ordinary
PyJS Python sources. The compiler remains a build-time tool and is not included
in generated browser bundles.

The builder supports GNU/Linux x64 and arm64, macOS x64 and arm64, and Windows
x64. Linux requires glibc; musl distributions such as Alpine are not supported.
GitHub Actions builds and smoke-tests each package on its matching native
runner, using `ubuntu-24.04-arm` for Linux ARM64 without emulation.

## Build and test

From the repository root:

```bash
python npm/scripts/build_runtime.py TARGET
python npm/tests/smoke_test.py TARGET --skip-build
```

`TARGET` is one of `linux-x64`, `linux-arm64`, `darwin-x64`, `darwin-arm64`, or
`win32-x64`. Build on the target operating system and architecture: both the
builder and the smoke test execute the embedded Python.

The first command downloads the pinned Python standalone archive, verifies its
SHA-256, installs the current PyJS checkout into it, and writes the platform
package under `npm/dist/`. The smoke test packs both npm packages, installs them
into a temporary project, and exercises the installed `pyjs` command.

Downloaded runtimes and generated npm packages are intentionally ignored by Git.

The resulting command exposes the same interface as the Python distribution,
including `pyjs -c CODE`, `pyjs FILE.py`, project scaffolding, and
`pyjs serve MODULE`.

## Intended package layout

`@pyjsdev/cli` is a small JavaScript launcher. It selects a package for the
current operating system and architecture, then invokes that package's
embedded Python with `-m pyjs`. The launcher selects the matching optional
platform package using Node's `process.platform` and `process.arch` values.
