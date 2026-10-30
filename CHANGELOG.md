# Changelog

## Unreleased

- JavaScript source maps limit function-name labels to the function's opening
  parenthesis, so browser debuggers retain parameter and local variable names.
  Scope names also retain their correct indices across bundled Python modules.

- Language snapshots preserve located compiler and syntax diagnostics,
  including source ranges, error codes, related locations and repair guidance.
  Compiler locations follow Python's physical lines even when source contains
  form feeds or Unicode line separators inside strings and comments.

- Editor clients can request compiler-backed completions and call signatures
  for valid Python buffers, including unsaved imports, inferred members and
  generic call types. Custom queries analyze the cursor's function and its
  dependencies without replacing full-module snapshots.

- Document editing commands expose typed arguments and success results for
  native text insertion and undo history where the browser supports them.

- Generator expressions inside instance methods preserve their receiver,
  including nested expressions and deferred attribute reads.

- Existing xterm terminals expose typed font, scrollback and cursor options
  that can be updated without replacing their emulator or input subscription.

- Electron hosts can defer native window closes and send string messages to
  removable preload subscriptions without exposing Electron events to renderers.

- Browser `fetch` can be passed as an asynchronous callback, retaining its
  optional request options and dictionary conversion. Direct calls also honor
  keyword URL and request options.

- Browser tests execute as modules, supporting managed npm dependencies and
  their stylesheets in each isolated test frame. Error stacks retain Python
  source locations.

- JavaScript `JSON.stringify` accepts primitive values and arrays of
  primitives as well as object records. Ordinary Python dictionaries remain
  excluded because their JavaScript representation is a `Map`. Implicit and
  bare Python returns serialize as `null`, including in callback use.
  BigInt-backed `int64` values receive a compilation diagnostic; convert them
  explicitly to strings or safe-range integers. Named `value=` arguments
  serialize the value directly, without an extra object wrapper.

- Add typed xterm.js and FitAddon browser bindings for terminal output, input,
  fitting and disposal.
- Bundle self-contained package CSS through managed npm imports, preserving
  stylesheet identity across development and packaged applications.

- Hydrated proxy references retain their client helpers and imported type
  names without retaining unused browser construction paths.

- Rust benchmarks match Cargo's Linux release defaults, removing inherited
  standard-library debug information from the measured executable size.

- The performance page uses a sticky metric button bar, keeping comparisons
  switchable while scrolling through workloads without covering column labels.
  Explanations sit above the controls; the color key stays on the desktop bar.

- Performance source views fold generated runtime and module scaffolding while
  keeping algorithm instructions visible. Code-size figures count complete
  runnable artifacts, including support code, in a dedicated code-size view
  with secondary gzip figures for JavaScript.

- JVM compiles integer-keyed dictionaries and `math.sqrt()`, enabling the
  Histogram, Spectral norm and N-body benchmarks without rewriting their
  algorithms. Negative square roots raise catchable Python exceptions.
  Float conversion also accepts Boolean values.

- The performance comparison uses full-page scrolling instead of a nested
  table viewport, with inline source comparisons and a compact machine/toolchain
  footer. Repeated baseline labels and diagnostic details are omitted from the
  presentation; raw measurements remain in harness output. All workloads and
  runtime columns stay visible, with handwritten and transpiled targets paired.
- A category heatmap summarizes benchmark ratios and links to static workload
  sections, with equal workload weighting and no repeated coverage counters.

- JVM supports `list.pop()` with default, positive, negative and boolean
  indices, preserving item identity and numeric representation. Invalid
  indices raise `IndexError` without changing the list.
- JVM supports `list(mapping)` and `list(mapping.keys())` to snapshot keys
  in insertion order before changing a dictionary, and `del mapping[key]`
  with a catchable `KeyError` for absent keys.

- Reduce cold compiler analysis time and memory use by reusing flow write
  summaries, avoiding redundant annotation analysis, and allocating
  reachability sets only when needed. Finalized
  functions are reused during dependency scheduling.
