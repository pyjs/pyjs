"""Run the same target suites locally and on GitHub's isolated runners."""

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKENDS = ("native", "transpiler", "semantics", "java", "webassembly")
PYTHON_TESTS = "not pyjs_web and not pyjs_android and not pyjs_android_jvm"
TARGETS = ("core", "js", "native", "jvm", "wasm", "browser",
           "android-robolectric", "android-device")


def suites(target, shard=1, shards=1, root=ROOT):
    if not 1 <= shard <= shards or (target != "native" and shards != 1):
        raise ValueError("Only native supports sharding; require 1 <= shard <= shards")
    if target == "native":
        # Partition whole modules, retaining module/session fixtures and keeping
        # every parametrization together. No xdist/process fanout within a VM.
        files = sorted(p.relative_to(root).as_posix()
                       for p in (root / "tests/native").rglob("test_*.py"))
        selected = files[shard - 1::shards]
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
        return [[path, "-m", "pyjs_web", "--pyjs-target=web", "--pyjs-browser=managed"]
                for path in ("tests", "examples", "extras")]
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
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()
    selected = suites(args.target, args.shard, args.shards)
    artifacts = ROOT / "test-artifacts" / f"{args.target}-{args.shard}"
    artifacts.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, PYTHONUNBUFFERED="1")
    if args.target == "core":
        environment["PYJS_RUN_DOWNLOAD_TESTS"] = "1"
    failed = False
    for index, suite in enumerate(selected, 1):
        command = [sys.executable, "-m", "pytest", "-q", "-ra", "--durations=20",
                   f"--junitxml={artifacts / f'{index}.xml'}",
                   f"--pyjs-artifacts-dir={artifacts / str(index)}", *suite]
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
