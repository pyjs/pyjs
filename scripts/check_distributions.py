"""Build every Python distribution and test installation outside the checkout."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {"pyjs", "pyjs_examples", "pyjs_extras"}

SMOKE = '''
import importlib
import importlib.resources
import sys
from pathlib import Path
from pyjs.scaffolding import templates
from pyjs.web.domx import div
from pyjs.web.ssr import render_html

for name in ("pyjs", "pyjs_examples", "pyjs_extras"):
    module = importlib.import_module(name)
    assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), module.__file__
assert render_html(div("a < b")) == "<div>a &lt; b</div>"
assert any(item.name == "pyjs_examples.calculator" for item in templates())
assert importlib.resources.files("pyjs_examples.store").joinpath("fixtures").is_dir()
print("Installed distributions verified")
'''


def distributions(directory):
    wheels = sorted(directory.glob("*.whl"))
    sources = sorted(directory.glob("*.tar.gz"))
    if ({path.name.split("-")[0] for path in wheels} != PACKAGES
            or {path.name.split("-")[0] for path in sources} != PACKAGES
            or len(wheels) != len(PACKAGES) or len(sources) != len(PACKAGES)):
        raise ValueError("Expected one wheel and source archive for every workspace package")
    return wheels


def main():
    with tempfile.TemporaryDirectory(prefix="pyjs-distributions-") as temporary:
        work = Path(temporary)
        dist = work / "dist"
        # uv's default builds wheels from the source archives, checking both.
        subprocess.run(["uv", "build", "--all-packages", "--no-build-logs", "--out-dir", str(dist)],
                       cwd=ROOT, check=True)
        wheels = distributions(dist)
        environment = work / "environment"
        subprocess.run(["uv", "venv", "--python", sys.executable, str(environment)], check=True)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run(["uv", "pip", "install", "--python", str(python),
                        *(str(path) for path in wheels)], cwd=work, check=True)
        subprocess.run(["uv", "pip", "check", "--python", str(python)], cwd=work, check=True)
        # -I ignores source/PYTHONPATH leakage; all imports must use the wheel.
        subprocess.run([str(python), "-I", "-c", SMOKE], cwd=work, check=True)
        executable = python.with_name("pyjs.exe" if os.name == "nt" else "pyjs")
        clean_env = {key: value for key, value in os.environ.items()
                     if key not in {"PYTHONPATH", "PYTHONHOME"}}
        result = subprocess.run([str(executable), "-c", "print(sum(range(10)))"],
                                cwd=work, env=clean_env, text=True, capture_output=True, check=True)
        if result.stdout.strip() != "45":
            raise AssertionError(f"Installed CLI returned {result.stdout!r}; stderr: {result.stderr}")


if __name__ == "__main__":
    main()