- Preserve complete source spans for the first assignment to an instance field.

- Add `pyjs lsp` for versioned compiler type snapshots, source definitions,
  unsaved module batches, background indexing and persistent caches. An
  optional project interpreter keeps service and execution environments apart.
  Workspace imports preserve interpreter startup modules, and source positions
  follow Python physical lines, including comments containing Unicode
  separators and unsaved buffers with mixed line endings.

- JVM supports `math.isfinite()`, first-match `list.remove()` for strings,
  integers and booleans, same-storage list unpacking, reference-valued
  `set(iterable)`, and `dict.setdefault(key, default)`. Unsupported item
  domains and implicit `setdefault` defaults remain explicit boundaries.
- JVM module-qualified function calls use their static target rather than
  attempting to load the module as a runtime receiver.
- Typed Android drawing APIs expose Canvas, Paint, pointer events and native
  pinch-scale recognition, with View drawing/touch callbacks. Reference-valued
  native class fields retain their declared type when their Python placeholder
  is `None` or omitted.
- JVM retains Java-invoked callbacks inherited through native superclasses,
  such as an Android TextView subclass overriding View's drawing callback.
- Tuple class-check diagnostics retain the original subject's source location.

- DOM render assertions use explicit integer pixel extents for fractional
  element sizes, avoiding browser-dependent screenshot dimension rounding.

- JavaScript Pydantic model decoding honors `extra="forbid"`, including
  nested, inherited and empty models. Explicit `extra="ignore"` overrides
  remain supported. Strict models no longer coerce integer value strings;
  JSON object keys still decode to their declared numeric key types.
  Union key schemas retain that conversion without relaxing value validation.
  Unsupported `extra="allow"` models now fail compilation instead of losing
  their dynamic fields.
  This does not add the full Pydantic validator or configuration surface.

- JVM class checks accept literal tuples, including nested and empty tuples.
  The checked expression runs once; existing native and emitted-class
  restrictions remain unchanged.
- The same single-evaluation lowering also supports application-defined
  `__round__()` dispatch on JVM.
- JVM integer `min()` and `max()` accept three or more positional arguments.
  Iterable and key-function forms remain unsupported.

- JVM list membership supports strings and nullable strings with value
  equality, preserving ordinary `in` evaluation order and explicit
  `__contains__` calls. Other mixed item domains remain unsupported.

- Android `Handler.postDelayed()` schedules callbacks on a message loop without
  relying on an attached View. Delays are milliseconds; callbacks still need
  lifecycle guards when their owning screen or account changes.

- Node hosts can perform bounded descriptor reads, inspect symlinks and file
  identity, flush descriptors, and publish hard links without replacing an
  existing destination. Incremental directory handles avoid materializing a
  whole directory. Unsupported requested open flags fail explicitly.

- Python Electron hosts can use partitioned Chromium sessions, protocol
  handlers, cookie-aware fetch, request/navigation guards, controlled popup
  handling, and native menus. Window preferences default to sandboxing and
  isolation; hosts can retain a server origin without exposing Node to pages.

- JavaScript chained comparisons can await any operand without generating
  invalid synchronous arrow functions. Operands still run once, in order,
  and later operands are skipped after a failed comparison. Only source
  `await` expressions suspend execution; comparison plumbing adds no pauses.

- IndexedDB `transaction_result()` waits for the transaction to commit,
  propagates aborts and request failures, and rolls back when the supplied
  operation fails. This supports atomic local saves across related records.

- Write Electron hosts and sandboxed preloads in Python, compiled with source
  maps during application builds. Typed Node/Electron bindings support host
  services without shipping Python at runtime. Standalone `--target node`
  builds and `pytest --pyjs-target=node` run Python-authored services and tests
  in Node, while existing CommonJS hosts remain supported.

- Android application builds merge AAR manifests with Android's official
  merger, retaining library components, provider metadata and permissions.
  Explicit application overlays resolve conflicts without dropping library
  declarations. SDK incompatibilities and unresolved placeholders fail early.
