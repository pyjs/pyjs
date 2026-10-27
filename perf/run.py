"""Build, validate, and measure sequentially; retain immutable run snapshots."""
import argparse
import hashlib
import json
import math
import platform
import random
import re
import shutil
import statistics
import subprocess
import sys
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from perf.harness.build import ROOT, TARGETS
from perf.harness.jit import summarize_jit
from perf.harness.process import execute

REPO = ROOT.parent
CASES = ("sieve", "matrix", "objects", "fibonacci", "heapsort", "histogram", "textscan",
         "binarytrees", "mandelbrot")
REQUIRES = {
    "cpython": ("python",), "pyjs-js": ("node",), "javascript": ("node",), "pyjs-llvm": ("clang",),
    "rust": ("rustc",), "pyjs-jvm": ("java", "javac"), "java": ("java", "javac"),
}


def oracle(case, size):
    """Independent checks, deliberately not the timed algorithms."""
    if case == "sieve":
        return sum(all(n % d for d in range(2, math.isqrt(n) + 1))
                   for n in range(2, size + 1))
    if case == "matrix":
        # Sum(A @ B) = sum_k column_sum(A, k) * row_sum(B, k).
        return sum(sum((row * size + k) % 17 for row in range(size)) *
                   sum((k * size + col) % 13 for col in range(size))
                   for k in range(size))
    if case == "objects":
        return sum(i * (i % 7) for i in range(size))
    if case == "fibonacci":
        previous, current = 0, 1
        for _ in range(size):
            previous, current = current, previous + current
        return previous
    if case == "heapsort":
        return sum((i + 1) * value for i, value in enumerate(
            sorted((i * 73 + 19) % 1009 - 504 for i in range(size))))
    if case == "histogram":
        return sum(i * 17 % 257 + 1 for i in range(size))
    if case == "textscan":
        return 10 * size
    if case == "binarytrees":
        return 5 * (2 ** (size + 1) - 1)
    if case == "mandelbrot":
        # Complex arithmetic and a bounded for-loop, independent of the
        # scalar-component while-loop in the timed implementations.
        checksum = 0
        for index in range(size * size):
            c = complex(index % size * 2.0 / size - 1.5,
                        index // size * 2.0 / size - 1.0)
            z = 0j
            count = 0
            for _ in range(50):
                if z.real * z.real + z.imag * z.imag > 4.0:
                    break
                z = z * z + c
                count += 1
            checksum += (index + 1) * count
        return checksum
    raise ValueError(case)


def expected(case, size, loops):
    return ((loops + 1) // 2 * oracle(case, size) +
            loops // 2 * oracle(case, size + 1))


def parse_samples(stdout, checksum, warmups, samples):
    lines = stdout.splitlines()
    if len(lines) != warmups + samples:
        raise ValueError(f"expected {warmups + samples} result lines, got {len(lines)}")
    result = []
    for index, line in enumerate(lines):
        phase, value, elapsed = line.split()
        if phase != ("warmup" if index < warmups else "sample"):
            raise ValueError("unexpected sample phase")
        if int(value) != checksum:
            raise ValueError(f"incorrect checksum: expected {checksum}, got {value}")
        ns = int(elapsed)
        if ns <= 0:
            raise ValueError("nonpositive duration")
        result.append({"phase": phase, "checksum": int(value), "ns": ns})
    return result


def tool(command, *, version_flag="--version"):
    path = shutil.which(command) if command else None
    if not path:
        return {"path": None, "version": None}
    # Do not resolve rustup proxy symlinks: their basename selects the tool.
    result = execute([path, version_flag], timeout=30)
    if result.returncode:
        return {"path": None, "version": None, "error": result.stderr}
    return {"path": str(Path(path).absolute()),
            "version": (result.stdout or result.stderr).strip()}


def save(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def summarize(values):
    median = statistics.median(values)
    return {"median": median, "min": min(values), "max": max(values),
            "mad": statistics.median(abs(x - median) for x in values)}


def failure(error):
    if isinstance(error, subprocess.TimeoutExpired):
        return "timeout"
    if isinstance(error, ValueError):
        return "incorrect"
    return "failed"


def calibrate(command, case, size, *, loops, target_ms, max_loops, warmups, timeout):
    """Choose bounded per-configuration batches; keep every pilot checksum/trace."""
    traces = []
    if target_ms == 0:
        return loops, traces
    for _ in range(6):
        count = min(warmups, 10)
        pilot = execute(command + [str(size), str(loops), str(count), "3"], timeout=timeout)
        if pilot.returncode:
            raise RuntimeError(pilot.stderr or f"exit {pilot.returncode}")
        samples = parse_samples(pilot.stdout, expected(case, size, loops), count, 3)
        elapsed = statistics.median(s["ns"] for s in samples if s["phase"] == "sample")
        traces.append({"loops": loops, "samples": samples})
        if elapsed >= target_ms * 1e6 or loops >= max_loops:
            break
        loops = min(max_loops, max(loops + 1, math.ceil(loops * min(10, target_ms * 1e6 / elapsed))))
    # Do not claim the next, unmeasured batch size if the attempt bound was hit.
    return traces[-1]["loops"], traces


def warmup_drift(forks):
    for fork in forks:
        warm = [s["ns"] for s in fork if s["phase"] == "warmup"]
        measured = [s["ns"] for s in fork if s["phase"] == "sample"]
        if len(warm) < 3:
            return "Fewer than three warmup batches: convergence is unassessed."
        before, after = statistics.median(warm[-3:]), statistics.median(measured[:3])
        if max(before, after) > min(before, after) * 1.2:
            return "Warmup tail and first measured batches differ by more than 20%; increase warmup."
    return None


def run(args):
    if not sys.platform.startswith("linux"):
        raise SystemExit("The initial measurement host is Linux; other hosts are not validated.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    tools = {name: tool(getattr(args, name), version_flag="-version" if name == "javap" else "--version")
             for name in ("python", "node", "clang", "rustc", "java", "javac", "javap")}
    save(output / "toolchains.lock.json", tools)
    version_policy = json.loads((ROOT / "toolchains.lock.json").read_text())
    revision = execute(["git", "rev-parse", "HEAD"], cwd=REPO).stdout.strip()
    dirty = bool(execute(["git", "status", "--porcelain"], cwd=REPO).stdout)
    sources = {str(p.relative_to(ROOT)): p.read_text()
               for p in sorted(ROOT.rglob("*"))
               if p.is_file() and p.suffix in {".py", ".rs", ".java", ".c", ".cjs", ".toml", ".css", ".md"}
               and not set(p.relative_to(ROOT).parts) & {"runs", "build", "site", "__pycache__"}}
    source_hash = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    result = {
        "schema": 1, "created": datetime.now(UTC).isoformat(), "complete": False,
        "label": args.label, "revision": revision, "dirty": dirty,
        "source_sha256": source_hash, "sources": sources, "tools": tools,
        "version_policy": version_policy,
        "compiler_python": sys.version, "platform": platform.platform(),
        "machine": platform.machine(), "cpu": platform.processor(),
        "policy": {"forks": args.forks, "warmups": args.warmups, "samples": args.samples,
                   "loops": args.loops, "min_batch_ms": args.min_batch_ms, "max_loops": args.max_loops,
                   "seed": args.seed, "timeout": args.timeout,
                   "jvm_diagnostics": args.jvm_diagnostics},
        "warnings": ["Local exploratory measurements, not a dedicated-machine ranking.",
                     "Warmed batches are not a claim of JIT steady state; inspect warmup traces.",
                     "Latest versions are not auto-selected. Exact executable versions are recorded."],
        "rows": [],
    }
    for name, version in version_policy["versions"].items():
        actual = tools[name]["version"] or "unavailable"
        if not re.search(r"(?<![\d.])" + re.escape(version) + r"(?![\d.])", actual):
            result["warnings"].append(f"{name} differs from the checked version {version}: {actual}")
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        result["cpu"] = next((line.split(":", 1)[1].strip() for line in cpuinfo.read_text().splitlines()
                              if line.startswith("model name")), result["cpu"])
    save(output / "results.json", result)
    built = {}
    for case in args.cases:
        metadata = tomllib.loads((ROOT / "cases" / case / "case.toml").read_text())
        sizes = metadata["sizes"][:1] if args.small else metadata["sizes"]
        for target in args.targets:
            directory = output / "build" / case / target
            rows = [{"case": case, "target": target, "size": size, "metadata": metadata,
                     "status": "pending", "forks": [], "startup_seconds": [], "peak_rss_kib": None}
                    for size in sizes]
            result["rows"].extend(rows)
            missing = [name for name in REQUIRES[target] if not tools[name]["path"]]
            try:
                if missing:
                    for row in rows:
                        row.update(status="unavailable", error="Missing tool: " + ", ".join(missing))
                    continue
                print(f"build {case}/{target}", flush=True)
                started = time.perf_counter()
                build_result = execute([sys.executable, "-m", "perf.harness.build", case, target,
                                        directory, output / "toolchains.lock.json"],
                                       timeout=args.build_timeout, cwd=REPO)
                elapsed = time.perf_counter() - started
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "compiler.log").write_text(build_result.stdout + build_result.stderr)
                if build_result.returncode:
                    for row in rows:
                        row.update(status="compile-error", error=build_result.stderr[-8000:])
                    continue
                build = json.loads((directory / "build.json").read_text())
                artifacts = {str(p.relative_to(output)): p.stat().st_size
                             for p in directory.rglob("*") if p.is_file()}
                built[case, target] = build["command"]
                for row in rows:
                    row.update(build_seconds=elapsed, command=build["command"],
                               build_commands=build["build_commands"], artifacts=artifacts)
                    # Correctness before timing: size, alternating size, and edge cases.
                    for size in sorted({1, 2, row["size"], row["size"] + 1}):
                        check = execute(build["command"] + [str(size), "1", "0", "1"], timeout=args.timeout)
                        if check.returncode:
                            raise RuntimeError(check.stderr or f"exit {check.returncode}")
                        parse_samples(check.stdout, expected(case, size, 1), 0, 1)
                    row["status"] = "validated"
            except Exception as error:
                for row in rows:
                    row.update(status=failure(error), error=str(error))
            finally:
                save(output / "results.json", result)

    for row in result["rows"]:
        if row["status"] != "validated":
            continue
        try:
            row["loops"], row["calibration"] = calibrate(
                row["command"], row["case"], row["size"], loops=args.loops,
                target_ms=args.min_batch_ms, max_loops=args.max_loops,
                warmups=args.warmups, timeout=args.timeout)
        except Exception as error:
            row.update(status=failure(error), error="Calibration: " + str(error))
        finally:
            save(output / "results.json", result)

    rng = random.Random(args.seed)
    for fork in range(args.forks):
        jobs = [row for row in result["rows"] if row["status"] in {"validated", "ok"}]
        rng.shuffle(jobs)
        for row in jobs:
            case, target, size = row["case"], row["target"], row["size"]
            print(f"measure {case}/{target}/{size} fork {fork + 1}", flush=True)
            command = built[case, target]
            log = output / "build" / case / target / f"{size}-fork-{fork}.log"
            try:
                start = time.perf_counter()
                cold = execute(command + [str(size), "1", "0", "1"], timeout=args.timeout)
                wall = time.perf_counter() - start
                if cold.returncode:
                    raise RuntimeError(cold.stderr or f"exit {cold.returncode}")
                parse_samples(cold.stdout, expected(case, size, 1), 0, 1)
                row["startup_seconds"].append(wall)
                warm = execute(command + [str(size), str(row["loops"]), str(args.warmups), str(args.samples)],
                               timeout=args.timeout)
                log.write_text(warm.stdout + warm.stderr)
                if warm.returncode:
                    raise RuntimeError(warm.stderr or f"exit {warm.returncode}")
                samples = parse_samples(warm.stdout, expected(case, size, row["loops"]),
                                        args.warmups, args.samples)
                row["forks"].append(samples)
                row["status"] = "ok"
            except Exception as error:
                row.update(status=failure(error), error=str(error))
            finally:
                save(output / "results.json", result)

    for row in result["rows"]:
        if row["status"] != "ok":
            continue
        # Aggregate process medians, not pseudo-independent within-process samples.
        medians = [statistics.median(s["ns"] / row["loops"] / 1e9
                                    for s in fork if s["phase"] == "sample") for fork in row["forks"]]
        row["warm_seconds"] = summarize(medians)
        row["startup"] = summarize(row["startup_seconds"])
        row["warnings"] = []
        if row["warm_seconds"]["median"] * row["loops"] < max(10, args.min_batch_ms) / 1000:
            row["warnings"].append("Batch below requested duration; increase the bounded loop budget for publication.")
        if warning := warmup_drift(row["forks"]):
            row["warnings"].append(warning)
        if args.forks < 3:
            row["warnings"].append("Fewer than three process forks: smoke evidence only.")
        if row["warm_seconds"]["max"] > row["warm_seconds"]["min"] * 1.2:
            row["warnings"].append("Process medians vary by more than 20%.")
        if Path("/usr/bin/time").exists():
            memory = output / "build" / row["case"] / row["target"] / f'{row["size"]}-rss.txt'
            try:
                measured = execute(["/usr/bin/time", "-f", "%M", "-o", memory,
                                    *row["command"], str(row["size"]), str(row["loops"]),
                                    str(args.warmups), str(args.samples)], timeout=args.timeout)
                if measured.returncode:
                    raise RuntimeError(measured.stderr)
                parse_samples(measured.stdout, expected(row["case"], row["size"], row["loops"]),
                              args.warmups, args.samples)
                row["peak_rss_kib"] = int(memory.read_text().strip())
            except Exception as error:
                row["warnings"].append("Separate RSS pass unavailable: " + str(error))
        if args.jvm_diagnostics and row["target"] in {"pyjs-jvm", "java"}:
            directory = output / "build" / row["case"] / row["target"]
            trace = directory / f'{row["size"]}-jit.xml'
            log = directory / f'{row["size"]}-jit.log'
            try:
                command = row["command"]
                flags = ["-XX:+UnlockDiagnosticVMOptions", "-XX:+LogCompilation", f"-XX:LogFile={trace}"]
                diagnostic = execute([command[0], *flags, *command[1:], str(row["size"]),
                                      str(row["loops"]), str(args.warmups), str(args.samples)], timeout=args.timeout)
                log.write_text(diagnostic.stdout + diagnostic.stderr)
                if diagnostic.returncode:
                    raise RuntimeError(diagnostic.stderr or f"exit {diagnostic.returncode}")
                parse_samples(diagnostic.stdout, expected(row["case"], row["size"], row["loops"]),
                              args.warmups, args.samples)
                row["jvm_diagnostics"] = summarize_jit(trace)
                row["jvm_diagnostics"]["command"] = [command[0], *flags, *command[1:], str(row["size"]),
                                                    str(row["loops"]), str(args.warmups), str(args.samples)]
                if row["jvm_diagnostics"]["failures"]:
                    row["warnings"].append("HotSpot rejected benchmark JIT compilation in the diagnostic pass; inspect compiler failures.")
            except Exception as error:
                row["jvm_diagnostics"] = {"status": "unavailable", "error": str(error)}
                row["warnings"].append("Separate JVM diagnostic pass unavailable: " + str(error))
            for artifact in (trace, log):
                if artifact.is_file():
                    row["artifacts"][str(artifact.relative_to(output))] = artifact.stat().st_size
        save(output / "results.json", result)
    result["complete"] = True
    save(output / "results.json", result)
    print(f"Results: {output / 'results.json'}\nView: uv run pyjs serve perf.app:create_app --open /perf/", flush=True)
    return 0 if all(row["status"] == "ok" for row in result["rows"]) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New snapshot directory (never overwritten)")
    parser.add_argument("--label", default="Local exploratory run")
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--targets", nargs="+", choices=TARGETS, default=list(TARGETS))
    parser.add_argument("--small", action="store_true", help="Only the smaller input for each workload")
    parser.add_argument("--jvm-diagnostics", action="store_true",
                        help="separate checksum-validated HotSpot compilation log pass; not included in timings")
    for name, default in (("forks", 3), ("samples", 5), ("warmups", 20), ("loops", 5),
                          ("timeout", 30), ("build-timeout", 180)):
        parser.add_argument("--" + name, type=int, default=default)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--min-batch-ms", type=float, default=50, help="calibration target; 0 disables calibration")
    parser.add_argument("--max-loops", type=int, default=1000, help="bounded calibration ceiling (at most 1000)")
    for name, default in (("python", sys.executable), ("node", "node"), ("java", "java"),
                          ("javac", "javac"), ("javap", "javap"), ("rustc", "rustc"), ("clang", "clang")):
        parser.add_argument("--" + name, default=default)
    args = parser.parse_args()
    if any(getattr(args, name) < 1 for name in ("forks", "samples", "loops", "timeout", "build_timeout")) or args.warmups < 0:
        parser.error("counts and timeouts must be positive; warmups may be zero")
    if not 1 <= args.loops <= args.max_loops <= 1000:
        parser.error("require 1 <= loops <= max-loops <= 1000 to bound per-batch allocation")
    if not math.isfinite(args.min_batch_ms) or not 0 <= args.min_batch_ms <= 1000:
        parser.error("min-batch-ms must be finite and between 0 and 1000")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
