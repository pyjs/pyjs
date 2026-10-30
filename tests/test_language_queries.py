import concurrent.futures
import time

import pytest

from pyjs.language.session import AnalysisSession

SOURCE = ('import helper\nfrom pyjs import js\n@js\ndef render(value: int) -> str:\n'
          '    return str(value)\n@js\ndef example(value: int):\n    return render(value)\n')


@pytest.mark.parametrize('method', ['completion', 'signatures'])
@pytest.mark.parametrize('ending', ['import os; os._exit(4)', 'import time; time.sleep(10)'])
def test_query_failure_cleanup_and_recovery(tmp_path, method, ending):
    path = tmp_path / 'example.py'
    path.write_text(SOURCE)
    helper = tmp_path / 'helper.py'
    helper.write_text(ending + '\n')
    session = AnalysisSession(tmp_path, timeout=1, cache_dir=tmp_path / '.cache')
    try:
        query = getattr(session, method)
        failed = query(path.as_uri(), 8, 20)
        assert failed['status'] == 'error', failed
        assert failed['items'] == [] and failed['signatures'] == []
        assert 'timed out' in failed['message'] if 'sleep' in ending else 'exited' in failed['message']
        assert session.process is None
        helper.write_text('VALUE = 1\n')
        assert query(path.as_uri(), 8, 20)['status'] == 'ready'
        assert not session.cache
    finally:
        session.shutdown()


@pytest.mark.parametrize('method', ['completion', 'signatures'])
@pytest.mark.parametrize('change', ['disk', 'overlay', 'invalid-sibling'])
def test_query_discards_changed_dependency_generation(tmp_path, method, change):
    path = tmp_path / 'example.py'
    path.write_text(SOURCE)
    helper = tmp_path / 'helper.py'
    helper.write_text('from pathlib import Path\nimport time\nPath("started").touch()\n'
                      'while not Path("continue").exists():\n    time.sleep(0.01)\nVALUE = 1\n')
    session = AnalysisSession(tmp_path, timeout=5, cache_dir=tmp_path / '.cache')
    try:
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(getattr(session, method), path.as_uri(), 8, 20)
            try:
                deadline = time.monotonic() + 5
                while not (tmp_path / 'started').exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert (tmp_path / 'started').exists()
                if change == 'disk':
                    helper.write_text('VALUE = 2\n')
                elif change == 'overlay':
                    session.update(helper.as_uri(), 1, 'VALUE = 2\n')
                else:
                    session.update((tmp_path / 'other.py').as_uri(), 1, 'if (')
            finally:
                (tmp_path / 'continue').touch()
            result = future.result(timeout=5)
            assert result['status'] == 'superseded', result
            assert result['items'] == [] and result['signatures'] == []
        assert session.process is None
        assert not session.cache
    finally:
        session.shutdown()


@pytest.mark.parametrize('method', ['completion', 'signatures'])
def test_shutdown_terminates_query_worker(tmp_path, method):
    path = tmp_path / 'example.py'
    path.write_text(SOURCE)
    (tmp_path / 'helper.py').write_text(
        'from pathlib import Path\nimport time\nPath("started").touch()\ntime.sleep(30)\n')
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / '.cache')
    try:
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(getattr(session, method), path.as_uri(), 8, 20)
            try:
                deadline = time.monotonic() + 5
                while not (tmp_path / 'started').exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert (tmp_path / 'started').exists()
                process = session.process
            finally:
                session.shutdown()
            assert future.result(timeout=5)['status'] == 'error'
            assert process.poll() is not None
            assert session.process is None
    finally:
        session.shutdown()


@pytest.mark.parametrize('method', ['completion', 'signatures'])
@pytest.mark.parametrize('newline', ['\r\n', '\r'])
def test_query_coordinates_use_normalized_lines(tmp_path, method, newline):
    path = tmp_path / 'example.py'
    source = SOURCE.replace('\n', newline)
    path.write_bytes(source.encode())
    (tmp_path / 'helper.py').write_text('VALUE = 1\n')
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / '.cache')
    try:
        session.update(path.as_uri(), 1, source)
        query = getattr(session, method)
        result = query(path.as_uri(), 8, 20)
        assert result['status'] == 'ready', result
        assert result['items' if method == 'completion' else 'signatures']
        with pytest.raises(ValueError, match='position'):
            query(path.as_uri(), 8, len(SOURCE.splitlines()[7]) + 1)
    finally:
        session.shutdown()


