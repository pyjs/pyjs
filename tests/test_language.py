"""Real compiler snapshots, invalid edits, and LSP wire interoperability."""

import io
import os
import subprocess
import sys
import sysconfig
import venv
from pathlib import Path

import pytest

import pyjs
from pyjs.language.server import read_message, write_message
from pyjs.language.session import AnalysisSession

SOURCE = '''from pyjs import js
@js
def calculate(value: int):
    result = value + 1
    return result
'''


def project_interpreter(directory, *, compiler=True):
    venv.EnvBuilder(with_pip=False).create(directory)
    executable = directory / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    library = Path(subprocess.check_output([str(executable), '-I', '-c',
        'import sysconfig; print(sysconfig.get_path("purelib"))'], text=True).strip())
    if compiler:
        (library / 'compiler.pth').write_text(
            str(Path(pyjs.__file__).resolve().parents[1]) + '\n' + sysconfig.get_path('purelib') + '\n')
    return executable, library


def test_selected_interpreters_use_their_dependencies_and_separate_caches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'workspace'
    root.mkdir()
    path = root / 'example.py'
    path.write_text('from runtime_dependency import get_value\nfrom pyjs import js\n'
                    '@js\ndef answer():\n    return get_value()\n')
    cache = tmp_path / 'cache'
    for name, value, label in [('numbers', '42', 'int'), ('strings', '"hello"', 'str')]:
        executable, library = project_interpreter(tmp_path / name)
        (library / 'runtime_dependency.py').write_text(
            'from pyjs import js\n@js\ndef get_value():\n    return ' + value + '\n')
        session = AnalysisSession(root, interpreter=executable.relative_to(tmp_path), cache_dir=cache)
        try:
            result = session.snapshot(path.as_uri(), force=True)
            assert result['status'] == 'ready', result
            assert result['symbols'][0]['type'] == 'answer() -> ' + label
            assert not result['cached']
        finally:
            session.shutdown()
        reopened = AnalysisSession(root, interpreter=executable.relative_to(tmp_path), cache_dir=cache)
        try:
            result = reopened.snapshot(path.as_uri())
            assert result['cached']
            assert result['symbols'][0]['type'] == 'answer() -> ' + label
        finally:
            reopened.shutdown()
    assert len(list(cache.glob('*/snapshots.sqlite3'))) == 2


def test_missing_compiler_does_not_break_protocol_or_silently_use_host_python(tmp_path):
    executable, _ = project_interpreter(tmp_path / 'empty', compiler=False)
    path = tmp_path / 'example.py'
    path.write_text(SOURCE)
    child = subprocess.Popen([sys.executable, '-m', 'pyjs', 'lsp', '--root', str(tmp_path),
                              '--python', str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        write_message(child.stdin, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})
        assert read_message(child.stdout)['id'] == 1
        write_message(child.stdin, {'jsonrpc': '2.0', 'id': 2, 'method': 'pyjs/moduleState',
                                   'params': {'uri': path.as_uri()}})
        assert 'selected interpreter needs PyJS' in read_message(child.stdout)['error']['message']
        write_message(child.stdin, {'jsonrpc': '2.0', 'id': 3, 'method': 'shutdown'})
        assert read_message(child.stdout)['id'] == 3
        write_message(child.stdin, {'jsonrpc': '2.0', 'method': 'exit'})
        assert child.wait(timeout=5) == 0
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)