- Android clients can use typed SQLite database, cursor and prepared-statement
  APIs for transactional local storage, with parameter binding and catchable
  native database exceptions.
- Android shared-preference editors expose `clear()`, retaining native
  deferred commit and chaining semantics for local-storage cleanup.
- JVM native function bindings can call static interface methods with
  `interface=True`, including factories used by AndroidX callback APIs.
- Fresh browser/Android test imports preserve dependencies installed in a
  project-local virtual environment, keeping pytest session fixtures usable
  after compiled tests run. Registered Django models, loaded admin modules and
  their parent packages retain identity while client children reload without
  stale package bindings or duplicate admin registration. Host imports are
  restored after each build, including failures, so server views and model
  methods remain callable after compiling their clients.

- Package Python UI entries with stock Electron using
  `pyjs build my_app --target electron -o dist/my-app`. Builds include Python
  source maps and a sandboxed renderer; optional app-owned Node hosts provide
  desktop services. Outputs are host-platform application directories, not
  signed installers. Browser and desktop pages with managed npm imports now
  load their generated JavaScript as a module.

- The local Stripe simulator supports explicit and clock-driven checkout
  expiry, blocks payment after expiry, and supports invoice retrieval and
  customer/status-filtered forward pagination through the official SDK.

- Django queryset pagination preserves timestamp and time microseconds in
  cursor boundaries and query fingerprints, avoiding skipped or repeated rows
  when ordered values fall within the same millisecond.

- Java and Android clients can use native ISO calendar dates, device-local
  today, time zones and fixed clocks through `pyjs.java.time`. Android requires
  API 26 or newer; calendar failures remain catchable native exceptions.

- JVM method receivers and arguments retain class refinements from type guards
  even when their local slot has a broader declared type. Reference casts are
  inserted where a typed consumer requires them, not on base-compatible uses
  of locals that may have copied stale attribute refinements. Overridden
  methods and properties keep their base declarations reachable; JVM virtual
  dispatch and inherited field access use compatible declaring owners.
  Keyword/default binding checks stay within the stored receiver's hierarchy,
  excluding unrelated siblings of an inherited method's declaring class.
  This is not a general mutable-field flow-analysis repair: compiler-generated
  indexed/chained assignment temporaries can still retain stale refinements.
- JVM fixed tuples can be unpacked into local names, including nested tuples,
  swaps and repeated targets. Nested tuple iteration uses the same assignment
  rules. Ordinary unpacked values clear earlier inferred numeric formats,
  avoiding unintended fixed-width truncation. Variable-length unpacking remains
  unsupported, with an explicit diagnostic for starred targets.
- JVM dictionaries support `pop`, including eager defaults, nullable values,
  missing-key errors, and iterator invalidation after removal. Shallow `copy`
  preserves insertion order without sharing key-set mutations.
- JVM programs support stable `sorted()` over ordinary lists, strings and hash
  keys, shallow `list.copy()`, and basic reference-valued sets. Sorting leaves
  source containers unchanged; unsupported callbacks and represented items
  receive explicit compilation errors.

- Dictionary `pop(key, default)` accepts a fallback outside the stored value
  type, matching `get()`, including `None` for non-nullable reference values.
- `pyjs.java.uuid` exposes Java UUID generation, parsing and string conversion
  on JVM and Android. Native `IllegalArgumentException` is catchable through
  `pyjs.java.errors`; UUID parsing retains the platform's acceptance rules.
- Immediately awaited objects preserve instance fields, properties, methods,
  and represented numeric fields across JavaScript, JVM, and LLVM lowering.
- Empty list and dictionary branches inherit an unambiguous sibling's storage
  type before conditional lowering, including nested fresh empty lists and
  fixed-width items. Nested fresh empties in list, tuple and dictionary
  literals also inherit sibling storage. Existing container aliases keep
  their storage and identity.
