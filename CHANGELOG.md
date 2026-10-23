# Changelog

## Unreleased

### Changed

- Tailwind provisioning and Clang/browser discovery delegate to sdkmgr 0.3.
  Tailwind selects the exact supported release; explicit custom commands are
  retained. Browser discovery never downloads implicitly and reports setup
  instructions for pinned Chrome for Testing when no browser is installed.
  Invalid `CHROME_BIN` overrides, including empty values, now fail instead of
  silently falling back. Unset the variable to enable automatic discovery.
- `LLVM.version` and the native CLI's JSON `compilation.compiler` field now
  report sdkmgr's numeric compiler version rather than the full vendor banner.
- Android build tools use host-correct executable suffixes, and locked JAR/AAR
  downloads use sdkmgr's checksum-addressed cache. Cached artifact bytes are
  reverified; the previous coordinate-based cache is left untouched.
- Node discovery skips its shared cache when the working directory is no
  longer accessible, while retaining relative-path cache isolation.
- Node provisioning delegates to sdkmgr's mise/nvm providers instead of
  downloading archives into PyJS's own cache. Explicit executable selections
  remain supported; configure custom download mirrors through the provider.
- Android tooling uses sdkmgr's SDK-root and JDK 21 discovery. Existing SDKs
  remain usable without installing a new management CLI, and missing tools
  produce setup instructions without starting installers during tests.
  Automatic discovery requires JDK 21: other `JAVA_HOME` versions are skipped,
  and Android Studio's bundled JBR is no longer searched implicitly. Set
  `JAVA_HOME` to its JDK 21 directory to reuse it.
- Tests wait for Android boot completion before reusing an existing emulator,
  rather than treating ADB connectivity as installation readiness.

### Added

- Android Notes saves detached card-order snapshots on background threads.
  Completed drops coalesce behind a single writer; newer edits remain dirty
  until their own acknowledgement. Save failures retain retry diagnostics
  through Activity recreation. Native `AtomicBoolean` safely publishes worker
  results; the example's main-thread polling recovers them when posting a
  callback is rejected.
- Android packages can declare a process-scoped `Application` owner.
  Framework-created Activities and Applications reject inherited Python
  initializers as well as direct ones; initialize state in `onCreate`.
  Native threads, main-loop callbacks, synchronous preference commits and
  Activity destruction callbacks support coordinated background work.
  Compiled tests discover an unambiguous Application owner and can run
  main-thread callbacks without launching an Activity.
  Notes uses that owner to retain unsaved order and retry diagnostics across
  Activity recreation; process termination still loses unpersisted changes.
- Ordinary Python methods named `notify`, `notifyAll`, `wait` or `getClass`
  no longer collide with Java's final Object methods. Explicit native
  callback names retain their declared ABI.
- JVM `list(existing_list)` makes a detached shallow copy, including empty,
  nested and represented-item lists with matching storage. Native callback
  owners reached only through casts retain their fields and lifecycle
  methods, supporting framework-created Application state.
  Assigning an incompatible list layout to a Python-owned field is diagnosed
  during compilation rather than failing JVM class verification.

- Android Notes saves card order after completed drags and restores it on
  launch. Save failures preserve the previous snapshot and provide a retry
  action; invalid saved orders block automatic overwrites. Native Java file
  bindings and app-private file-directory access support the example's
  bounded, single-writer storage path, with preserved exception diagnostics.

- Managed JVM exceptions expose read-only `.args`, retaining original
  positional values and missing dictionary keys independently of messages.
  Reinitialization replaces the tuple without changing saved references.
  Existing custom numeric and reference payloads remain supported; erased
  numeric comparisons preserve Boolean/integer equality and mixed floating
  precision. Native exceptions reject Python argument inspection. Erased
  numeric and reference-array dictionary keys raise `TypeError` until
  Python-compatible hashing is supported.
- JVM reference-valued variable-length tuples support literals, typed calls
  and fields, identity, length, checked integer indexing and iteration.
  Unsupported tuple operations receive diagnostics; erased reference-array
  equality raises `TypeError` instead of silently comparing array identity.
- JVM applications can render Python-style exception chains with
  `pyjs.java.format_exception()`. Reports select explicit causes or unsuppressed
  context, preserve native frames and suppressed details, and safely handle
  cycles and long chains. Managed exceptions use the same reports for Java
  `printStackTrace()` overloads without changing their stored state.
- JVM exceptions expose read-only implicit context across handlers, helper
  calls and cleanup. Runtime and formatting failures retain the handled error;
  returns and unwinding restore the caller's state, independently per thread.
  Suppressed context remains inspectable, and exception reuse breaks implicit
  cycles. Native Java failures may be retained without mutating their state.
- JVM supports explicit exception causes and `from None`, with read-only
  cause/suppression state, identity-preserving replacement and Java cause
  reporting. Native failures can be retained as causes without mutating their
  Java state; foreign targets receive a focused diagnostic or `TypeError`.
- Native compilation is available directly from Python files, modules and
  command snippets with `pyjs --target native`. `pyjs build --target native`
  keeps a standalone executable, and `--perf` compares matching CPython/native
  process runs while reporting compilation time separately. Executable entry
  points may return `None`; simple top-level statements can be wrapped automatically.
- JVM custom exception classes support inherited catches, initializers, typed
  fields and retained identity. Default scalar text follows original positional
  arguments; custom string methods preserve virtual dispatch. Python methods
  cannot accidentally override native Throwable methods.
  Java logging preserves the original exception when formatting fails, and
  local `super()` aliases keep lexical parent dispatch. Exceptions crossing
  native calls, fields, views and callbacks retain custom text without Python
  string calls, including exceptions stored in typed maps or cast to object
  and nullable native views. Conditional values keep their common custom
  exception base, including formatting raw union locals, items and catches.
  Unsafe exception-erasing object locals receive a diagnostic without
  rejecting existing non-exception union and collection initializers.
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

- JavaScript string slices use Python character offsets rather than UTF-16
  offsets, keeping slices around emoji consistent with indexing and length.
- Native SSR retains reached Python record layouts regardless of package name,
  including navigation responses and dormant live-session fields. Partial
  standard-library models no longer fail on unused unsupported imports, and
  dialog trigger registration does not pull browser callbacks into SSR.
- JVM and LLVM bare reraises in return-path `finally` blocks now use the
  enclosing handler after the departing inner handler has been popped.
- JVM optional exceptions format absent values as `None` without dereferencing
  null. `str()`, f-strings and no-argument `__str__()` preserve present-value
  custom dispatch, single evaluation and implicit string-result validation.
  Python-authored formatters on native Throwable subclasses also participate
  through base views and mixed managed/native unions, without changing Java's
  native message methods.

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