def test_snapshot_resolves_paths_and_sorts_once_per_module(tmp_path, monkeypatch):
    from pathlib import Path

    from pyjs.analysis.objects import AsyncFunctionDef, FunctionDef
    from pyjs.javascript.source import analyze_source
    from pyjs.language import snapshots

    path = tmp_path / "example.py"
    source = ("from pyjs import js\n@js\ndef helper(value: int):\n    return value + 1\n"
              "def main():\n    text = '🐍'; size = len(text)\n    return helper(size)\n")
    with analyze_source(source, filename=str(path)) as analysis:
        resolved = []
        sorted_lengths = []
        body_walks = {}
        labels = {}
        original_resolve = Path.resolve
        original_walk = snapshots.ast.walk
        original_label = snapshots.type_text

        def resolve(path, *args, **kwargs):
            resolved.append(str(path))
            return original_resolve(path, *args, **kwargs)

        def sort(values, **kwargs):
            values = list(values)
            sorted_lengths.append(len(values))
            return sorted(values, **kwargs)

        def walk(node):
            if isinstance(node, (FunctionDef, AsyncFunctionDef)):
                body_walks[node] = body_walks.get(node, 0) + 1
            return original_walk(node)

        def label(value):
            labels[value] = labels.get(value, 0) + 1
            return original_label(value)

        monkeypatch.setattr(Path, "resolve", resolve)
        monkeypatch.setattr(snapshots, "sorted", sort, raising=False)
        monkeypatch.setattr(snapshots.ast, "walk", walk)
        monkeypatch.setattr(snapshots, "type_text", label)
        snapshot = snapshots.collect(analysis.entry_point, tmp_path, {str(path): source}, "__synthetic__")[str(path)]
    assert resolved.count(str(path)) == 1
    assert sorted_lengths == [len(snapshot["occurrences"])]
    assert list(body_walks.values()) == [1, 1]
    assert labels and set(labels.values()) == {1}
    assert snapshot["symbols"] == [
        {"name": "helper", "type": "helper(value: int) -> int", "kind": "function", "line": 3},
        {"name": "main", "type": "main() -> int", "kind": "function", "line": 5},
    ]
    positions = [(item["line"], item["column"]) for item in snapshot["occurrences"]]
    assert positions == sorted(set(positions))
    for item in snapshot["occurrences"]:
        assert source.splitlines()[item["line"] - 1][item["column"]:item["endColumn"]] == item["name"]
    call = next(item for item in snapshot["occurrences"] if item["name"] == "helper" and item["line"] == 7)
    assert (call["definitionPath"], call["definitionLine"], call["definitionColumn"]) == ("example.py", 3, 4)


def test_snapshot_uses_inference_and_skips_unchanged_source(tmp_path):
    path = tmp_path / "example.py"
    path.write_text(SOURCE)
    session = AnalysisSession(tmp_path)
    session.update(path.as_uri(), 1, SOURCE)
    first = session.snapshot(path.as_uri())
    assert first["status"] == "ready", first
    assert first["symbols"] == [{"name": "calculate", "type": "calculate(value: int) -> int",
                                 "kind": "function", "line": 3}]
    assert {item["type"] for item in first["occurrences"]} == {"int"}
    assert first["occurrences"][0]["line"] == 3
    assert session.snapshot(path.as_uri())["cached"]
    session.update(path.as_uri(), 2, SOURCE + "\nif (")
    pending = session.snapshot(path.as_uri())
    assert pending["status"] == "pending"
    assert pending["symbols"] == []
    changed = SOURCE.replace("value: int", "value: str").replace("value + 1", 'value + "!"')
    session.update(path.as_uri(), 3, changed)
    assert session.snapshot(path.as_uri())["symbols"][0]["type"] == "calculate(value: str) -> str"
    assert path.read_text() == SOURCE


def test_imported_disk_and_unsaved_dependencies_invalidate_snapshot(tmp_path):
    dep = tmp_path / "helper.py"
    dep.write_text("from pyjs import js\n@js\ndef value():\n    return 1\n")
    path = tmp_path / "example.py"
    source = "from pyjs import js\nfrom helper import value\n@js\ndef calculate():\n    return value()\n"
    path.write_text(source)
    session = AnalysisSession(tmp_path)
    session.update(path.as_uri(), 1, source)
    first = session.snapshot(path.as_uri())
    assert first["status"] == "ready", first
    assert first["symbols"][0]["type"] == "calculate() -> int"
    dep.write_text(dep.read_text().replace("return 1", 'return "a"'))
    second = session.snapshot(path.as_uri())
    assert not second["cached"]
    assert second["symbols"][0]["type"] == "calculate() -> str"
    session.update(dep.as_uri(), 1, dep.read_text().replace('return "a"', "return True"))
    assert session.snapshot(path.as_uri())["symbols"][0]["type"] == "calculate() -> bool"


def test_module_execution_failure_and_hang_do_not_kill_session(tmp_path):
    path = tmp_path / "example.py"
    path.write_text("")
    session = AnalysisSession(tmp_path, timeout=1)
    for version, source in enumerate(["raise SystemExit(0)", "while True: pass", SOURCE], 1):
        session.update(path.as_uri(), version, source)
        result = session.snapshot(path.as_uri())
        assert result["status"] == ("ready" if version == 3 else "error"), result