- JVM clients generate typed remote operations from ordinary API declarations
  without including server bodies. Nested model results and structured errors
  are decoded on the client. Generated codecs alias their builtin bindings;
  existing source-analysis restrictions still apply, including string Literal
  annotations beside parameters named `str`. Malformed numeric statuses retain
  the normal operation-error fallback. This does not add cancellation, streams,
  resource relationships, or nonblocking execution.
- Pydantic client models support `model_dump_json()` and
  `model_validate_json(text)` in JavaScript and JVM programs, reusing typed
  client schemas for local persistence. JVM codecs cover the existing finite,
  acyclic API schema subset; full Pydantic validation stays on the server.
  Invalid JSON reports `ValueError` on both targets. JavaScript rejects
  ambiguous date/datetime JSON output and non-finite numbers rather than
  silently shifting dates or replacing numbers with null.
- JVM transports support isolated in-memory cookie sessions, GET bootstrap,
  and UTF-8 form submission for Django login/logout. CSRF headers remain
  explicit; credential persistence and lifecycle handling stay with the app.
- JVM list and application-length truth tests reject negative lengths even
  under negation while preserving boolean length results as zero or one.
  Explicit-separator string splitting supports bounded splits
  and preserves trailing empty fields; whitespace splitting remains unsupported.
- JVM lists support in-place `reverse()`, retaining aliases, element identities
  and fixed-width numeric representations without allocating a replacement list.

- JVM nullable integers and floats retain `None` through calls, fields, and
  collections, with exact numeric equality and Python-compatible truth tests.
  Ordinary scalar method signatures keep their primitive ABI.

- JVM conditions can short-circuit mixed string, integer and Boolean operands
  without materializing an incompatible result union. Value-returning mixed
  unions retain their existing storage restrictions. Nullable strings preserve
  their empty/missing false values in conditions and fallback expressions.

- Android application packages can declare permissions and reference an
  app-owned network-security XML resource. Defaults still request no network
  access and retain the existing cleartext policy.

- Plain Pydantic models can be constructed as typed JVM field containers with
  inherited defaults and nested values. Server validation stays server-side;
  unsupported model hooks and configurations receive explicit diagnostics.
  Redeclared inherited fields share their original storage, including reads
  and writes through base-typed references; incompatible redeclarations fail
  compilation instead of creating shadow fields.

- String `Literal` values retain ordinary string storage and operations in
  JVM code, including containers and iteration. Native iteration also accepts
  string literals without losing their declared value constraints.
  Aliased `Literal` imports now work in local annotations across backends.
- JVM dictionary iteration preserves insertion order and supports live key
  views. Key-set changes during iteration raise a Python `RuntimeError`.

### Changed

- JVM application calls support keyword and keyword-only arguments, including
  defaults, inherited methods, and constructors, without reordering argument
  evaluation. Native Java calls continue to require positional arguments.
  Keyword-only overrides with incompatible binding contracts are rejected.
  Virtual calls using ordinary keywords or omitted defaults also reject
  incompatible override binding instead of silently swapping arguments or
  choosing the wrong default. Fully supplied positional calls retain support
  for renamed override parameters.
- JVM and Android clients can read schema-directed JSON tokens and quote JSON
  strings without an additional runtime dependency. Unknown values are
  validated with bounded nesting. Typed number readers reject signed-integer
  and finite-double overflow.
- JVM chained comparisons retain Python short-circuiting and single operand
  evaluation. String ordering compares Unicode code points, and `chr()`
  supports the full Unicode range with Python-compatible range errors.

- JVM API transport can POST UTF-8 JSON through the existing client transport
  interface, retaining error bodies with bounded response size and explicit
  connect/read timeouts. Native calls require a worker thread on Android;
  lifecycle integration remains application-owned.
- JVM Python property getters now preserve inherited virtual dispatch and
  declared numeric representations, including shared response properties.

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
- LLVM integer dictionary/set lookup hoists key loading and equality dispatch
  out of its dense scan, retaining full-width equality and first-match order.
- LLVM keeps non-suspending range-loop cursors in function-local storage and
  reuses checked list/tuple indices instead of repeating normalization and
  bounds checks. Negative indexing, catchable errors and suspended-generator
  state retain their existing behavior.
