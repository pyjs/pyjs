# Measurement contract

## Compare implementations, not language names

Four configurations share the same Python kernel byte for byte. JavaScript, Rust and Java
use the same algorithm, deterministic input and checksum. Representation
differences are disclosed per case: Java primitive arrays versus Python lists,
Rust individually boxed records versus managed objects, and different memory
management policies. These are comparable workloads, not identical machine
operations. No handwritten backend implementation replaces a Python kernel.
The JavaScript reference uses ordinary arrays and the same Node executable as
PyJS JavaScript; it introduces no typed-array, SIMD or library shortcut.

Integer inputs, intermediates and checksums in the configured cases remain
within JavaScript's exact integer range and signed 64-bit limits. Mandelbrot
uses binary64 real/imaginary components with identical operation order and no
fast-math. Its integer escape-count checksum must match exactly; no floating
tolerance conceals a changed branch. No library acceleration or user-level
parallelism is used. No GC is disabled; JVM/V8 may use runtime threads.

Before measuring, every target is checked at edge inputs 1 and 2, N, and N+1.
An independent trial-division oracle checks the sieve. A column/row sum identity
checks the matrix result. An arithmetic sum checks object traversal. Iterative
Fibonacci checks the recursive implementation; Python's library sort checks
heap sort; a direct stream sum checks dictionary counting without constructing
a dictionary; a known per-pattern score checks Unicode scanning. A closed-form
node count checks binary trees; a separate CPython complex-arithmetic loop
checks Mandelbrot's scalar implementation. Every
warmup and sample checksum is also checked. Wrong output, malformed output,
timeouts and compilation errors never become timings.

The histogram's container implementations are intentionally disclosed: LLVM
currently uses a dense linear key scan, while the references use hash maps.
Optimizing integer comparison does not turn that scan into a hash table.
Java/Rust text references iterate scalar values, whereas Python/JavaScript
and PyJS LLVM expose character strings; character allocation costs differ.

## Timed boundaries

**Fresh process** starts a prebuilt program, performs one kernel invocation,
prints its checksum and timing record, and exits. The Python coordinator's
monotonic clock includes process launch, output capture and teardown.
Filesystem caches are not cleared: this is not a cold-cache measurement.

**Warmed batch** runs multiple kernel calls in an already-started process,
alternating N and N+1, and returns their checksum as a decimal string.
Per-process warmup precedes samples. Allocation, initialization and final
checksum calculation are included. Driver printing happens after timing.
The displayed value is the median of process medians, divided by calls per
batch, not the fastest sample. Raw warmup and measurement traces remain visible.

Native LLVM currently exposes a descriptor-oriented library ABI. A small
compiled C driver calls it directly: there is no CPython or ctypes in the
measured process. Its timing includes arena lifecycle, exception checks and
one checksum write to a temporary file per batch. Reading/printing that value
is outside the timed interval. Other adapters return a string without that
write. This asymmetry is disclosed, not corrected using an estimated overhead.
The native GC heap remains alive across batches and is destroyed at exit.

Rust uses release optimization (-O), ordinary bounds checks, and black_box on
runtime kernel input to discourage hoisting. LLVM uses Clang -O2, without
fast-math or CPU-specific flags. Java uses javac defaults and JVM defaults.
Python's GC remains enabled (this harness does not use timeit's GC suppression).
Source and generated artifacts allow investigation of unexpected optimizations.

**Memory** is a separate validated GNU time run of the same warmed command.
Peak RSS includes interpreter/VM baseline, generated runtime and all batches;
it is not retained heap size or bytes allocated per operation.

**JVM diagnostics**, when requested, run separately with HotSpot compilation
logging and the same input/batch policy. Checksums are validated, but instrumented
times are excluded from all benchmark summaries. Failure records and successfully
compiled benchmark methods are reported together: one failed attempt does not
prove that all compilation tiers failed, and absence of failures does not prove
compilation or convergence. These flags are HotSpot-specific; other VMs can
retain valid timing results while reporting diagnostic unavailability.

**Build time** is one clean build in a fresh subprocess, including Python
compiler import, analysis/emission and adapter compilation. Dependencies and
tool downloads are excluded. CPython's preparation is a file copy, not native
compilation. Artifact byte counts list files individually: do not compare a
standalone binary with a class file without accounting for its required VM.

## Noise, warmup and reproducibility

Run serially on an otherwise idle dedicated machine. Record CPU, OS, compiler
revision, source hashes, versions, flags and all commands. Do not mix machines
in one comparative chart or compare absolute timings across historical machines.
Use latest stable releases when creating a publication snapshot, pin them, and
retain older snapshots when refreshing versions.

Do not assume a fixed warmup count proves steady state. Inspect the traces and
increase warmup where needed; label unstable results instead of selecting a
favorable measurement window. Separate pilot processes select a per-target/input
batch size toward 50 ms, with at most six attempts and 1000 calls per batch.
Pilot checksums and timings are retained but excluded from measured summaries.
The selected loop count is reused for all measured forks and the separate RSS
pass. Faster targets may execute more calls per batch, affecting allocation/GC
pressure; use `--min-batch-ms 0` for an explicit fixed-count comparison.

Batches below the requested duration (or 10 ms minimum), fewer than three forks,
and process medians spanning over 20% are flagged. Fewer than three warmup batches
leave convergence unassessed. A difference over 20% between the median of the
last three warmups and first three samples adds a drift warning. These checks do not certify
stability. No confidence interval is claimed from two or three samples.

For publication, repeat the experiment with more forks and input sizes, inspect
generated code, and reproduce surprising ratios. The initial local snapshots
are exploratory, not headline performance claims. CI verifies harness behavior
and correctness, not machine-dependent speed thresholds.

## Inspiration

- [Are We Fast Yet?](https://github.com/smarr/are-we-fast-yet): comparable
  algorithms and compiler effectiveness.
- [Programming Language Benchmarks](https://programming-language-benchmarks.vercel.app/):
  source-first comparisons and generated result pages.
- [LangArena](https://kostya.github.io/LangArena/): varied workloads and explicit
  runtime, memory and compilation dimensions.
- [pyperf](https://pyperf.readthedocs.io/en/latest/run_benchmark.html):
  worker processes, raw samples, instability and warmup cautions.

The initial case implementations are original, not copied submissions.