def test_stdio_cli_and_unicode_frames(tmp_path):
    path = tmp_path / "example.py"
    path.write_text(SOURCE)
    child = subprocess.Popen([sys.executable, "-m", "pyjs", "lsp", "--root", str(tmp_path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        def exchange(i, method, params):
            write_message(child.stdin, {"jsonrpc": "2.0", "id": i, "method": method, "params": params})
            response = read_message(child.stdout)
            assert response["id"] == i, response
            return response
        assert exchange(1, "initialize", {})["result"]["capabilities"]["textDocumentSync"]["change"] == 1
        result = exchange(2, "pyjs/moduleSnapshot", {"uri": path.as_uri(), "version": 1,
                                                   "text": '# 🐍\nprint("worker logging")\n' + SOURCE})
        assert result["result"]["status"] == "ready", result
        assert exchange(3, "shutdown", {})["result"] is None
        write_message(child.stdin, {"jsonrpc": "2.0", "method": "exit"})
        assert child.wait(timeout=5) == 0
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)
    stream = io.BytesIO()
    write_message(stream, {"jsonrpc": "2.0", "result": "🐍"})
    stream.seek(0)
    assert read_message(stream)["result"] == "🐍"


def test_atomic_buffer_set_closes_old_overlays_and_force_reruns_initialization(tmp_path):
    path = tmp_path / "example.py"
    marker = tmp_path / "count.txt"
    source = ('from pathlib import Path\n'
              'path = Path("count.txt")\n'
              'count = int(path.read_text()) + 1 if path.exists() else 1\n'
              'path.write_text(str(count))\n' + SOURCE)
    path.write_text(source)
    session = AnalysisSession(tmp_path)
    session.replace_documents([{"uri": path.as_uri(), "version": 1, "text": source}])
    assert session.snapshot(path.as_uri())["status"] == "ready"
    assert marker.read_text() == "1"
    assert session.snapshot(path.as_uri())["cached"]
    assert marker.read_text() == "1"
    session.snapshot(path.as_uri(), force=True)
    assert marker.read_text() == "2"
    invalid = tmp_path / "incomplete.py"
    session.update(invalid.as_uri(), 1, "if (")
    assert session.snapshot(path.as_uri())["status"] == "pending"
    assert marker.read_text() == "2"
    session.replace_documents([{"uri": path.as_uri(), "version": 2, "text": source}])
    assert session.snapshot(path.as_uri())["status"] == "ready"


def test_imports_and_module_initialization_see_unsaved_relative_sources(tmp_path):
    package = tmp_path / "example"
    package.mkdir()
    (package / "__init__.py").write_text("")
    dependency = package / "config.py"
    dependency.write_text('NAME = "old"\n')
    path = package / "main.py"
    source = 'from .config import NAME\nvalue = len(NAME)\n' + SOURCE
    path.write_text(source)
    session = AnalysisSession(tmp_path)
    session.replace_documents([
        {"uri": dependency.as_uri(), "version": 1, "text": 'NAME = "new name"\n'},
        {"uri": path.as_uri(), "version": 1, "text": source},
    ])
    result = session.snapshot(path.as_uri())
    assert result["status"] == "ready", result
    assert result["symbols"][0] == {"name": "value", "type": "int", "kind": "global", "line": 2}


def test_old_generation_is_never_published_as_current(tmp_path):
    import concurrent.futures
    import time

    path = tmp_path / "example.py"
    source = 'import time\ntime.sleep(0.3)\n' + SOURCE
    path.write_text(source)
    session = AnalysisSession(tmp_path)
    session.update(path.as_uri(), 1, source)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(session.snapshot, path.as_uri())
        deadline = time.monotonic() + 5
        while session.process is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert session.process is not None
        session.update(path.as_uri(), 2, SOURCE)
        assert future.result(timeout=5)["status"] == "superseded"
    assert session.snapshot(path.as_uri())["status"] == "ready"


@pytest.mark.parametrize('change', ['invalid-sibling', 'failed-target'])
def test_changed_generation_does_not_publish_inflight_results(tmp_path, change):
    import concurrent.futures
    import time

    path = tmp_path / 'example.py'
    source = ('from pathlib import Path\nimport time\n'
              'Path("started").touch()\n'
              'while not Path("continue").exists():\n    time.sleep(0.01)\n')
    source += SOURCE if change == 'invalid-sibling' else 'raise ValueError("old source")\n'
    path.write_text(source)
    session = AnalysisSession(tmp_path)
    try:
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(session.snapshot, path.as_uri())
            try:
                deadline = time.monotonic() + 5
                while not (tmp_path / 'started').exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert (tmp_path / 'started').exists()
                if change == 'invalid-sibling':
                    session.update((tmp_path / 'other.py').as_uri(), 1, 'if (')
                else:
                    session.update(path.as_uri(), 1, SOURCE)
            finally:
                (tmp_path / 'continue').touch()
            assert future.result(timeout=5)['status'] == 'superseded'
        assert not session.cache
        session.replace_documents([{'uri': path.as_uri(), 'version': 2, 'text': SOURCE}])
        assert session.snapshot(path.as_uri())['status'] == 'ready'
    finally:
        session.shutdown()


def test_malformed_frame_stops_the_running_worker(tmp_path):
    import time

    path = tmp_path / 'example.py'
    path.write_text('from pathlib import Path\nimport time\n'
                    'Path("started").touch()\ntime.sleep(30)\n' + SOURCE)
    child = subprocess.Popen([sys.executable, '-m', 'pyjs', 'lsp', '--root', str(tmp_path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        write_message(child.stdin, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'})
        assert read_message(child.stdout)['id'] == 1
        write_message(child.stdin, {'jsonrpc': '2.0', 'id': 2, 'method': 'pyjs/moduleSnapshot',
                                   'params': {'uri': path.as_uri()}})
        deadline = time.monotonic() + 5
        while not (tmp_path / 'started').exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (tmp_path / 'started').exists()
        child.stdin.write(b'invalid header\r\n\r\n')
        child.stdin.flush()
        assert child.wait(timeout=5) != 0
        assert b'Invalid LSP header' in child.stderr.read()
    finally:
        if child.poll() is None:
            child.terminate()
        child.communicate(timeout=5)


def test_namespace_package_and_unicode_source_locations(tmp_path):
    directory = tmp_path / "namespace" / "nested"
    directory.mkdir(parents=True)
    path = directory / "example.py"
    source = 'from pyjs import js\n@js\ndef word():\n    text = "🐍"; size = len(text)\n    return size\n'
    path.write_text(source)
    session = AnalysisSession(tmp_path)
    session.update(path.as_uri(), 1, source)
    result = session.snapshot(path.as_uri())
    assert result["status"] == "ready", result
    occurrence = next(item for item in result["occurrences"] if item["name"] == "size" and item["line"] == 4)
    assert source.splitlines()[3][occurrence["column"]:occurrence["endColumn"]] == "size"
    assert occurrence["type"] == "int"


def test_valid_python_with_type_error_is_not_reported_as_pending(tmp_path):
    path = tmp_path / "example.py"
    path.write_text(SOURCE)
    session = AnalysisSession(tmp_path)
    session.update(path.as_uri(), 1, SOURCE)
    assert session.snapshot(path.as_uri())["status"] == "ready"
    session.update(path.as_uri(), 2, SOURCE.replace("value + 1", "missing_name"))
    result = session.snapshot(path.as_uri())
    assert result["status"] == "error"
    assert "missing_name" in result["message"]
    assert result["occurrences"] == []


def test_class_methods_have_inferred_types_and_original_locations(tmp_path):
    path = tmp_path / "example.py"
    source = ('from pyjs import js\n@js\nclass Thing:\n'
              '    def __init__(self, value: int):\n        self.value = value\n'
              '    def double(self):\n        result = self.value * 2\n        return result\n')
    path.write_text(source)
    session = AnalysisSession(tmp_path)
    session.update(path.as_uri(), 1, source)
    result = session.snapshot(path.as_uri())
    assert result["status"] == "ready", result
    methods = {symbol["name"]: symbol for symbol in result["symbols"]}
    assert methods["Thing.double"]["type"].endswith(" -> int")
    assert methods["Thing.double"]["line"] == 6
    occurrence = next(item for item in result["occurrences"] if item["name"] == "result")
    assert occurrence["line"] == 7
    assert occurrence["type"] == "int"


def test_traversed_modules_survive_restart_and_resolve_import_aliases(tmp_path):
    dep = tmp_path / "helper.py"
    dep.write_text('from pyjs import js\n@js\ndef value(number: int):\n    """Return the next number."""\n    return number + 1\n')
    path = tmp_path / "example.py"
    path.write_text('from pyjs import js\nfrom helper import value as next_value\n@js\ndef calculate():\n    result = next_value(4)\n    return result\n')
    (tmp_path / "pyproject.toml").write_text('[tool.pyjs]\napplication="example"\n')
    session = AnalysisSession(tmp_path)
    session.index_project()
    assert session.index_state == "ready"
    snapshot = session.snapshot(path.as_uri())
    reference = next(item for item in snapshot["occurrences"] if item["name"] == "next_value")
    assert reference["definitionPath"] == "helper.py"
    assert reference["definitionLine"] == 3
    assert reference["definitionColumn"] == 4
    assert reference["signature"] == "value(number: int) -> int"
    assert reference["documentation"] == "Return the next number."
    assert any(item["hint"] and item["name"] == "result" for item in snapshot["occurrences"])
    session.shutdown()
    restarted = AnalysisSession(tmp_path)
    retained = restarted.snapshot(dep.as_uri())
    assert retained["cached"]
    assert restarted.process is None
    assert retained["symbols"][0]["type"] == "value(number: int) -> int"
    dep.write_text(dep.read_text().replace("number + 1", '"different"'))
    assert not restarted.snapshot(dep.as_uri())["cached"]
    assert restarted.snapshot(dep.as_uri())["symbols"][0]["type"].endswith(" -> str")


def test_unsaved_snapshots_are_not_reused_for_different_disk_content(tmp_path):
    path = tmp_path / "example.py"
    path.write_text(SOURCE)
    session = AnalysisSession(tmp_path)
    changed = SOURCE.replace("value: int", "value: str").replace("value + 1", 'value + "!"')
    session.update(path.as_uri(), 1, changed)
    assert session.snapshot(path.as_uri())["symbols"][0]["type"].endswith(" -> str")
    restarted = AnalysisSession(tmp_path)
    assert restarted.cached_snapshot(path.as_uri()) is None
    assert restarted.snapshot(path.as_uri())["symbols"][0]["type"].endswith(" -> int")


def test_class_reference_and_local_definition_locations(tmp_path):
    path = tmp_path / "example.py"
    path.write_text('from pyjs import js\n@js\nclass Thing:\n    def double(self, number: int):\n        result = number * 2\n        return result\n@js\ndef run():\n    thing = Thing()\n    return thing.double(3)\n')
    result = AnalysisSession(tmp_path).snapshot(path.as_uri())
    assert result["status"] == "ready", result
    method = next(item for item in result["occurrences"] if item["name"] == "double")
    assert (method["definitionLine"], method["definitionColumn"]) == (4, 8)
    local = next(item for item in result["occurrences"] if item["name"] == "result" and item["line"] == 6)
    assert (local["definitionLine"], local["definitionColumn"]) == (5, 8)


def test_opening_unchanged_buffer_during_background_index_reuses_results(tmp_path):
    import concurrent.futures
    import time

    path = tmp_path / "example.py"
    path.write_text('import time\ntime.sleep(0.3)\n' + SOURCE)
    session = AnalysisSession(tmp_path)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(session.snapshot, path.as_uri())
        deadline = time.monotonic() + 5
        while session.process is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert session.process is not None
        session.update(path.as_uri(), 1, path.read_text())
        assert future.result(timeout=5)["status"] == "ready"
    assert session.snapshot(path.as_uri())["cached"]


def test_cached_file_does_not_wait_for_unrelated_slow_analysis(tmp_path):
    import concurrent.futures
    import time

    path = tmp_path / "example.py"
    path.write_text(SOURCE)
    other = tmp_path / "slow.py"
    other.write_text('import time\ntime.sleep(0.5)\n' + SOURCE)
    session = AnalysisSession(tmp_path)
    assert session.snapshot(path.as_uri())["status"] == "ready"
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(session.snapshot, other.as_uri())
        deadline = time.monotonic() + 5
        while session.process is None and time.monotonic() < deadline:
            time.sleep(0.01)
        started = time.monotonic()
        assert session.snapshot(path.as_uri())["cached"]
        assert time.monotonic() - started < 0.25
        assert future.result(timeout=5)["status"] == "ready"


def test_parameter_declarations_and_complete_signature_are_available(tmp_path):
    path = tmp_path / "example.py"
    source = ('from pyjs import js\n@js\ndef describe(value: int, /, count: int = 2, *, label: str = "hi") -> str:\n'
              '    """Describe a value."""\n    return label * (value + count)\n')
    path.write_text(source)
    session = AnalysisSession(tmp_path)
    try:
        result = session.snapshot(path.as_uri())
        assert result['status'] == 'ready', result
        assert result['symbols'][0]['type'] == "describe(value: int, /, count: int = 2, *, label: str = 'hi') -> str"
        declarations = [item for item in result['occurrences'] if item['kind'] == 'parameter']
        assert [(item['name'], item['type']) for item in declarations] == [('value', 'int'), ('count', 'int'), ('label', 'str')]
        for item in declarations:
            assert source.splitlines()[item['line'] - 1][item['column']:item['endColumn']] == item['name']
            assert item['definitionLine'] == 3
    finally:
        session.shutdown()
