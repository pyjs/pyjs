# PyJS performance lab

One Python workload, four execution configurations: CPython, PyJS JavaScript
on Node, PyJS LLVM, and PyJS JVM. Handwritten JavaScript, Rust and Java implementations
provide reference points. This is a compiler investigation, not a universal
language ranking.

## Run a snapshot

From the repository root, with the development environment synced:

```sh
uv run python -m perf.run --output perf/runs/first --small
```

The initial measurement host is **Linux**. Install CPython, Node, Clang, Rust
and a JDK first. Nothing is provisioned by the benchmark runner. Missing tools
remain visible as unavailable configurations; any unsuccessful configuration
makes the command exit nonzero, but the JSON results are still saved.

Select exact executables explicitly:

```sh
uv run python -m perf.run --output perf/runs/baseline \
  --python /path/to/python --node /path/to/node --clang /path/to/clang \
  --rustc /path/to/rustc --java /path/to/jdk/bin/java \
  --javac /path/to/jdk/bin/javac --javap /path/to/jdk/bin/javap
```

Use the **same JDK** for handwritten Java and PyJS JVM. The compiler itself
runs under the synced repository Python, independently of the measured CPython.
Use a real rustc toolchain path when possible, rather than a mutable rustup
proxy. All discovered paths and exact version output are saved in each run's
`toolchains.lock.json`. The runner does not claim that PATH tools are latest.
The checked-in [version policy](toolchains.lock.json) records the latest-stable
versions checked for this slice and their upstream sources. Mismatches produce
visible warnings, not silent substitutions. Refresh that policy explicitly when
preparing a new publication snapshot; the per-run lock records actual tools.

A quick correctness/adapter check:

```sh
uv run python -m perf.run --output perf/runs/smoke --small \
  --forks 1 --warmups 2 --samples 2 --loops 2 --min-batch-ms 0
```

A larger exploratory run (still inspect warmup traces before publishing):

```sh
uv run python -m perf.run --output perf/runs/exploratory \
  --forks 5 --warmups 30 --samples 10 --loops 20
```

Add `--jvm-diagnostics` to run an additional checksum-validated HotSpot
compilation pass for each JVM/Java input. Its timing is excluded from the
comparison. The UI lists compiler failures and compiled methods, with links
to the original XML/log. An unsupported VM reports diagnostic unavailability
without discarding otherwise valid measurements. Verbose bytecode listings
include generated helper classes and their declared stack/local capacities.

By default, separate pilot processes calibrate each target/input toward a
50 ms batch, starting at `--loops` and bounded by `--max-loops` (1000).
The selected count and validated pilot traces are saved per row. Set
`--min-batch-ms 0` to use the same explicit loop count for every target.
Warmup, sample and fork counts apply to every target. A batch alternates N and N+1 inputs; the reported
warmed duration divides batch time by loop count. Both sizes have independently
checked expected results. `--small` selects the smaller configured base N only.
The full catalog has two base input sizes for each of fifteen workloads. A
snapshot can contain only a selected subset: use the snapshot selector to see
which workloads were actually measured. Omit `--cases` to run the full catalog.

Builds and measurements run sequentially with timeouts. Fork order is shuffled
with a recorded seed. Output directories must be new and are never overwritten.
An interrupted run retains the last complete JSON checkpoint with
`complete: false`. Do not run this beside CI, reviews, or other heavy tasks.

## Open the live PyJS UI

Start the local server and open the latest saved snapshot in one command:

```sh
uv run pyjs serve perf.app:create_app --open /perf/
```

Use `--port 0` for an available port, or open a specific snapshot with
`--open '/perf/?run=first'`. The browser opens only after the server is ready.
Stop the server with Ctrl-C. If a desktop browser is unavailable, the command
prints the URL for manual opening.