@pytest.mark.parametrize('method', ['completion', 'signatures'])
@pytest.mark.parametrize('required', [False, True])
def test_targeted_query_analyzes_required_functions(tmp_path, method, required):
    path = tmp_path / 'example.py'
    source = SOURCE + '\n@js\ndef unrelated():\n    return missing\n'
    if required:
        source = source.replace(' -> str', '').replace('return str(value)', 'return unrelated()')
    path.write_text(source)
    (tmp_path / 'helper.py').write_text('VALUE = 1\n')
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / '.cache')
    try:
        result = getattr(session, method)(path.as_uri(), 8, 20)
        assert result['status'] == ('error' if required else 'ready'), result
        if not required:
            assert result['items' if method == 'completion' else 'signatures']
        assert not session.cache
    finally:
        session.shutdown()


@pytest.mark.parametrize('method', ['completion', 'signatures'])
def test_query_graph_is_not_reused_by_normal_compilation(tmp_path, method):
    from pyjs.analysis.analyzer import analyze_module, release_compilation
    from pyjs.analysis.diagnostics import CompilationError
    from pyjs.analysis.source import create_module
    from pyjs.javascript.source import analyze_source
    from pyjs.language.completion import complete_module
    from pyjs.language.signatures import signatures_module

    expression = 'ren§()' if method == 'completion' else 'render(§)'
    source = '''from pyjs import js
@js
def render(value: int = 1) -> str:
    return str(value)
@js
def example():
    result = ''' + expression + '''
    return result.upper()
@js
def editor_entry():
    pass
def main():
    return example()
'''
    if method == 'signatures':
        source = source.replace('value: int = 1', 'value: int')
    offset = source.index('§')
    source = source.replace('§', '')
    line = source[:offset].count('\n') + 1
    column = len(source[:offset].rsplit('\n', 1)[-1])
    path = tmp_path / 'query_state.py'
    module = create_module(source, str(path))
    query = complete_module if method == 'completion' else signatures_module
    result = query(module, module.editor_entry, path, source, line, column)
    assert result['items' if method == 'completion' else 'signatures']
    with pytest.raises(CompilationError):
        entry, _ = analyze_module(module)
        release_compilation(entry)
    with analyze_source('def main(value: int):\n    return str(value).upper()\n') as normal:
        assert normal.types == 'def main(value: int) -> str:\n    return value.[int]__str__!().[str]upper!()'
        assert normal.javascript == ('export function main(value) {\n'
                                     '    return String(value).toUpperCase();\n}')


@pytest.mark.parametrize('method', ['completion', 'signatures'])
def test_selected_snapshot_only_compiler_is_rejected_before_execution(tmp_path, method):
    from tests.test_language import project_interpreter

    executable, library = project_interpreter(tmp_path / 'old', compiler=False)
    package = library / 'pyjs' / 'language'
    package.mkdir(parents=True)
    (package.parent / '__init__.py').touch()
    (package / '__init__.py').touch()
    (package / 'store.py').write_text('def cache_directory(root):\n    return root / "old-cache"\n')
    marker = tmp_path / 'executed'
    (package / 'worker.py').write_text('from pathlib import Path\ndef main(startup):\n'
                                     f'    Path({str(marker)!r}).touch()\n')
    path = tmp_path / 'example.py'
    path.write_text(SOURCE)
    session = AnalysisSession(tmp_path, interpreter=executable, cache_dir=tmp_path / '.cache')
    try:
        with pytest.raises(ValueError, match='selected interpreter needs PyJS with cursor query support'):
            getattr(session, method)(path.as_uri(), 8, 20)
        assert not marker.exists()
        assert session.process is None
        assert not session.cache
    finally:
        session.shutdown()


@pytest.mark.parametrize('method', ['completion', 'signatures'])
def test_query_uses_selected_interpreter_dependencies(tmp_path, method):
    from tests.test_language import project_interpreter

    executable, library = project_interpreter(tmp_path / 'project-env')
    (library / 'runtime_dependency.py').write_text(
        'from pyjs import js\n@js\ndef render(value: str) -> str:\n    return value\n')
    path = tmp_path / 'example.py'
    source = ('from pyjs import js\nfrom runtime_dependency import render\n'
              '@js\ndef example():\n    return render("hello")\n')
    path.write_text(source)
    session = AnalysisSession(tmp_path, interpreter=executable, cache_dir=tmp_path / '.cache')
    try:
        result = getattr(session, method)(path.as_uri(), 5, 17 if method == 'completion' else 18)
        assert result['status'] == 'ready', result
        item = result['items' if method == 'completion' else 'signatures'][0]
        assert item['detail' if method == 'completion' else 'label'] == 'render(value: str) -> str'
    finally:
        session.shutdown()
