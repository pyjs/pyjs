"""Run the same target suites locally and on GitHub's isolated runners."""

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKENDS = ("native", "transpiler", "semantics", "java", "webassembly")
PYTHON_TESTS = "not pyjs_web and not pyjs_android and not pyjs_android_jvm"
TARGETS = ("core", "js", "native", "jvm", "wasm", "browser",
           "android-robolectric", "android-device", "portable")


def native_shards(files, count, weights):
    # Longest measured modules first, into the least-loaded bin. Discovery is
    # authoritative: new files get a conservative estimate, never disappear
    # because a timing snapshot predates them. Keep fixtures within a module.
    bins = [[] for _ in range(count)]
    loads = [0] * count
    for name in sorted(files, key=lambda name: (-weights.get(name, 60), name)):
        index = min(range(count), key=lambda i: (loads[i], i))
        bins[index].append(name)
        loads[index] += weights.get(name, 60)
    return bins


def suites(target, shard=1, shards=1, root=ROOT):
    if not 1 <= shard <= shards or (target != "native" and shards != 1):
        raise ValueError("Only native supports sharding; require 1 <= shard <= shards")
    if target == "native":
        files = [p.relative_to(root).as_posix()
                 for p in (root / "tests/native").rglob("test_*.py")]
        weights = json.loads((ROOT / "scripts/ci_native_seconds.json").read_text())
        selected = native_shards(files, shards, weights)[shard - 1]
        if not selected:
            raise ValueError("Native shard is empty")
        return [selected]
    if target == "core":
        return [["tests", *(f"--ignore=tests/{name}" for name in BACKENDS),
                 "-m", PYTHON_TESTS],
                ["examples", "-m", PYTHON_TESTS],
                ["extras", "-m", PYTHON_TESTS]]
    if target in ("js", "jvm", "wasm"):
        paths = {"js": ["tests/transpiler", "tests/semantics"],
                 "jvm": ["tests/java"], "wasm": ["tests/webassembly"]}
        return [[*paths[target], "-m", PYTHON_TESTS]]
    if target == "browser":
        # Django test settings and the Store example must live in separate
        # processes. Do not drop Store or extras browser tests to avoid clashes.
        # Extras currently have host-side compilation tests, not marked web
        # tests. Collect them with examples so future web tests join this lane
        # without treating an empty standalone extras selection as success.
        return [[*paths, "-m", "pyjs_web", "--pyjs-target=web", "--pyjs-browser=managed"]
                for paths in (["tests"], ["examples", "extras"])]
    if target == "portable":
        # Full Linux coverage is not multiplied by OS. Exercise executed
        # language contracts and OS-sensitive tooling on Windows/macOS, then
        # browser DOM APIs. GPU rendering and Android SDK tests stay on Linux.
        return [["tests/semantics", "tests/java/test_jvm.py", "tests/java/test_classpath.py",
                 "tests/webassembly", "tests/tooling/test_command.py", "tests/tooling/test_node.py",
                 "tests/tooling/test_npm.py", "tests/tooling/test_browser.py", "tests/tooling/test_downloads.py",
                 "tests/test_cli.py", "tests/test_scaffolding.py", "tests/test_newcomer_experience.py",
                 "tests/test_dev_server.py", "tests/test_server_watch.py", "-m", PYTHON_TESTS],
                ["tests", "--ignore=tests/web/webgpu", "-m", "pyjs_web",
                 "--pyjs-target=web", "--pyjs-browser=managed"]]
    if target == "android-robolectric":
        return [[path, "-m", "pyjs_android_jvm and not pyjs_android_device",
                 "--pyjs-target=android", "--pyjs-android-runtime=robolectric"]
                for path in ("tests", "examples")]
    if target == "android-device":
        return [["tests", "-m", "pyjs_android", "--pyjs-target=android",
                 "--pyjs-android-runtime=host", "--pyjs-android-headless"],
                *[[path, "-m", "pyjs_android_jvm", "--pyjs-target=android",
                   "--pyjs-android-runtime=device", "--pyjs-android-headless"]
                  for path in ("tests", "examples")]]
    raise ValueError(f"Unknown target: {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=TARGETS)
    parser.add_argument("--shard", type=int, default=1)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=1,
                        help="Native-only process parallelism; local runs default to sequential")
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()
    if args.workers != 1 and args.target != "native":
        parser.error("Only native supports parallel workers")
    selected = suites(args.target, args.shard, args.shards)
    artifacts = ROOT / "test-artifacts" / f"{args.target}-{args.shard}"
    artifacts.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, PYTHONUNBUFFERED="1")
    if args.target in ("core", "portable"):
        environment["PYJS_RUN_DOWNLOAD_TESTS"] = "1"
    failed = False
    for index, suite in enumerate(selected, 1):
        command = [sys.executable, "-m", "pytest", "-q", "-ra", "--durations=20",
                   f"--junitxml={artifacts / f'{index}.xml'}",
                   f"--pyjs-artifacts-dir={artifacts / str(index)}", *suite]
        if "--pyjs-target=web" in suite:
            # A broken shared bundle otherwise retries daemon startup for
            # every test. Preserve useful failures without minutes of repeats.
            command.append("--maxfail=10")
        if args.target == "native":
            # Diagnose a stalled test without killing it or silently skipping
            # coverage. The job timeout is only a final backstop, not a budget.
            command.extend(("-o", "faulthandler_timeout=120"))
            if args.workers > 1 and not args.collect_only:
                command.extend(("-n", str(args.workers), "--dist", "loadfile", "--max-worker-restart=0"))
        if args.collect_only:
            command.append("--collect-only")
        print(shlex.join(command), flush=True)
        with (artifacts / f"{index}.log").open("w") as log:
            with subprocess.Popen(command, cwd=ROOT, env=environment, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
                for line in process.stdout:
                    log.write(line)
                    print(line, end="", flush=True)
                # An empty selection (pytest exit 5) is also a failure. Keep
                # running independent suites to retain their diagnostics.
                failed |= process.wait() != 0
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