The UI has snapshot, metric, target-group and workload selectors; source panels; generated
JavaScript/LLVM/bytecode links; and raw samples, warnings and failure diagnostics.
Workloads and input sizes run down the left; runtimes run across the top.
CPython is always first, followed by the JavaScript / Py → JS, Rust / Py → LLVM,
and Java / Py → JVM pairs. Subtle group headers separate those pairs. Show all
targets or just one pair alongside CPython. Every target compares with CPython. Time
comparisons say faster/slower; RSS comparisons say less/more memory. Ratios
rounding to 1.00 show approximately equal, not statistical equivalence. Missing,
zero-reference or failed comparisons stay explicit, never fabricated speedups.
Workload labels and column headings remain pinned while scrolling the table.
Run metadata, methodology and raw evidence are expandable below the matrix.
Each measurement's evidence shows per-fork warmup endpoints, sample medians
and ranges before the raw JSON, plus JVM compilation diagnostics when requested.
Its DOM is authored in Python and its controls are compiled with PyJS.
It reads `perf/runs/*/results.json` on request; new snapshots appear without
rebuilding or restarting. Incomplete and failed runs remain visible. No HTML
reports or copied static sites are written by the benchmark runner.

The same UI can be mounted in a configured documentation project:

```sh
uv run pyjs docs serve --app perf.app:mount --open /perf/
```

This requires the usual docs configuration and an importable `perf` package.
An ordinary website can call `perf.app.mount(application)` directly, optionally
passing `root=Path(...)` and `prefix="/benchmarks/"`. The docs build itself stays
static; the live extension is registered by `docs serve`, not `docs build`.

Managed-browser verification against a running server, with desktop/mobile captures:

```sh
uv run python -m perf.check_page http://localhost:8000/perf/ --output perf/runs/first/browser
```

The snapshot contains source text, hashes, compiler revision/dirty state,
tool versions, build/run commands, warmup/sample traces, and summary statistics.
Generated code and logs stay beside it. Keep meaningful JSON snapshots, not every
smoke run. Generated builds and browser captures can be discarded after diagnosis;
retain binaries only when investigating an artifact-specific issue. JSON records
source and artifact sizes, but does not recreate the exact original binaries.
Snapshots contain local executable paths and diagnostics: review them before
publishing. Nothing automatically uploads or publishes results.

## Adding cases

The catalog includes sieve, matrix multiplication, object traversal, recursive
Fibonacci, heap sort, dictionary counting, Unicode text scanning, binary trees,
Mandelbrot, N-queens, permutation enumeration, Towers of Hanoi, bouncing
particles, spectral norm and N-body. These exercise calls, indexed mutation,
mapping lookups, text, recursive allocation, backtracking and floating-point
computation. Each source panel contains
the complete runnable kernel and references.
Fibonacci deliberately uses naive recursion on every target, not memoization.
The histogram uses maps rather than a dense counting array. Unicode traversal
counts code points, including a supplementary-plane character, not UTF-16 units.
Binary trees retain one tree while constructing and counting four transient
trees; the input is depth, not node count. Mandelbrot uses scalar binary64
arithmetic and a weighted escape-count checksum, not bitmap encoding.
N-queens counts all solutions with an ordinary earlier-row conflict scan.
Permutations use swap/backtrack enumeration with a checksum of each arrangement.
Towers uses three growable array stacks, including actual pop/append operations.
Bouncing particles mutate object fields at each step; their oracle uses a
closed-form reflected trajectory. Spectral norm recomputes implicit matrix
entries during power iteration. N-body uses a deterministic softened eight-body
system, not astronomical initial conditions. The two floating-point additions
return scaled, truncated integer checksums; their independent oracles use a
materialized matrix and all-neighbor force sums respectively. This validates
the configured inputs to the stated output resolution, not bitwise equality
of every floating-point intermediate.

Unsupported configurations remain visible: the JVM backend rejects primitive
dictionary keys, so its histogram cells contain compilation diagnostics.
The new Towers case also exposes unsupported JVM `list.pop()`, while N-body
and spectral norm expose unsupported JVM stdlib `math.sqrt()` imports. Those
configurations remain failed cells; there are no target-specific workload
rewrites or substitute timings. The math-import failure currently reports an
internal source-inspection exception, not a polished unsupported diagnostic.
Historical snapshots also show unsupported direct string iteration; the newer
base supports that operation. Failures are not timing zeros and do not prevent
the other configurations from being measured.

