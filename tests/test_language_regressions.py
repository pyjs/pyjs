"""Source-generation and import edge cases through real analysis workers."""

import concurrent.futures
import hashlib
import io
import json
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import pytest

from pyjs.language.server import read_message, write_message
from pyjs.language.session import AnalysisSession
from pyjs.language.store import SnapshotStore

SOURCE = 'from pyjs import js\n@js\ndef answer():\n    return 42\n'


@pytest.mark.parametrize('shadow, imported', [('types', 'asyncio'), ('types', 'email.message'),
                                             ('enum', 'http'), ('functools', 'statistics')])
@pytest.mark.parametrize('opened', [False, True])
def test_workspace_names_preserve_interpreter_startup_imports(tmp_path, shadow, imported, opened):
    dependency = tmp_path / (shadow + '.py')
    dependency.write_text(SOURCE)
    main = tmp_path / 'main.py'
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    try:
        if opened:
            session.update(dependency.as_uri(), 1, SOURCE)
        for prefix in ('import ' + imported, 'from ' + shadow + ' import answer'):
            main.write_text(prefix + '\n' + SOURCE)
            plain = subprocess.run([sys.executable, '-I', '-c',
                'import sys; sys.path.insert(0, sys.argv[1]); import main', str(tmp_path)],
                capture_output=True, text=True, timeout=15)
            result = session.snapshot(main.as_uri(), force=True)
            assert result['status'] == ('ready' if plain.returncode == 0 else 'error'), (result, plain.stderr)
    finally:
        session.shutdown()


def test_workspace_compiler_package_does_not_replace_running_compiler(tmp_path):
    package = tmp_path / 'pyjs'
    package.mkdir()
    (package / '__init__.py').write_text('raise AssertionError("Wrong compiler instance")\n')
    main = tmp_path / 'main.py'
    main.write_text(SOURCE)
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    try:
        session.update((package / '__init__.py').as_uri(), 1, 'VALUE = 1\n')
        result = session.snapshot(main.as_uri(), force=True)
        assert result['status'] == 'ready', result
        assert result['symbols'][0]['type'] == 'answer() -> int'
        result = session.snapshot((package / '__init__.py').as_uri(), force=True)
        assert result['status'] == 'error'
        assert 'conflicts with an interpreter startup or compiler module' in result['message']
    finally:
        session.shutdown()


@pytest.mark.parametrize('separator', ['\x0c', '\x1c', '\x1d', '\x1e', '\x85', '\u2028', '\u2029'])
def test_source_line_positions_follow_python_newlines(tmp_path, separator):
    source = ('from pyjs import js\n# before' + separator + 'after\n'
              '@js\ndef add(value: int, other: int):\n    return value + other\n')
    main = tmp_path / 'main.py'
    main.write_text(source)
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    try:
        result = session.snapshot(main.as_uri())
        assert result['status'] == 'ready', result
        assert result['symbols'][0]['type'] == 'add(value: int, other: int) -> int'
        for item in result['occurrences']:
            text = source.split('\n')[item['line'] - 1][item['column']:item['endColumn']]
            assert text == item['name'], item
    finally:
        session.shutdown()


@pytest.mark.parametrize('collision', ['later_directory', 'shadowed_module'])
def test_opening_a_shadowed_file_preserves_import_precedence(tmp_path, collision):
    if collision == 'later_directory':
        base = tmp_path / 'src'
        base.mkdir()
        first, second = base / 'example.py', tmp_path / 'example.py'
    else:
        base = tmp_path
        (base / 'example').mkdir()
        first, second = base / 'example' / '__init__.py', base / 'example.py'
    first.write_text(SOURCE)
    second.write_text(SOURCE.replace('42', '"other"'))
    main = base / 'main.py'
    main.write_text('from example import answer\n' + SOURCE.replace('return 42', 'return answer()').replace('def answer', 'def result'))
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    try:
        for opened in (False, True):
            if opened:
                session.update(second.as_uri(), 1, second.read_text())
            result = session.snapshot(main.as_uri(), force=True)
            assert result['status'] == 'ready', result
            assert result['symbols'][0]['type'] == 'result() -> int'
            assert str(first) in result['dependencies']
            assert str(second) not in result['dependencies']
    finally:
        session.shutdown()


