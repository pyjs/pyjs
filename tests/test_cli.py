import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import pyjs.cli as cli
from pyjs.cli import main
from pyjs.scaffolding import version_string
from pyjs.testing.capture import CaptureResult
from pyjs.tooling.npm import NpmImport, NpmPackage


def test_template_lists_machine_readable_catalog(capsys):
    assert main(["template", "--json"]) == 0

    catalog = json.loads(capsys.readouterr().out)
    names = {template["name"] for template in catalog}

    assert "pyjs_examples.calculator" in names
    assert "pyjs_examples.components" in names
    assert (
        next(
            template["kind"] for template in catalog if template["name"] == "pyjs_examples.counter"
        )
        == "file"
    )


def test_template_identifies_file_and_directory_sources(capsys):
    assert main(["template"]) == 0

    output = capsys.readouterr().out
    assert "Type" in output
    rows = [line.split() for line in output.splitlines()]
    assert ["pyjs_examples.counter", "file"] in [row[:2] for row in rows]
    assert ["pyjs_examples.calculator", "dir"] in [row[:2] for row in rows]
    assert "pyjs_examples.components" in output
    assert "comprehensive installed applications" in output


def test_template_suggests_official_examples_when_catalog_is_empty(monkeypatch, capsys):
    monkeypatch.setattr(cli, "templates", lambda: ())

    assert main(["template"]) == 0

    output = capsys.readouterr().out
    assert "No PyJS templates are installed." in output
    assert "python -m pip install pyjs-examples" in output


