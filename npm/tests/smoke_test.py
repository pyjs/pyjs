import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

NPM_ROOT = Path(__file__).resolve().parents[1]
NPM = "npm.cmd" if os.name == "nt" else "npm"


def run(command: list[str], *, cwd: Path, capture=False):
    print("+", " ".join(command))
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=capture,
    )
    if result.returncode and capture:
        print(result.stdout, end="")
        print(result.stderr, end="")
    result.check_returncode()
    return result


def pack(source: Path, destination: Path) -> Path:
    result = run(
        [NPM, "pack", str(source), "--pack-destination", str(destination), "--json"],
        cwd=NPM_ROOT,
        capture=True,
    )
    return destination / json.loads(result.stdout)[0]["filename"]


def assert_output(command: list[str], expected: str, cwd: Path):
    result = run(command, cwd=cwd, capture=True)
    actual = result.stdout.strip()
    if actual != expected:
        raise AssertionError(f"Expected {expected!r}, got {actual!r}")


def main():
    parser = argparse.ArgumentParser(description="Smoke-test the portable PyJS npm CLI.")
    parser.add_argument("target", help="runtime target, such as linux-x64")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    runtime = NPM_ROOT / "dist" / f"cli-{args.target}"
    cli_manifest = json.loads((NPM_ROOT / "cli" / "package.json").read_text())
    if not args.skip_build:
        run(
            ["python", str(NPM_ROOT / "scripts" / "build_runtime.py"), args.target],
            cwd=NPM_ROOT,
        )

    packages = NPM_ROOT / "dist" / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    runtime_manifest = json.loads((runtime / "package.json").read_text())
    runtime_archive = pack(runtime, packages)
    cli_archive = pack(NPM_ROOT / "cli", packages)

    with tempfile.TemporaryDirectory(prefix="pyjs-npm-") as temporary:
        project = Path(temporary)
        package = {
            "name": "pyjs-npm-smoke-test",
            "private": True,
            "dependencies": {
                "@pyjsdev/cli": f"file:{cli_archive}",
                runtime_manifest["name"]: f"file:{runtime_archive}",
            },
        }
        (project / "package.json").write_text(json.dumps(package, indent=2) + "\n")
        run([NPM, "install", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=project)

        executable_name = "pyjs.cmd" if os.name == "nt" else "pyjs"
        executable = project / "node_modules" / ".bin" / executable_name
        assert_output(
            [str(executable), "--version"],
            "pyjs " + cli_manifest["version"],
            project,
        )
        serve_help = run(
            [str(executable), "serve", "--help"], cwd=project, capture=True
        ).stdout
        if "application module or Python file" not in serve_help:
            raise AssertionError("The portable CLI did not expose the serve command.")
        assert_output(
            [str(executable), "-c", "print(sum(range(10)))"],
            "45",
            project,
        )
        source = run(
            [str(executable), "--src", "-c", "print((1 + 2) * 3)"],
            cwd=project,
            capture=True,
        ).stdout
        if "console.log((1 + 2) * 3);" not in source:
            raise AssertionError("The transpiled source did not contain the expected expression.")

        (project / "helper.py").write_text(
            "from pyjs import js\n\n"
            "@js\n"
            "def increment(value: int) -> int:\n"
            "    return value + 1\n"
        )
        (project / "app.py").write_text(
            "from helper import increment\n\n"
            "def main():\n"
            "    print(increment(4))\n"
        )
        assert_output([str(executable), "app.py"], "5", project)
        imported_source = run(
            [str(executable), "--src-all", "app.py"],
            cwd=project,
            capture=True,
        ).stdout
        if "function increment" not in imported_source:
            raise AssertionError("The transpiler did not include the local imported function.")

    print("PyJS npm smoke test passed.")


if __name__ == "__main__":
    main()