Each `cases/NAME/` contains:

- `case.toml`: description, two bounded sizes and representation notes.
- `workload.py`: ordinary typed Python, `kernel(size: int) -> int`.
- `reference.cjs`, `reference.rs` and `Kernel.java`: matching algorithm and input generation.
- An independent expected-result calculation in `run.oracle`, tested against
  the Python workload. Do not validate an implementation against itself.

Keep allocation and checksum work in the kernel. Backend adapters own clocks,
warmup and process lifecycle. JS compilation adds only client-reachability
decorators; it does not rewrite the algorithm. Keep builtin libraries, explicit
SIMD and parallel implementations in separately labeled future categories.

## Scope and next steps

The lab provides fifteen workloads and seven adapters, two sizes,
fresh-process and warmed-batch timing, separate RSS measurements, build time,
artifact byte counts, bounded batch calibration, warmup-drift warnings, and a
live PyJS UI. See [methodology](methodology.md)
before interpreting a speedup.

A dedicated publication machine, automated latest-stable refresh, checked
publication snapshots/history, more
workloads, and non-Linux measurement hosts remain follow-ups. The per-snapshot
lock records the tools actually used; it is not an automatic installer or
latest-version guarantee. No performance threshold is added to normal CI.

### Comparison-site coverage

This is **not a complete port** of the comparison-site catalogs. The
[Benchmarks Game](https://benchmarksgame-team.pages.debian.net/benchmarksgame/),
[Programming Language Benchmarks](https://programming-language-benchmarks.vercel.app/),
and [Are We Fast Yet?](https://github.com/smarr/are-we-fast-yet) use different
inputs, output protocols and implementation rules. Shared names identify
workload families, not interchangeable scores. The catalog check on 2026-10-28
identified these covered families and remaining gaps:

| Workload family | Coverage here | Next useful gap |
| --- | --- | --- |
| Integer loops, sorting, permutations | Sieve, matrix, heap sort, Fibonacci, permutations, N-queens | Fannkuch-redux prefix-flip workload |
| Allocation, mutation and recursion | Object traversal, binary trees, Towers, bouncing particles | Linked structures and a constraint solver |
| Floating-point computation | Mandelbrot, spectral norm, N-body | Broader numerical/application workloads |
| Text and mapping | Unicode scan, histogram | FASTA, reverse complement, k-nucleotide |
| Application/library work | Not yet measured | JSON serialization, LRU, regex, HTTP |
| Large integers and specialized math | Not yet measured | Pi/e digits and cryptographic arithmetic |

Are We Fast Yet?'s Richards, DeltaBlue, Havlak and collision-detection workloads
would add larger abstraction-heavy programs beyond these microbenchmarks.
LangArena is another breadth reference, not a parity claim. Prefer workloads
that expose a new runtime behavior; give library-backed, parallel, SIMD and
I/O workloads separate categories rather than mixing them into scalar-kernel
rankings. Each addition needs an independent oracle, matching references and
real adapter execution before its measurements are interpreted.

### Compiler optimizations and follow-ups

Local controls on 2026-10-27 identified the following bottlenecks. Both now
have compiler implementations, distinct from the original diagnostic controls
described below. The measurements are not publication rankings.

1. **JVM stack metadata prevented hot kernels from compiling.** Ordinary
   generated methods previously declared `max_stack=65535`. On JDK 27.0.1,
   HotSpot rejected kernels with `illegal oopMap register name` / `too many
   local variables` even though their actual local counts were modest.
   Changing only those class-file stack bounds to 256 in isolated copies made
   the kernels compile. Across three process forks, matrix N=64 fell from
   20.84 ms to 0.567 ms; sieve N=20000 from 3.09 ms to 0.278 ms; object traversal
   from 10.88 ms to 0.394 ms. Object timings varied substantially between forks.
   All checksums and full JVM verification passed. A hardcoded 256 is **not a
   safe fix**. The compiler now calculates stack bounds across branches,
   backedges and exception entries, using field/method descriptors and two-slot
   values. Unknown instructions and inconsistent stack heights fail explicitly.
2. **JavaScript range iteration dominated the matrix case.** On Node 26.12.1,
   replacing only the bounded positive `range` loops with equivalent `while`
   loops reduced N=64 from 13.12 ms to 0.946 ms. Removing checked indexing alone
   left it at 13.09 ms; both controls took 0.622 ms versus 0.611 ms for handwritten
   JavaScript. This points first to generator/iterator lowering, not blanket
   removal of bounds checks. Direct builtin range loops now use counted loops
   with private induction variables, single left-to-right argument evaluation,
   zero-step checks, negative steps and existing break/else handling. Assigning
   to the Python target does not change iteration. First-class ranges and other
   iterables keep their existing lowering; list bounds checks remain intact.

Evidence is in `runs/jvm-diagnosis-20261027/verified/ablation.json` and
`runs/jvm-diagnosis-20261027/javascript/ablation.json`, with source controls,
per-fork output and JIT logs alongside. The JVM control's original top-level
partial run had a metadata-parser bug and is excluded; only `verified/` is
authoritative. Diagnostic timings include instrumentation and must not replace
ordinary benchmark measurements. Both experiments validated every batch and
used three sequential randomized forks, 60 warmups and 10 samples.

Remeasure before optimizing secondary range guards or allocation costs. Keep
the native checksum-write boundary visible; the LLVM investigation below
retains that boundary and does not attribute object-allocation costs to GC.

The implemented changes were measured in `runs/optimized-20261027/results.json`
against `runs/diagnostic-baseline-20261027/results.json`, using the same tools,
three forks, 30 warmups, seven samples and bounded per-target batch calibration.
All 42 configurations validated their checksums. Separate HotSpot logs show
successful C2 compilation of all six PyJS kernel/input configurations and no
recorded benchmark compilation failures. The matrix kernel's computed stack
capacity is nine slots, not the experimental 256-slot cap.

| Workload | PyJS JVM, before → after | PyJS JavaScript, before → after |
| --- | --- | --- |
| Sieve, N=20000 | 2.830 → 0.110 ms | 1.018 → 0.138 ms |
| Matrix, N=64 | 19.212 → 0.586 ms | 13.807 → 0.900 ms |
| Objects, N=20000 | 10.485 → 0.387 ms | 0.694 → 0.206 ms |

These are exploratory process-median summaries on a shared desktop, not
performance guarantees. Batch-size and warmup warnings remain on sieve/object
measurements; object process medians also varied substantially. The two matrix
rows have no harness instability warning, which still does not certify steady
state. Open the saved snapshots to inspect all raw traces and diagnostics.

### LLVM loop and indexing investigation

Controlled builds in `runs/llvm-diagnosis-20261027/` isolate two costs:

- Compiler-private range cursors were arena allocated on every loop entry.
  Moving ordinary, non-suspending cursors to entry-block stack storage removes
  those allocations and lets LLVM promote their fields. Each lexical loop
  owns separate storage, reused on re-entry. Suspended generators retain
  persistent cursors; first-class iterator objects are unchanged.
- List/tuple access first normalized and checked the index for a catchable
  `IndexError`, then repeated normalization and bounds checking inside the
  runtime accessor. The emitter now uses the first checked position directly.
  Public runtime accessors retain their checks, and application indexing keeps
  its original exception guard. This is not unchecked array access.

The diagnostic experiment changed only cursor storage and the redundant
accessor trap, independently and together. Three sequential randomized forks
used 100 calls per batch, 10 warmups and seven samples; every checksum matched
the independent oracle. Median milliseconds per call:

| Workload | Baseline | Stack cursor only | Single check only | Both |
| --- | ---: | ---: | ---: | ---: |
| Matrix, N=64 | 1.326 | 1.100 | 0.808 | 0.600 |
| Sieve, N=20000 | 0.359 | 0.332 | 0.299 | 0.295 |
| Objects, N=20000 | 0.511 | 0.483 | 0.479 | 0.482 |

Object-process medians overlap substantially: this does not establish an
object-allocation speedup. `index-ablation.json` retains all traces and
`index_probe.py` describes the isolated IR control. The final implementation
also reuses the normalized index rather than recomputing it.

Hardware profiling was unavailable (`perf_event_paranoid=4`); no machine
security settings were changed. These conclusions come from generated and
optimized IR inspection plus controlled ablations, not hardware-counter
profiles. Broad allocation/GC tuning, bounds-check elimination and changes to
overflow semantics are not included. Regression tests exercise O0/O2,
sanitizers, signed-range limits, suspended generators, index errors, mutations
and represented element layouts.

The final implementation's ordinary snapshot is
`runs/llvm-optimized-20261027/results.json`. All 42 configurations and 126
forks validated their checksums. Tool versions and measurement policy match
`runs/optimized-20261027/results.json`; per-target calibration can select
different batch sizes. LLVM milliseconds per call:

| Workload | Before | After | Speedup |
| --- | ---: | ---: | ---: |
| Sieve, N=20000 | 0.334 | 0.277 | 1.20× |
| Matrix, N=64 | 1.222 | 0.844 | 1.45× |
| Objects, N=20000 | 0.458 | 0.448 | 1.02× |

Report these ordinary measurements separately from the isolated ablation;
they differ in implementation, batch sizes and measurement conditions. Do not
treat the object difference as a demonstrated improvement. The three larger
LLVM inputs have no harness instability warning in this snapshot; the smaller
inputs remain below the requested batch duration. Shared-desktop measurements
still need dedicated-machine confirmation before publication. RSS includes
all kernel allocations retained until the end of each batch, so different
calibrated loop counts must not be presented as a per-kernel memory comparison.

### Expanded workloads and integer mapping lookup

The pre-rebase `runs/expanded-optimized-20261027/results.json` contains all seven workloads:
94 successful target/input configurations, with every checksum validated across
282 process forks. Four JVM cells record the then-current numeric-dictionary and
string-iteration compilation boundaries (two input sizes each). All 24 separate
Java/JVM diagnostic passes completed without recorded compilation failures.
These are historical measurements on the recorded revision, not measurements
of newer merged backend features or of the rebased PR. The rebased implementation
retains managed-heap cursors for suspended native frames and the newer JVM
class writer's conservative cap for manually bounded helper methods.

The new histogram exposed LLVM's dense linear dictionary scan. Optimized IR
showed a generic equality call on every candidate key. The integer-only path
now loads the query once and compares 64-bit keys directly, with no storage
layout change. Empty mappings do not dereference the query; first-match order,
mutation behavior and non-integer/custom-key paths remain unchanged.

The fixed-batch control in `runs/integer-lookup-20261027/comparison.json` checks
that the generated modules differ **only** in `pyjs.dict.find`. It measures the
saved binaries in shuffled order, with three forks, 20 calls per batch, 30
warmups and seven samples, validating every checksum:

| Histogram input | Before | After | Speedup |
| --- | ---: | ---: | ---: |
| N=2000 | 0.279 ms | 0.257 ms | 1.09× |
| N=20000 | 2.842 ms | 2.268 ms | 1.25× |

The separate ordinary snapshots (`expanded-baseline-20261027` versus
`expanded-optimized-20261027`) measured N=20000 at 2.647 → 2.244 ms (1.18×).
Keep those calibrated results separate from the fixed-batch control. Neither
is a dedicated-machine performance guarantee.

This is a constant-factor improvement, not a hash-table implementation. The
257-key histogram still exposes linear lookup cost; scalable indexing is the
larger follow-up. Other leads are JavaScript's checked heap-sort accesses and
LLVM character-string allocation. Do not remove Python bounds checks or
compare character allocation with scalar iteration as if they were identical.
JVM Fibonacci is already close to handwritten Java in this snapshot. Preserve
these varied workloads and explicit unsupported cells as future regression
evidence instead of specializing the benchmarks around backend limitations.
