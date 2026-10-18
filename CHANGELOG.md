# Changelog

## Unreleased

### Added

- JVM custom exception classes support inherited catches, initializers, typed
  fields and retained identity. Default scalar text follows original positional
  arguments; custom string methods preserve virtual dispatch. Python methods
  cannot accidentally override native Throwable methods.
- JVM supports membership in integer/Boolean lists and reference-key
  dictionaries, including nullable keys. Membership syntax evaluates its
  needle before its container; explicit methods retain receiver-first order.
- JVM builtin exceptions can be stored, passed, returned and raised repeatedly
  while preserving identity and messages. Declared native Java constructors
  can also produce owned throwable values.
- JVM builtin exceptions and assertions accept integer and Boolean messages.
  Fixed-width integer values retain their normalized value; Booleans render as
  `True` or `False`. Numeric `KeyError` messages are not quoted.
- JVM missing dictionary keys raise catchable `KeyError`. String keys and
  explicit string messages preserve Python quoting and Unicode escapes,
  including the distinction between no argument and an empty string.
  Printability uses shared, pinned Unicode data across JVM and Android hosts.
- JVM synchronous context managers support nested cleanup, suppression,
  failed entry/binding, and returns or loop exits. Application `bool | None`
  values retain their distinct nullable representation, including `__exit__`
  results. Declared native Java exception classes support typed catches,
  narrowing and forwarding without losing the original throwable.
- JVM compilation supports ordered exception handlers, reraising, lazy
  assertions, and `finally` cleanup across returns and loop exits. Supported
  builtin Python exceptions retain their hierarchy and string messages;
  native Java failures remain catchable through `Exception`/`BaseException`.
- JVM strings support locale-independent `upper()` alongside `lower()`.

- Introduced this changelog. Future releases will record notable features,
  compatibility changes and fixes here.
- Pull-request CI covers Linux, Windows and macOS, including parallel LLVM,
  browser/WebGPU and Android tests, cross-platform package installation, and
  retained failure artifacts. Releases reuse the same validation workflow.
- Experimental native LLVM compilation and execution on Linux, macOS and
  Windows, on x64 and arm64. Shared tests cover executables and Python-loaded
  libraries; the README includes a runnable Python-to-native example.

### Changed

- JVM-controlled bounds, division, shifts, range steps and integer parsing
  now raise catchable Python exception categories. Representation limits use
  `OverflowError` or `MemoryError`; unrelated Java API errors remain native.
- JVM-raised Python exceptions now use generated Python-hierarchy classes,
  replacing the previous Java `RuntimeException`, `IllegalArgumentException`,
  and `AssertionError` mappings. Java callers should catch `Exception` or the
  generated type; Python assertions now extend Java `Exception`, not `Error`.
  Exception class names in JVM stack traces change accordingly.

### Fixed

- JVM nullable-string exception messages render a supplied `None` as Python
  text rather than an empty native message.
- Bare reraises remain valid after handler-local writes and branch narrowing.
- JVM and LLVM context-manager entry results can be optional values without
  crashing shared control-flow analysis.
- JVM executable string results retain UTF-8 encoding on non-UTF-8 consoles.
- Native output preserves UTF-8 and newline bytes across platforms; NaN
  formatting follows Python's sign and percentage rules on macOS too.
- Closing all handles to a native library unloads its code, allowing safe file
  replacement and recompilation without executing an earlier version. Use
  separate output directories for simultaneously loaded revisions.
- Browser test compilation no longer blocks control-connection keepalives;
  disconnected requests release pending results without overlapping builds.
  The runner page is prepared before readiness so cold compilation cannot
  strand the browser on an HTTP timeout page.

### Feature overview

PyJS compiles typed Python to JavaScript for browser applications, with
server-rendered HTML, custom elements, reactive UI and typed client/server APIs.
It also provides WGSL shader generation, JVM/Android tooling and experimental
WebAssembly support.

The upcoming 0.5.0 release introduces the LLVM native target, including compiled
Python data structures, managed memory and native HTML rendering. Target support
covers defined subsets of Python rather than arbitrary CPython programs.
