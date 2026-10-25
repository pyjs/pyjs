import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import pyjs.scaffolding as scaffolding
from pyjs.scaffolding import (
    create,
    find_template,
    template_sources,
    templates,
    version_string,
)


def run_python_tests(project: Path, *, pythonpath: str | None = None):
    env = os.environ.copy()
    if pythonpath is not None:
        env["PYTHONPATH"] = pythonpath
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=project,
        capture_output=True,
        env=env,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def run_python(project: Path, source: str):
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=project,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def run_pytest(project: Path, *args: str):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *args],
        cwd=project,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def project_files(project: Path) -> set[str]:
    return {
        path.relative_to(project).as_posix()
        for path in project.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def test_create_starter_project(tmp_path):
    project = create("hello_pyjs", tmp_path / "hello_pyjs")

    assert project_files(project) == {
        ".gitignore",
        "README.md",
        "hello_pyjs/__init__.py",
        "hello_pyjs/__main__.py",
        "hello_pyjs/hello_pyjs.py",
        "pyproject.toml",
        "tests/test_app.py",
        "tests/test_browser_app.py",
    }
    pyproject = (project / "pyproject.toml").read_text()
    config = tomllib.loads(pyproject)
    assert 'name = "hello-pyjs"' in pyproject
    assert '["hello_pyjs", "hello_pyjs.*"]' in pyproject
    assert config["project"]["version"] == "0.1.0"
    assert config["project"]["dependencies"] == [f"pyjs~={version_string()}"]
    assert config["project"]["optional-dependencies"]["test"] == [
        "pytest>=9.0",
        "ruff>=0.15.0",
    ]
    assert config["tool"]["pyjs"]["application"] == "hello_pyjs.hello_pyjs"
    application = project / "hello_pyjs" / "hello_pyjs.py"
    assert "__PYJS_" not in application.read_text()
    assert "def test_app_updates_its_status():" not in application.read_text()
    readme = (project / "README.md").read_text()
    assert "python -m hello_pyjs" in readme
    assert "pyjs serve" in readme
    assert "pyjs skill" in readme
    assert "pyjs template" in readme
    assert "ruff check ." in readme
    assert "--pyjs-target=web --pyjs-browser=managed" in readme
    launched = run_python(
        project,
        "import runpy; import pyjs.server.dev; "
        "pyjs.server.dev.serve = lambda source: print(source); "
        'runpy.run_module("hello_pyjs", run_name="__main__")',
    )
    assert Path(launched.rstrip()).resolve() == application.resolve()
    run_python_tests(project)


def test_create_starter_project_with_src_layout(tmp_path):
    project = create("example", tmp_path / "example", src_layout=True)

    assert (project / "src/example/__init__.py").is_file()
    assert (project / "src/example/__main__.py").is_file()
    assert (project / "src/example/example.py").is_file()
    assert (project / "tests/test_app.py").is_file()
    config = (project / "pyproject.toml").read_text()
    assert 'where = ["src"]' in config
    assert 'include = ["example", "example.*"]' in config
    run_python_tests(project, pythonpath="src")


def test_create_uses_application_name_as_default_destination(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    project = create("example")

    assert project == tmp_path / "example"
    assert (project / "example/example.py").is_file()


def test_create_official_example_from_installed_provider(tmp_path):
    project = create(
        "calculator_demo",
        tmp_path / "calculator-demo",
        template="pyjs_examples.calculator",
    )

    assert (project / "calculator.py").is_file()
    assert not (project / "__init__.py").exists()
    assert not (project / "__main__.py").exists()
    assert "examples/calculator/" not in (project / "README.md").read_text()
    assert not (project / "conftest.py").exists()
    config = tomllib.loads((project / "pyproject.toml").read_text())
    assert config["tool"]["setuptools"]["py-modules"] == [
        "android", "android_build", "calculator", "model",
    ]
    run_python_tests(project)


@pytest.mark.parametrize("path", ["calculator.py", "tests/test_model.py",
                                  "tests/nested/test_model.py"])
def test_template_imports_only_flatten_references_to_the_removed_package(path):
    template = find_template("pyjs_examples.calculator")
    prefix = "." * len(Path(path).parts)
    source = f"from {prefix}model import Calculator\n"
    if prefix != ".":
        source += "from .model import LocalCalculator\n"
    result = scaffolding._normalize_source(path, source.encode(), template)
    expected = "from model import Calculator\n"
    if prefix != ".":
        expected += "from .model import LocalCalculator\n"
    assert result.decode() == expected


def test_create_file_template_as_project(tmp_path):
    project = create(
        "counter_demo",
        tmp_path / "counter-demo",
        template="pyjs_examples.counter",
    )

    assert (project / "counter.py").is_file()
    assert "serve(__file__)" in (project / "counter.py").read_text()
    assert "def test_counter_updates_its_state():" in (project / "counter.py").read_text()
    assert 'py-modules = ["counter"]' in (project / "pyproject.toml").read_text()
    assert "python counter.py" in (project / "README.md").read_text()
    run_python(project, "from counter import CounterApp; assert CounterApp().count == 0")


def test_create_file_template_as_renamed_single_file(tmp_path):
    source = Path(__file__).parents[1] / "examples" / "counter.py"
    application = create(
        "my_counter",
        tmp_path,
        template="pyjs_examples.counter",
        single_file=True,
    )

    assert application.read_text() == source.read_text()
    assert "def test_counter_updates_its_state():" in application.read_text()
    run_python(tmp_path, "from my_counter import CounterApp; assert CounterApp().count == 0")
    assert "1 passed" in run_pytest(tmp_path, application.name)


def test_create_default_single_file(tmp_path):
    application = create("hello", tmp_path, single_file=True)

    assert "class App(CustomElement):" in application.read_text()
    assert '"h1",' in application.read_text()
    assert '"Hello",' in application.read_text()
    assert "__PYJS_" not in application.read_text()
    assert "serve(__file__)" in application.read_text()
    assert "def test_app_updates_its_status():" in application.read_text()
    assert project_files(tmp_path) == {"hello.py"}
    assert "1 passed" in run_pytest(tmp_path, application.name)
    assert f"{application.name}::test_app_updates_its_status" in run_pytest(
        tmp_path,
        "--collect-only",
        application.name,
        "--pyjs-target=web",
    )


def test_single_file_rejects_directory_template(tmp_path):
    with pytest.raises(ValueError, match="directory template"):
        create(
            "calculator",
            tmp_path,
            template="pyjs_examples.calculator",
            single_file=True,
        )


def test_create_requires_an_application_name():
    with pytest.raises(ValueError, match="valid Python identifiers"):
        create(".")


def test_src_layout_only_applies_to_starter_projects(tmp_path):
    with pytest.raises(ValueError, match="cannot be combined with --template"):
        create(
            "counter",
            tmp_path / "counter",
            template="pyjs_examples.counter",
            src_layout=True,
        )

    with pytest.raises(ValueError, match="cannot be combined with --single-file"):
        create("counter", tmp_path, single_file=True, src_layout=True)


def test_create_single_file_does_not_overwrite(tmp_path):
    destination = tmp_path / "counter.py"
    destination.write_text("keep me")

    with pytest.raises(FileExistsError, match="already exists"):
        create("counter", tmp_path, template="pyjs_examples.counter", single_file=True)

    assert destination.read_text() == "keep me"


def test_create_rejects_nonempty_destination(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "keep.txt").write_text("user data")

    with pytest.raises(FileExistsError, match="destination is not empty"):
        create("existing", destination)

    assert (destination / "keep.txt").read_text() == "user data"


def test_catalog_is_inferred_from_registered_packages():
    catalog = {template.name: template for template in templates()}

    assert catalog["pyjs_examples.calculator"].title == "Calculator"
    assert catalog["pyjs_examples.calculator"].description.startswith(
        "A tested universal calculator"
    )
    assert catalog["pyjs_examples.calculator"].kind == "directory"
    assert catalog["pyjs_examples.chat"].modules == (
        "chat",
        "chat_server",
        "protocol",
        "visual_test",
    )
    assert catalog["pyjs_examples.counter"].kind == "file"
    assert catalog["pyjs_examples.counter"].modules == ("counter",)
    assert "pyjs_examples.components" in catalog
    assert not (Path(scaffolding.__file__).parent / "manifest.toml").exists()
    assert not (Path(scaffolding.__file__).parent / "templates" / "samples").exists()


def test_core_has_no_hardcoded_templates(monkeypatch):
    monkeypatch.setattr(scaffolding.importlib.metadata, "entry_points", lambda **kwargs: ())

    assert templates() == ()
    with pytest.raises(ValueError, match="pip install pyjs-examples"):
        find_template("missing")


def test_template_sources_omit_generated_files_and_caches():
    sources = dict(template_sources(find_template("pyjs_examples.calculator")))

    assert "calculator.py" in sources
    assert "tests/test_calculator.py" in sources
    assert "__init__.py" not in sources
    assert "__main__.py" not in sources
    assert all("__pycache__" not in name for name in sources)
    assert all(not name.endswith(".pyc") for name in sources)


def test_inspected_directory_sources_match_created_project(tmp_path):
    template = find_template("pyjs_examples.chat")
    sources = dict(template_sources(template))
    project = create("chat_demo", tmp_path / "chat-demo", template=template.name)

    assert "from chat_server import chat_server" in sources["chat.py"]
    assert "python chat.py" in sources["README.md"]
    assert "python visual_test.py" in sources["README.md"]
    for name, content in sources.items():
        assert (project / name).is_file()
        if content is not None:
            assert (project / name).read_text(encoding="utf-8") == content


def test_template_sources_identify_binary_files():
    sources = dict(template_sources(find_template("pyjs_examples.space_invaders")))

    assert sources["tests/renders/initial_wave.png"] is None


def test_examples_distribution_maps_its_source_root_to_pyjs_examples():
    project_root = Path(__file__).parents[1]
    config = tomllib.loads((project_root / "examples" / "pyproject.toml").read_text())
    core = tomllib.loads((project_root / "pyproject.toml").read_text())

    assert config["project"]["name"] == "pyjs-examples"
    assert config["project"]["version"] == version_string()
    assert config["project"]["dependencies"] == [f"pyjs=={version_string()}"]
    assert config["project"]["entry-points"]["pyjs.templates"] == {
        "calculator": "pyjs_examples.calculator",
        "chat": "pyjs_examples.chat",
        "components": "pyjs_examples.components",
        "counter": "pyjs_examples.counter",
        "notes": "pyjs_examples.notes",
        "space_invaders": "pyjs_examples.space_invaders",
    }
    assert config["tool"]["setuptools"]["package-dir"] == {"pyjs_examples": "."}
    assert "pyjs_examples.calculator" in config["tool"]["setuptools"]["packages"]
    assert "pyjs_examples.homescreen_widget" in config["tool"]["setuptools"]["packages"]
    assert "pyjs_examples.widgets" not in config["tool"]["setuptools"]["packages"]
    assert config["tool"]["setuptools"]["package-data"][
        "pyjs_examples.homescreen_widget"
    ] == ["README.md", "res/**/*.xml"]
    assert core["project"]["entry-points"]["pytest11"] == {"pyjs": "pyjs.testing.pytest_plugin"}
    assert core["project"]["scripts"] == {"pyjs": "pyjs.cli:main"}
    assert core["project"]["optional-dependencies"]["examples"] == [
        f"pyjs-examples=={version_string()}"
    ]
    assert core["tool"]["setuptools"]["package-data"]["pyjs"] == [
        "skills/pyjs/SKILL.md",
        "testing/android_device_runtime.json",
        "testing/android_runtime.json",
        "tooling/android_manifest_runtime.json",
    ]
    assert core["tool"]["setuptools"]["package-data"]["pyjs.android"] == [
        "*.json"
    ]