def test_template_descriptions_wrap_within_the_terminal_width(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.shutil,
        "get_terminal_size",
        lambda fallback=(80, 24): os.terminal_size((72, 24)),
    )

    assert main(["template"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert all(len(line) <= 72 for line in lines)
    description_column = lines[0].index("Description")
    assert any(line.startswith(" " * description_column) and line.strip() for line in lines[1:])


def test_template_prints_file_source(capsys):
    assert main(["template", "pyjs_examples.counter"]) == 0

    output = capsys.readouterr().out
    assert output.startswith("===== counter.py =====\n")
    assert "class CounterApp(CustomElement):" in output
    assert "def test_counter_updates_its_state():" in output


def test_template_prints_directory_sources_in_order(capsys):
    assert main(["template", "pyjs_examples.calculator"]) == 0

    output = capsys.readouterr().out
    headers = [
        line.removeprefix("===== ").removesuffix(" =====")
        for line in output.splitlines()
        if line.startswith("===== ")
    ]
    assert headers == sorted(headers)
    assert "README.md" in headers
    assert "calculator.py" in headers
    assert "tests/test_calculator.py" in headers
    assert "class CalculatorApp(Widget):" in output


@pytest.mark.parametrize(
    ("template", "module", "expected"),
    [
        ("pyjs_examples.counter", "counter", "export class CounterApp"),
        ("pyjs_examples.calculator", "calculator", "export class CalculatorApp"),
        ("pyjs_examples.chat", "chat", "export class ChatApp"),
    ],
)
def test_template_prints_transpiled_entry_source(template, module, expected, capsys):
    assert main(["template", template, "--src"]) == 0

    output = capsys.readouterr().out
    assert output.startswith(f"===== {module}.js =====\n")
    assert expected in output
    assert "const modules = new Map()" not in output


def test_template_source_requires_a_name(capsys):
    with pytest.raises(SystemExit):
        main(["template", "--src"])

    assert "--src requires a template name" in capsys.readouterr().err


def test_npm_sync_installs_only_reachable_exact_dependencies(
    tmp_path,
    monkeypatch,
    capsys,
):
    def entry_point():
        pass

    analyzed = SimpleNamespace()
    monkeypatch.setattr(
        cli.importlib,
        "import_module",
        lambda name: SimpleNamespace(main=entry_point),
    )
    monkeypatch.setattr(
        cli,
        "prepare_bundle",
        lambda *args, **kwargs: (
            {"app": "", "example.vendor": ""},
            analyzed,
            set(),
        ),
    )
    monkeypatch.setattr(
        cli,
        "collect_npm_packages",
        lambda modules: (NpmPackage("yjs", "13.6.27"),),
    )
    imports = (NpmImport(NpmPackage("yjs", "13.6.27"), "$yjs"),)
    monkeypatch.setattr(cli, "collect_npm_imports", lambda modules: imports)
    released = []
    monkeypatch.setattr(cli, "release_compilation", released.append)

    synchronized = []

    class Project:
        def __init__(self, directory):
            self.directory = directory

        def sync(self, packages, package_imports):
            synchronized.append((self.directory, packages, package_imports))
            return SimpleNamespace(
                directory=self.directory,
                packages=packages,
                vendor=self.directory / "pyjs-vendor.js",
            )

    monkeypatch.setattr(cli, "ManagedNpmProject", Project)
    destination = tmp_path / "managed"

    assert main(
        ["npm", "sync", "sample", "--directory", str(destination)]
    ) == 0

    packages = (NpmPackage("yjs", "13.6.27"),)
    assert synchronized == [(destination, packages, imports)]
    assert released == [analyzed]
    assert capsys.readouterr().out == (
        f"Synchronized 1 npm package in {destination}\n"
        "  yjs@13.6.27\n"
        f"Built browser module at {destination / 'pyjs-vendor.js'}\n"
    )


def test_npm_sync_can_emit_machine_readable_results(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "_entry_point",
        lambda target, parser: lambda: None,
    )
    analyzed = SimpleNamespace()
    monkeypatch.setattr(
        cli,
        "prepare_bundle",
        lambda *args, **kwargs: ({"app": ""}, analyzed, set()),
    )
    monkeypatch.setattr(cli, "collect_npm_packages", lambda modules: ())
    monkeypatch.setattr(cli, "collect_npm_imports", lambda modules: ())
    monkeypatch.setattr(cli, "release_compilation", lambda value: None)

    class Project:
        def __init__(self, directory):
            self.directory = directory

        def sync(self, packages, package_imports):
            return SimpleNamespace(
                directory=self.directory,
                packages=packages,
                vendor=None,
            )

    monkeypatch.setattr(cli, "ManagedNpmProject", Project)
    destination = tmp_path / "managed"

    assert main(
        [
            "npm",
            "sync",
            "sample",
            "--directory",
            str(destination),
            "--json",
        ]
    ) == 0

    assert json.loads(capsys.readouterr().out) == {
        "directory": str(destination),
        "packages": {},
        "vendor": None,
    }


def test_template_rejects_json_with_source_name(capsys):
    with pytest.raises(SystemExit):
        main(["template", "pyjs_examples.counter", "--json"])

    assert "--json cannot be combined" in capsys.readouterr().err


def test_skill_prints_version_matched_agent_instructions(capsys):
    assert main(["skill"]) == 0

    output = capsys.readouterr().out
    assert output.startswith("---\nname: pyjs\n")
    assert "pyjs template NAME" in output
    assert "pyjs --version" in output
    assert "github.com/pyjs/pyjs/" in output
    assert "python -m pytest -q app.py --pyjs-target=web" in output


def test_version_prints_installed_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"pyjs {version_string()}\n"


def test_command_string_runs_generated_javascript(monkeypatch, capsys):
    node = cli.Node(executable="test-node")
    monkeypatch.setattr(cli, "Node", lambda: node)
    monkeypatch.setattr(
        node,
        "run_javascript",
        lambda source: subprocess.CompletedProcess([], 0, "3\n", ""),
    )

    assert main(["-c", "print(1 + 2)"]) == 0

    assert capsys.readouterr().out == "3\n"


def test_source_mode_prints_javascript_without_running_node(monkeypatch, capsys):
    monkeypatch.setattr(cli, "Node", lambda: pytest.fail("Node should not run"))

    assert main(["--src", "-c", "print('hello')"]) == 0

    output = capsys.readouterr().out
    assert "console.log('hello')" in output
    assert "const modules = new Map()" not in output
    assert "===== " not in output


def test_command_string_supports_module_imports(capsys):
    assert (
        main(
            [
                "--src",
                "-c",
                'from pyjs.web.events import Event; event = Event("ready"); print(event.type)',
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "var event = new Event('ready')" in output
    assert "console.log(event.type)" in output


def test_command_string_formats_compilation_diagnostics(capsys):
    assert main(["-c", "print(missing)"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        '  File "<string>", line 1\n'
        "    print(missing)\n"
        "          ^^^^^^^\n"
        "pyjs.CompilationError: Name 'missing' is not defined [PYJS1001]\n"
    )


def test_file_input_formats_compilation_diagnostics(tmp_path, capsys):
    source = tmp_path / "broken.py"
    source.write_text(
        "def main():\n    print(missing)\n",
        encoding="utf-8",
    )

    assert main([str(source)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f'  File "{source}", line 2\n'
        "    print(missing)\n"
        "          ^^^^^^^\n"
        "pyjs.CompilationError: Name 'missing' is not defined [PYJS1001]\n"
    )


def test_module_input_formats_compilation_diagnostics(
    tmp_path,
    monkeypatch,
    capsys,
):
    source = tmp_path / "broken_module.py"
    source.write_text(
        "def main():\n    print(missing)\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(tmp_path)
    try:
        assert main(["-m", "broken_module"]) == 2
    finally:
        sys.modules.pop("broken_module", None)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f'  File "{source}", line 2\n'
        "    print(missing)\n"
        "          ^^^^^^^\n"
        "pyjs.CompilationError: Name 'missing' is not defined [PYJS1001]\n"
    )


def test_command_string_serializes_compilation_diagnostics(capsys):
    assert main(["--json", "-c", 'print("é", missing)']) == 2

    assert json.loads(capsys.readouterr().out) == {
        "error": {
            "code": "PYJS1001",
            "severity": "error",
            "message": "Name 'missing' is not defined",
            "primary": {
                "file": "<string>",
                "start": {"line": 0, "column": 11},
                "end": {"line": 0, "column": 18},
                "message": None,
            },
            "secondary": [],
            "notes": [],
            "help": [],
        }
    }


def test_command_string_formats_python_syntax_errors_the_same_way(capsys):
    assert main(["-c", "print("]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        '  File "<string>", line 1\n'
        "    print(\n"
        "         ^\n"
        "SyntaxError: '(' was never closed\n"
    )


def test_verbose_compilation_error_includes_traceback(monkeypatch, capsys):
    def fail(program):
        raise ValueError("bad source")

    monkeypatch.setattr(cli, "_compile_direct", fail)

    assert main(["-v", "-c", "bad_source()"]) == 2

    error = capsys.readouterr().err
    assert "Traceback (most recent call last)" in error
    assert "ValueError: bad source" in error


def test_verbose_public_diagnostic_includes_compiler_traceback(capsys):
    assert main(["-v", "-c", "print(missing)"]) == 2

    error = capsys.readouterr().err
    assert error.startswith(
        '  File "<string>", line 1\n'
        "    print(missing)\n"
        "          ^^^^^^^\n"
        "pyjs.CompilationError: Name 'missing' is not defined [PYJS1001]\n"
        "Traceback (most recent call last):\n"
    )
    assert "pyjs/analysis/analyzer.py" in error.replace("\\", "/")


def test_verbose_json_public_diagnostic_includes_compiler_traceback(capsys):
    assert main(["--json", "-v", "-c", "print(missing)"]) == 2

    error = json.loads(capsys.readouterr().out)["error"]
    traceback_text = error.pop("traceback")
    assert error == {
        "code": "PYJS1001",
        "severity": "error",
        "message": "Name 'missing' is not defined",
        "primary": {
            "file": "<string>",
            "start": {"line": 0, "column": 6},
            "end": {"line": 0, "column": 13},
            "message": None,
        },
        "secondary": [],
        "notes": [],
        "help": [],
    }
    assert "pyjs/analysis/analyzer.py" in traceback_text.replace("\\", "/")


def test_internal_compilation_error_does_not_print_argument_usage(monkeypatch, capsys):
    def fail(program):
        raise ValueError("bad source")

    monkeypatch.setattr(cli, "_compile_direct", fail)

    assert main(["-c", "bad_source()"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "pyjs: error: bad source\n"


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("verbose", [0, 1])
def test_diagnostics_keep_structured_and_exception_notes_once(capsys, as_json, verbose):
    from dataclasses import replace

    with pytest.raises(cli.CompilationError) as caught:
        cli.compile_source("print(missing)")
    diagnostic = caught.value.diagnostic
    error = cli.CompilationError(replace(
        diagnostic, notes=("original diagnostic context",), help=("try this",),
        secondary=(replace(diagnostic.primary, message="related location"),),
    ))
    error.add_note("analysis output")
    assert cli._compilation_error(error, SimpleNamespace(json=as_json, v=verbose)) == 2
    captured = capsys.readouterr()
    if as_json:
        details = json.loads(captured.out)["error"]
        assert details["notes"] == ["original diagnostic context", "analysis output"]
        assert details["help"] == ["try this"]
        assert details["secondary"][0]["message"] == "related location"
        assert captured.err == ""
    else:
        assert captured.out == ""
        for text in ("original diagnostic context", "analysis output", "try this", "related location"):
            assert captured.err.count(text) == 1


def test_internal_compilation_error_never_has_an_empty_message(
    monkeypatch,
    capsys,
):
    def fail(program):
        raise AssertionError

    monkeypatch.setattr(cli, "_compile_direct", fail)

    assert main(["-c", "bad_source()"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "pyjs: error: AssertionError\n"


def test_json_compilation_error_is_structured(monkeypatch, capsys):
    def fail(program):
        raise ValueError("bad source")

    monkeypatch.setattr(cli, "_compile_direct", fail)

    assert main(["--json", "-c", "bad_source()"]) == 2

    assert json.loads(capsys.readouterr().out) == {
        "error": {"type": "ValueError", "message": "bad source"}
    }


def test_verbose_mode_labels_source_and_node_output(monkeypatch, capsys):
    node = cli.Node(executable="test-node")
    monkeypatch.setattr(cli, "Node", lambda: node)
    monkeypatch.setattr(
        node,
        "run_javascript",
        lambda source: subprocess.CompletedProcess([], 0, "hello\n", ""),
    )

    assert main(["-v", "-c", "print('hello')"]) == 0

    output = capsys.readouterr().out
    assert "===== .js =====" in output
    assert "const modules = new Map()" not in output
    assert f"===== node v{node.version} output =====" in output
    assert output.endswith("hello\n")


def test_direct_json_contains_runtime_result(monkeypatch, capsys):
    node = cli.Node(executable="test-node")
    monkeypatch.setattr(cli, "Node", lambda: node)
    monkeypatch.setattr(
        node,
        "run_javascript",
        lambda source: subprocess.CompletedProcess([], 0, "hello\n", ""),
    )

    assert main(["--json", "-v", "-c", "print('hello')"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["input"] == "<string>"
    assert result["node"] == {
        "version": node.version,
        "path": str(node.executable),
        "selection": "argument",
    }
    assert result["stdout"] == "hello\n"
    assert "console.log('hello')" in result["sources"][".js"]
    assert "javascript" not in result


def test_browser_module_node_failure_has_an_actionable_hint(monkeypatch, capsys):
    node = cli.Node(executable="test-node")
    monkeypatch.setattr(cli, "Node", lambda: node)
    monkeypatch.setattr(
        node,
        "run_javascript",
        lambda source: subprocess.CompletedProcess(
            [],
            1,
            "",
            "ReferenceError: document is not defined\n    at app.js:1:1\n",
        ),
    )

    assert main(["-c", "print('browser')"]) == 1

    assert capsys.readouterr().err == (
        "pyjs: error: This module uses browser APIs. Serve it with "
        "`python -m your_package` or run a managed browser test.\n"
    )


def test_successful_node_execution_does_not_reinterpret_stderr(monkeypatch, capsys):
    node = cli.Node(executable="test-node")
    monkeypatch.setattr(cli, "Node", lambda: node)
    stderr = "ReferenceError: document is not defined\n"
    monkeypatch.setattr(
        node,
        "run_javascript",
        lambda source: subprocess.CompletedProcess([], 0, "", stderr),
    )

    assert main(["-c", "print('diagnostic')"]) == 0

    assert capsys.readouterr().err == stderr


def test_verbose_browser_module_failure_retains_node_stderr(monkeypatch, capsys):
    node = cli.Node(executable="test-node")
    monkeypatch.setattr(cli, "Node", lambda: node)
    stderr = "ReferenceError: HTMLElement is not defined\n    at app.js:2:1\n"
    monkeypatch.setattr(
        node,
        "run_javascript",
        lambda source: subprocess.CompletedProcess([], 1, "", stderr),
    )

    assert main(["-v", "-c", "print('browser')"]) == 1

    error = capsys.readouterr().err
    assert error == (
        stderr
        + "pyjs: hint: This module uses browser APIs. Serve it with "
        "`python -m your_package` or run a managed browser test.\n"
    )


def test_json_browser_module_failure_retains_stderr_and_hint(monkeypatch, capsys):
    node = cli.Node(executable="test-node")
    monkeypatch.setattr(cli, "Node", lambda: node)
    stderr = "ReferenceError: window is not defined\n    at app.js:3:1\n"
    monkeypatch.setattr(
        node,
        "run_javascript",
        lambda source: subprocess.CompletedProcess([], 1, "", stderr),
    )

    assert main(["--json", "-c", "print('browser')"]) == 1

    result = json.loads(capsys.readouterr().out)
    assert result["stderr"] == stderr
    assert result["hint"] == (
        "This module uses browser APIs. Serve it with `python -m your_package` "
        "or run a managed browser test."
    )


def test_perf_json_compares_python_and_javascript(monkeypatch, capsys):
    node = cli.Node(executable="test-node")
    calls = []
    monkeypatch.setattr(cli, "Node", lambda: node)
    monkeypatch.setattr(
        cli,
        "benchmark_python",
        lambda *args, **kwargs: cli.Benchmark(10, (0.02, 0.01)),
    )

    def run(source):
        calls.append(source)
        if "__pyjsPerf__" in source:
            return subprocess.CompletedProcess(
                [],
                0,
                '__PYJS_PERF__{"loops":10,"values":[0.01,0.02]}\n',
                "",
            )
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(node, "run_javascript", run)

    assert main(["--perf", "--loops", "10", "--samples", "2", "--json", "-c", "1 + 2"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["correctness"]["matches"] is True
    assert result["performance"]["python"]["loops"] == 10
    assert result["performance"]["javascript"]["loops"] == 10
    assert len(calls) == 2


def test_perf_auto_calibration_uses_one_common_loop_count(monkeypatch, capsys):
    node = cli.Node(executable="test-node")
    calls = []
    monkeypatch.setattr(cli, "Node", lambda: node)
    monkeypatch.setattr(cli, "calibrate_python", lambda function: 20)

    def run(source):
        calls.append(source)
        if "__pyjsPerf__" not in source:
            return subprocess.CompletedProcess([], 0, "", "")
        if "let loops = null;" in source:
            values = {"loops": 10, "values": []}
        else:
            assert "let loops = 20;" in source
            values = {"loops": 20, "values": [0.01, 0.02]}
        return subprocess.CompletedProcess([], 0, f"__PYJS_PERF__{json.dumps(values)}\n", "")

    monkeypatch.setattr(node, "run_javascript", run)
    monkeypatch.setattr(
        cli,
        "benchmark_python",
        lambda *args, **kwargs: cli.Benchmark(20, (0.02, 0.01)),
    )

    assert main(["--perf", "--samples", "2", "--json", "-c", "1 + 2"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["performance"]["python"]["loops"] == 20
    assert result["performance"]["javascript"]["loops"] == 20
    assert result["performance"]["calibration"] == {
        "python_loops": 20,
        "javascript_loops": 10,
        "selected_loops": 20,
    }
    assert len(calls) == 3


def test_python_file_runs_as_javascript(tmp_path, monkeypatch, capsys):
    source = tmp_path / "example.py"
    source.write_text("def main():\n    print(7)\n", encoding="utf-8")
    node = cli.Node(executable="test-node")
    generated = {}
    monkeypatch.setattr(cli, "Node", lambda: node)

    def run(javascript):
        generated["source"] = javascript
        return subprocess.CompletedProcess([], 0, "7\n", "")

    monkeypatch.setattr(node, "run_javascript", run)

    assert main([str(source)]) == 0

    assert "console.log(7)" in generated["source"]
    assert capsys.readouterr().out == "7\n"


def test_python_file_without_main_runs_as_a_script(tmp_path, monkeypatch, capsys):
    source = tmp_path / "example.py"
    source.write_text("print(9)\n", encoding="utf-8")
    node = cli.Node(executable="test-node")
    monkeypatch.setattr(cli, "Node", lambda: node)
    monkeypatch.setattr(
        node,
        "run_javascript",
        lambda javascript: subprocess.CompletedProcess([], 0, "9\n", ""),
    )

    assert main([str(source)]) == 0

    assert capsys.readouterr().out == "9\n"


def test_module_runs_as_javascript(tmp_path, monkeypatch, capsys):
    (tmp_path / "example_module.py").write_text(
        "def main():\n    print('module')\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(tmp_path)
    node = cli.Node(executable="test-node")
    monkeypatch.setattr(cli, "Node", lambda: node)
    monkeypatch.setattr(
        node,
        "run_javascript",
        lambda javascript: subprocess.CompletedProcess([], 0, "module\n", ""),
    )

    assert main(["-m", "example_module"]) == 0

    assert capsys.readouterr().out == "module\n"


def test_serve_uses_default_runner_for_module(tmp_path, monkeypatch):
    (tmp_path / "serve_module.py").write_text(
        "def main():\n    return None\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(tmp_path)
    served = []
    monkeypatch.setattr(cli, "serve_application", served.append)

    assert main(["serve", "serve_module"]) == 0

    assert served == ["serve_module"]


def test_serve_uses_default_runner_for_file(tmp_path, monkeypatch):
    application = tmp_path / "standalone.py"
    application.write_text("def main():\n    return None\n", encoding="utf-8")
    served = []
    monkeypatch.setattr(cli, "serve_application", served.append)

    assert main(["serve", str(application)]) == 0

    assert served == [str(application.resolve())]


def test_serve_runs_package_entry_point(tmp_path, monkeypatch):
    package = tmp_path / "serve_package"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(tmp_path)
    calls = []
    monkeypatch.setattr(
        cli.runpy,
        "run_module",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert main(["serve", "serve_package"]) == 0

    assert calls == [(('serve_package',), {"run_name": "__main__", "alter_sys": True})]


def test_serve_uses_default_runner_for_package_without_entry_point(tmp_path, monkeypatch):
    package = tmp_path / "serve_default_package"
    package.mkdir()
    (package / "__init__.py").write_text(
        "def main():\n    return None\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(tmp_path)
    served = []
    monkeypatch.setattr(cli, "serve_application", served.append)

    assert main(["serve", "serve_default_package"]) == 0

    assert served == ["serve_default_package"]


def test_serve_uses_project_application(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pyjs]\napplication = "configured_app"\n', encoding="utf-8"
    )
    (tmp_path / "configured_app.py").write_text(
        "def main():\n    return None\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    served = []
    monkeypatch.setattr(cli, "serve_application", served.append)

    assert main(["serve"]) == 0

    assert served == ["configured_app"]


def test_serve_without_target_or_project_application_is_an_error(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'ambiguous'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit):
        main(["serve"])

    assert "no application is configured" in capsys.readouterr().err


def test_source_all_mode_labels_each_tree_shaken_module(tmp_path, monkeypatch, capsys):
    (tmp_path / "source_helper.py").write_text(
        "from pyjs import js\n\n@js\ndef double(value: int) -> int:\n    return value * 2\n",
        encoding="utf-8",
    )
    (tmp_path / "source_app.py").write_text(
        "from source_helper import double\n\ndef main():\n    print(double(3))\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(tmp_path)
    sys.modules.pop("source_helper", None)

    assert main(["--src-all", "-m", "source_app"]) == 0

    output = capsys.readouterr().out
    assert output.count("=====") == 4
    assert "===== source_helper.js =====" in output
    assert "===== source_app.js =====" in output
    assert "const modules = new Map()" not in output


def test_source_mode_does_not_render_optional_type_diagnostics(capsys):
    counter = Path(__file__).parents[1] / "examples" / "counter.py"

    assert main(["--src", str(counter)]) == 0

    output = capsys.readouterr().out
    assert "export class CounterApp" in output
    assert "export class CustomElement" not in output
    assert "===== pyjs.web.domx.js =====" not in output
    assert "const modules = new Map()" not in output


def test_inspect_captures_running_application(tmp_path, monkeypatch, capsys):
    captured = {}
    screenshot = tmp_path / "page.png"
    diagnostics = tmp_path / "page.json"

    async def capture(url, output, **options):
        captured.update(url=url, output=output, **options)
        return CaptureResult([screenshot], diagnostics)

    monkeypatch.setattr(cli, "capture_url", capture)

    assert (
        main(
            [
                "inspect",
                "http://localhost:9000",
                "--output",
                str(screenshot),
                "--width",
                "390",
                "--height",
                "844",
                "--color-scheme",
                "dark",
                "--wait-for",
                "main",
            ]
        )
        == 0
    )

    assert captured["url"] == "http://localhost:9000"
    assert captured["output"] == screenshot
    assert captured["width"] == 390
    assert captured["height"] == 844
    assert captured["color_scheme"] == "dark"
    assert captured["wait_for_selector"] == "main"
    assert f"Saved screenshot: {screenshot}" in capsys.readouterr().out


def test_inspect_requires_interval_and_duration_together(capsys):
    with pytest.raises(SystemExit):
        main(["inspect", "--interval", "0.1"])

    assert "--interval and --duration must be used together" in capsys.readouterr().err


def test_create_and_build_starter(tmp_path, monkeypatch, capsys):
    project = tmp_path / "demo"

    assert main(["create", "demo", str(project)]) == 0
    monkeypatch.chdir(project)
    sys.modules.pop("demo.demo", None)
    assert main(["build", "demo.demo:main", "--only-js"]) == 0

    assert (project / "demo.demo.main.js").is_file()
    assert (project / "demo.demo.main.js.map").is_file()
    output = capsys.readouterr().out
    assert "Created PyJS project" in output
    assert "python -m demo" in output
    assert "pyjs serve" in output


def test_create_starter_in_current_directory_with_src_layout(tmp_path):
    assert main(["create", "demo", str(tmp_path), "--src-layout"]) == 0

    assert (tmp_path / "src/demo/__init__.py").is_file()
    assert (tmp_path / "src/demo/demo.py").is_file()


def test_create_from_registered_template(tmp_path):
    project = tmp_path / "calculator-demo"

    assert (
        main(
            [
                "create",
                "calculator_demo",
                str(project),
                "--template",
                "pyjs_examples.calculator",
            ]
        )
        == 0
    )

    assert (project / "calculator.py").is_file()


def test_create_standalone_file_from_registered_template(tmp_path, capsys):
    application = tmp_path / "my_counter.py"

    assert (
        main(
            [
                "create",
                "my_counter",
                str(tmp_path),
                "--template",
                "pyjs_examples.counter",
                "--single-file",
            ]
        )
        == 0
    )

    assert application.is_file()
    assert "serve(__file__)" in application.read_text()
    assert f"python {application}" in capsys.readouterr().out


def test_create_rejects_a_destination_without_an_application_name(capsys):
    with pytest.raises(SystemExit):
        main(["create", "."])

    assert "valid Python identifiers" in capsys.readouterr().err


def test_no_command_prints_help(capsys):
    assert main([]) == 0

    output = capsys.readouterr().out
    assert "create" in output
    assert "serve" in output
    assert "docs" in output
    assert "skill" in output


def test_top_level_help_surfaces_python_like_execution_options(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "Python-like direct execution" in output
    assert "-c CODE" in output
    assert "-m MODULE" in output
    assert "--src-all" in output
    assert "--perf" in output


def test_skill_uses_current_project_and_store_run_commands(capsys):
    assert main(["skill"]) == 0

    output = capsys.readouterr().out
    assert "python -m PACKAGE" in output
    assert "python app.py" not in output
    assert 'python -m pip install "pyjs-examples[store]"' in output
    assert "python -m pyjs_examples.store" in output


def test_docs_help_lists_build_and_serve(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["docs", "--help"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "build" in output
    assert "serve" in output
