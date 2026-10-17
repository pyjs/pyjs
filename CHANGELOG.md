# Changelog

## Unreleased

### Added

- Introduced this changelog. Future releases will record notable features,
  compatibility changes and fixes here.
- Pull-request CI covers Linux, Windows and macOS, including parallel LLVM,
  browser/WebGPU and Android tests, cross-platform package installation, and
  retained failure artifacts. Releases reuse the same validation workflow.

### Fixed

- JVM executable string results retain UTF-8 encoding on non-UTF-8 consoles.
- Browser test compilation no longer blocks control-connection keepalives;
  disconnected requests release pending results without overlapping builds.

### Feature overview

PyJS compiles typed Python to JavaScript for browser applications, with
server-rendered HTML, custom elements, reactive UI and typed client/server APIs.
It also provides WGSL shader generation, JVM/Android tooling and experimental
WebAssembly support.

The upcoming 0.5.0 release introduces the LLVM native target, including compiled
Python data structures, managed memory and native HTML rendering. Target support
covers defined subsets of Python rather than arbitrary CPython programs.