def test_normalized_identifiers_preserve_original_source_spans(tmp_path):
    helper = tmp_path / 'units.py'
    source = ('from pyjs import js\n@js\nclass ﬁBox:\n'
              '    @staticmethod\n    def ﬁle(µs: int):\n        return µs\n'
              '@js\ndef answer():\n    return ﬁBox.ﬁle(42)\n')
    helper.write_text(source)
    main = tmp_path / 'main.py'
    main.write_text('from units import answer\n' + SOURCE.replace('return 42', 'return answer()').replace('def answer', 'def result'))
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    try:
        result = session.snapshot(main.as_uri())
        assert result['status'] == 'ready', result
        result = session.cached_snapshot(helper.as_uri())
        assert result['status'] == 'ready', result
        names = {item['name'] for item in result['occurrences']}
        assert {'fiBox', 'file', 'μs'} <= names
        for item in result['occurrences']:
            text = source.splitlines()[item['line'] - 1][item['column']:item['endColumn']]
            assert unicodedata.normalize('NFKC', text) == item['name'], item
    finally:
        session.shutdown()


def test_parameterless_protocol_methods_accept_null_params(tmp_path):
    child = subprocess.Popen([sys.executable, '-m', 'pyjs', 'lsp', '--root', str(tmp_path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for index, method in enumerate(['initialize', 'pyjs/indexState', 'shutdown']):
            write_message(child.stdin, {'jsonrpc': '2.0', 'id': index, 'method': method, 'params': None})
            response = read_message(child.stdout)
            assert response['id'] == index
            assert 'result' in response
        write_message(child.stdin, {'jsonrpc': '2.0', 'method': 'exit', 'params': None})
        assert child.wait(timeout=5) == 0
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)


@pytest.mark.parametrize('layout', ['module', 'package', 'src'])
def test_saved_workspace_dependency_overrides_worker_bootstrap(tmp_path, layout):
    base = tmp_path / 'src' if layout == 'src' else tmp_path
    dependency = base / ('json/__init__.py' if layout == 'package' else 'json.py')
    dependency.parent.mkdir(parents=True, exist_ok=True)
    dependency.write_text(SOURCE)
    main = base / 'main.py'
    main.write_text('from json import answer\n' + SOURCE.replace('return 42', 'return answer()').replace('def answer', 'def result'))
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    try:
        result = session.snapshot(main.as_uri())
        assert result['status'] == 'ready', result
        assert result['symbols'][0]['type'] == 'result() -> int'
        assert str(dependency) in result['dependencies']
    finally:
        session.shutdown()


@pytest.mark.parametrize('package', [False, True])
def test_unsaved_namespace_child_does_not_replace_existing_module(tmp_path, package):
    dependency = tmp_path / ('example/__init__.py' if package else 'example.py')
    dependency.parent.mkdir(exist_ok=True)
    dependency.write_text(SOURCE)
    main = tmp_path / 'main.py'
    main.write_text('from example import answer\n' + SOURCE.replace('return 42', 'return answer()').replace('def answer', 'def result'))
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    try:
        session.update((tmp_path / 'example' / 'unused.py').as_uri(), 1, 'VALUE = 42\n')
        result = session.snapshot(main.as_uri())
        assert result['status'] == 'ready', result
        assert result['symbols'][0]['type'] == 'result() -> int'
        assert str(dependency) in result['dependencies']
    finally:
        session.shutdown()


def test_protocol_recovers_after_invalid_uri_types(tmp_path):
    child = subprocess.Popen([sys.executable, '-m', 'pyjs', 'lsp', '--root', str(tmp_path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        write_message(child.stdin, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'})
        assert read_message(child.stdout)['id'] == 1
        for method, extra in [('pyjs/moduleSnapshot', {}), ('pyjs/moduleSnapshot', {'force': True}),
                              ('pyjs/moduleState', {})]:
            for uri in [42, {'invalid': 'uri'}, [], True, None]:
                write_message(child.stdin, {'jsonrpc': '2.0', 'id': 2, 'method': method,
                                            'params': {'uri': uri} | extra})
                response = read_message(child.stdout)
                assert response is not None
                assert response['id'] == 2
                assert response['error']['code'] == -32602
        write_message(child.stdin, {'jsonrpc': '2.0', 'id': 3, 'method': 'pyjs/indexState'})
        assert read_message(child.stdout)['result']['status'] == 'idle'
        write_message(child.stdin, {'jsonrpc': '2.0', 'id': 4, 'method': 'shutdown'})
        assert read_message(child.stdout)['id'] == 4
        write_message(child.stdin, {'jsonrpc': '2.0', 'method': 'exit'})
        assert child.wait(timeout=5) == 0
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)


@pytest.mark.parametrize('module', ['example', 'json', 'pkg.helper'])
@pytest.mark.parametrize('saved', [False, True])
def test_explicit_module_identity_and_unsaved_imports(tmp_path, module, saved):
    target = tmp_path / (module.replace('.', '/') + '.py')
    target.parent.mkdir(exist_ok=True)
    if saved:
        target.write_text(SOURCE)
    main = tmp_path / 'main.py'
    main.write_text('from pyjs import js\nfrom ' + module + ' import answer\n'
                    '@js\ndef result():\n    return answer()\n')
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    try:
        session.update(target.as_uri(), 1, SOURCE)
        for path in (target, main):
            result = session.snapshot(path.as_uri(), force=True)
            assert result['status'] == 'ready', result
            assert result['symbols'][0]['type'].endswith(' -> int')
        assert target.exists() == saved
    finally:
        session.shutdown()


def test_unsaved_package_initialization_is_executed(tmp_path):
    package = tmp_path / 'pkg'
    initial = package / '__init__.py'
    child = package / 'helper.py'
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    try:
        session.replace_documents([
            {'uri': initial.as_uri(), 'version': 1, 'text': SOURCE},
            {'uri': child.as_uri(), 'version': 1,
             'text': 'from pyjs import js\nfrom . import answer\n@js\ndef result():\n    return answer()\n'},
        ])
        result = session.snapshot(child.as_uri())
        assert result['status'] == 'ready', result
        assert result['symbols'][0]['type'] == 'result() -> int'
        assert session.cached_snapshot(initial.as_uri())['status'] == 'ready'
        assert not package.exists()
    finally:
        session.shutdown()


@pytest.mark.parametrize('ending', ['raise ValueError("old dependency")', 'import os; os._exit(4)', 'time.sleep(10)'])
@pytest.mark.parametrize('overlay', [True, False])
def test_changed_dependency_supersedes_failure_exit_and_timeout(tmp_path, ending, overlay):
    helper = tmp_path / 'helper.py'
    helper.write_text('from pathlib import Path\nimport time\nPath("started").touch()\n'
                      'while not Path("continue").exists():\n    time.sleep(0.01)\n' + ending + '\n')
    path = tmp_path / 'main.py'
    path.write_text('import helper\n' + SOURCE)
    session = AnalysisSession(tmp_path, timeout=2, cache_dir=tmp_path / 'cache')
    try:
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(session.snapshot, path.as_uri())
            try:
                deadline = time.monotonic() + 5
                while not (tmp_path / 'started').exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert (tmp_path / 'started').exists()
                if overlay:
                    session.update(helper.as_uri(), 1, 'VALUE = 42\n')
                else:
                    helper.write_text('VALUE = 42\n')
            finally:
                (tmp_path / 'continue').touch()
            assert future.result(timeout=5)['status'] == 'superseded'
        assert session.snapshot(path.as_uri())['status'] == 'ready'
    finally:
        session.shutdown()


def test_restarted_sessions_allocate_distinct_persistent_revisions(tmp_path):
    helper = tmp_path / 'helper.py'
    helper.write_text(SOURCE)
    main = tmp_path / 'main.py'
    main.write_text('from helper import answer\n' + SOURCE.replace('answer', 'other'))
    first = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    first.snapshot(main.as_uri())
    old = first.snapshot(helper.as_uri())
    first.shutdown()
    second = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    try:
        assert second.snapshot(helper.as_uri())['revision'] == old['revision']
        helper.write_text(SOURCE.replace('42', '"new"'))
        second.snapshot(main.as_uri())
        new = second.snapshot(helper.as_uri())
        assert new['symbols'][0]['type'] == 'answer() -> str'
        assert new['revision'] > old['revision']
        # Independently running services also share the allocation sequence.
        stores = [SnapshotStore(tmp_path / 'cache') for _ in range(8)]
        with concurrent.futures.ThreadPoolExecutor() as pool:
            revisions = list(pool.map(lambda store: store.next_revision(0), stores))
        assert len(set(revisions)) == len(revisions)
        assert min(revisions) > new['revision']
    finally:
        second.shutdown()


def test_classmethod_parameters_do_not_replace_class_definitions(tmp_path):
    path = tmp_path / 'example.py'
    source = ('from pyjs import js\n@js\nclass  Example:\n'
              '    @classmethod\n    def  helper(cls, value: int):\n        return cls()\n'
              '@js\ndef\tanswer():\n    return Example()\n')
    path.write_text(source)
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    try:
        result = session.snapshot(path.as_uri())
        assert result['status'] == 'ready', result
        for item in result['occurrences']:
            assert source.splitlines()[item['line'] - 1][item['column']:item['endColumn']] == item['name']
            if item['name'] in ('Example', 'cls', 'helper', 'answer'):
                definition = source.splitlines()[item['definitionLine'] - 1]
                assert definition[item['definitionColumn']:].startswith(item['name']), item
        constructor = next(item for item in result['occurrences'] if item['name'] == 'Example')
        assert (constructor['definitionLine'], constructor['definitionColumn']) == (3, 7)
    finally:
        session.shutdown()


@pytest.mark.parametrize('application', ['example', 'example:answer', 'example.py', 'pkg', 'pkg:answer', 'src/example.py'])
def test_indexing_accepts_module_package_and_source_path(tmp_path, application):
    source = tmp_path / ('pkg/__init__.py' if application.startswith('pkg') else
                         'src/example.py' if application.startswith('src/') else 'example.py')
    source.parent.mkdir(exist_ok=True)
    source.write_text(SOURCE)
    (tmp_path / 'pyproject.toml').write_text('[tool.pyjs]\napplication=' + json.dumps(application) + '\n')
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    try:
        session.index_project()
        assert session.index_state == 'ready'
        assert session.cached_snapshot(source.as_uri())['status'] == 'ready'
    finally:
        session.shutdown()


def test_protocol_recovers_after_invalid_bodies_and_named_parameters(tmp_path):
    child = subprocess.Popen([sys.executable, '-m', 'pyjs', 'lsp', '--root', str(tmp_path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        write_message(child.stdin, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'})
        assert read_message(child.stdout)['id'] == 1
        for body, code in [(b'{not json', -32700), (b'[]', -32600),
                           (b'{"jsonrpc":"1.0"}', -32600)]:
            child.stdin.write(f'Content-Length: {len(body)}\r\n\r\n'.encode() + body)
            child.stdin.flush()
            response = read_message(child.stdout)
            assert response['id'] is None
            assert response['error']['code'] == code
        write_message(child.stdin, {'jsonrpc': '2.0', 'id': 2, 'method': 'pyjs/moduleSnapshot', 'params': [1]})
        assert read_message(child.stdout)['error']['code'] == -32602
        write_message(child.stdin, {'jsonrpc': '2.0', 'id': 3, 'method': 'pyjs/indexState'})
        assert read_message(child.stdout)['result']['status'] == 'idle'
        write_message(child.stdin, {'jsonrpc': '2.0', 'id': 4, 'method': 'shutdown'})
        assert read_message(child.stdout)['id'] == 4
        write_message(child.stdin, {'jsonrpc': '2.0', 'method': 'exit'})
        assert child.wait(timeout=5) == 0
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)


def test_bare_interpreter_name_is_resolved_from_path(tmp_path, monkeypatch):
    executable = Path(sys.executable)
    monkeypatch.setenv('PATH', str(executable.parent))
    session = AnalysisSession(tmp_path, interpreter=executable.name, cache_dir=tmp_path / 'cache')
    try:
        assert session.interpreter == str(executable)
    finally:
        session.shutdown()


@pytest.mark.parametrize('endings', [('\n',), ('\r\n',), ('\r',), ('\n', '\r', '\r\n')])
@pytest.mark.parametrize('batch', [False, True])
def test_overlay_physical_newlines_preserve_raw_identity_and_cache(tmp_path, endings, batch):
    def ending_source(source):
        return ''.join(line + endings[i % len(endings)]
                       for i, line in enumerate(source.split('\n')[:-1]))

    helper = tmp_path / 'helper.py'
    main = tmp_path / 'main.py'
    helper_source = ending_source('from pyjs import js\n# before\u2028after\n@js\n'
                                 'def twice(value: int):\n    return value * 2\n')
    main_source = ending_source('from pyjs import js\nfrom helper import twice\n@js\n'
                               'def answer(value: int):\n    return twice(value)\n')
    sources = {str(helper): helper_source, str(main): main_source}
    for name, source in sources.items():
        compile(source, name, 'exec')
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    try:
        if batch:
            session.replace_documents([{'uri': Path(path).as_uri(), 'version': 1, 'text': text}
                                       for path, text in sources.items()])
        else:
            for path, text in sources.items():
                session.update(Path(path).as_uri(), 1, text)
        result = session.snapshot(main.as_uri())
        assert result['status'] == 'ready', result
        assert result['symbols'][0]['type'] == 'answer(value: int) -> int'
        assert result['sourceHash'] == hashlib.sha256(main_source.encode()).hexdigest()
        for path, source in sources.items():
            assert result['dependencies'][path] == hashlib.sha256(source.encode()).hexdigest()
            snapshot = session.cached_snapshot(Path(path).as_uri())
            assert snapshot is not None and snapshot['status'] == 'ready'
            assert snapshot['sourceHash'] == hashlib.sha256(source.encode()).hexdigest()
            lines = io.StringIO(source, newline=None).getvalue().split('\n')
            for item in snapshot['occurrences']:
                assert lines[item['line'] - 1][item['column']:item['endColumn']] == item['name'], item
                if item.get('definitionPath') in ('main.py', 'helper.py'):
                    definition = io.StringIO(sources[str(tmp_path / item['definitionPath'])], newline=None).getvalue().split('\n')
                    assert definition[item['definitionLine'] - 1][item['definitionColumn']:].startswith(item['name']), item
        normalized = io.StringIO(main_source, newline=None).getvalue()
        alternate = normalized if normalized != main_source else normalized.replace('\n', '\r\n')
        with pytest.raises(ValueError, match='version'):
            session.update(main.as_uri(), 1, alternate)
        session.update(main.as_uri(), 2, alternate)
        changed = session.snapshot(main.as_uri())
        assert changed['status'] == 'ready', changed
        assert not changed['cached'] and changed['revision'] > result['revision']
        assert changed['sourceHash'] == hashlib.sha256(alternate.encode()).hexdigest()
        assert session.snapshot(main.as_uri())['cached']
    finally:
        session.shutdown()