- JVM-generated functions compute operand-stack bounds from control flow,
  avoiding oversized declarations that prevented HotSpot JIT compilation.
- JavaScript lowers direct builtin `range()` loops to counted loops, retaining
  argument evaluation order, independent loop-target assignment and loop-else
  behavior without a generator/iterator allocation.
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

- `pyjs.web.async_lock.AsyncLock` serializes asynchronous browser operations
  in acquisition order, with a matching CPython implementation for tests.
  Release it in `finally` to preserve progress after request failures.
- Native `async def` and nested `await` use managed suspension frames, including
  custom await iterators, async callbacks and methods, exception propagation,
  and explicit close through `finally`. Synchronous host drivers can use the
  coroutine's `__await__` iterator; native entry points remain synchronous.
  An event loop, `asyncio`, and async generators are not included.
  Custom awaitables use concrete class annotations; `Awaitable[T]` storage is
  reserved for coroutine results, and `Awaitable` subclasses receive a diagnostic.
- Native compiler and LLVM tooling entry points accept per-compilation
  `library_mappings` for host interface implementations. Custom resolvers
  preserve native builtins and do not replace the default resolver, including
  during nested compilations or after a failed compilation.
- JVM strings support `replace`, code-point iteration, unit-step slices,
  `ord`, and signed `hex`. Scalar dictionary values can be stored and read
  through subscription or `get` with a matching default; optional scalar
  results and primitive dictionary keys remain unsupported.
- Android document export can use `ContentResolver.open_output_stream` and
  `Intent.EXTRA_TITLE`, Java output/character writers, and Android's streaming
  `JsonWriter`. Applications retain ownership of closing streams and handling
  provider failures.
- JVM class emission bounds conservative operand-stack sizes by method size,
  avoiding spurious stack overflows at JIT transitions for small methods.
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
- A source-first performance lab under `perf/` compares shared Python workloads
  on CPython and PyJS JavaScript, LLVM and JVM targets with JavaScript, Rust and Java
  references. Bounded sequential runs retain correctness checks, exact tool
  versions, raw samples, startup and warmed timings, memory and build costs.
  JSON snapshots feed a live PyJS UI exposing source, generated code, failures
  and measurement caveats rather than an aggregate language ranking. Its
  comparison matrix puts workloads in rows and runtimes in columns, with
  a fixed CPython baseline, paired handwritten/transpiled target columns,
  target-group filtering and pinned workload labels. A row-scaled heatmap
  highlights relative costs among non-CPython targets, and clicking a cell
  expands side-by-side Python and selected-runtime source directly beneath its
  row, including on phones. Matching outlines connect selection and code;
  the newest run is clearly identified and history stays under run details. Bounded
  batch calibration, readable per-fork traces and warmup-drift warnings flag
  weak measurements. Optional separate JVM compilation diagnostics expose
  rejected JIT compilation without contaminating the measured timings.
  Fifteen workloads include recursive Fibonacci, heap sort, dictionary counting,
  Unicode scanning, binary trees and Mandelbrot alongside sieve, matrix and
  object traversal, plus N-queens, permutations, Towers of Hanoi, bouncing
  particles, spectral norm and N-body; independent oracles validate every
  measured batch. Comparable algorithms use ordinary language idioms rather
  than per-language benchmark tricks; unsupported targets remain explicit.
- `pyjs serve` and `pyjs docs serve` can open a local URL after startup with
  `--open PATH`. Application factories and explicit docs-server extensions let
  live Python UI share the same local server as documentation.
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
- Typed callbacks whose result is an optional awaitable now accept both
  synchronous and asynchronous functions, including bound methods.
- Native callback invocation declares its storage layout even when no
  concrete callback is constructed, such as in an empty typed registry.
- Suspended native generators and coroutines retain range-loop cursors across
  separate host calls, avoiding early completion or repeated iterations after
  the previous call's temporary arena has been released.
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
