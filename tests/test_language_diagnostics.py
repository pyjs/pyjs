import concurrent.futures
import hashlib
import subprocess
import sys
import time

import pytest

from pyjs.language.server import read_message, write_message
from pyjs.language.session import AnalysisSession

SOURCE = 'from pyjs import js\n@js\ndef answer():\n    return 42\n'
INVALID = 'from pyjs import js\n@js\ndef answer():\n    label = "🐍"; return missing\n'


@pytest.fixture
def session(tmp_path):
    service = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    try:
        yield service
    finally:
        service.shutdown()


@pytest.mark.parametrize('newline', ['\n', '\r\n', '\r'])
@pytest.mark.parametrize('imported', [False, True])
def test_compiler_errors_preserve_source_ranges_and_dependency_identity(tmp_path, session, newline, imported):
    main = tmp_path / 'main.py'
    target = tmp_path / 'helper.py' if imported else main
    main.write_text('from helper import answer\n' + SOURCE.replace('answer', 'main').replace('42', 'answer()'))
    target.write_text(SOURCE)
    source = INVALID.replace('\n', newline)
    session.update(target.as_uri(), 7, source)
    result = session.snapshot(main.as_uri())
    assert result['status'] == 'error', result
    assert result['diagnostics'] == [{
        'code': 'PYJS1001', 'severity': 'error', 'message': "Name 'missing' is not defined",
        'primary': {'file': str(target), 'start': {'line': 3, 'column': 24},
                    'end': {'line': 3, 'column': 31}, 'message': None},
        'secondary': [], 'notes': [], 'help': [],
    }]
    assert result['dependencies'][str(target)] == hashlib.sha256(source.encode()).hexdigest()
    assert target.read_text() == SOURCE
    assert session.cached_snapshot(main.as_uri()) is None
    session.update(target.as_uri(), 8, SOURCE)
    ready = session.snapshot(main.as_uri())
    assert ready['status'] == 'ready', ready
    assert ready['diagnostics'] == []
    assert session.snapshot(main.as_uri())['diagnostics'] == []
    reopened = AnalysisSession(tmp_path, cache_dir=tmp_path / 'cache')
    try:
        retained = reopened.snapshot(main.as_uri())
        assert retained['cached']
        assert retained['diagnostics'] == []
        assert reopened.snapshot(target.as_uri())['diagnostics'] == []
    finally:
        reopened.shutdown()


@pytest.mark.parametrize('newline', ['\n', '\r\n', '\r'])
def test_invalid_open_sibling_has_diagnostic_without_executing_workspace(tmp_path, session, newline):
    marker = tmp_path / 'executed'
    main = tmp_path / 'main.py'
    main.write_text('from pathlib import Path\nPath("executed").touch()\n' + SOURCE)
    sibling = tmp_path / 'draft.py'
    session.update(sibling.as_uri(), 1, '# draft' + newline + 'label = "🐍"; if True:' + newline)
    result = session.snapshot(main.as_uri())
    assert result['status'] == 'pending'
    assert result['diagnostics'] == [{
        'code': 'SyntaxError', 'severity': 'error', 'message': 'invalid syntax',
        'primary': {'file': str(sibling), 'start': {'line': 1, 'column': 13},
                    'end': {'line': 1, 'column': 15}, 'message': None},
        'secondary': [], 'notes': [], 'help': [],
    }]
    assert not marker.exists()


def test_compiler_help_and_runtime_failures(tmp_path, session):
    main = tmp_path / 'main.py'
    main.write_text(SOURCE.replace('answer():', 'answer() -> int:').replace('42', '"bad"'))
    result = session.snapshot(main.as_uri())
    assert result['diagnostics'][0]['code'] == 'PYJS1105'
    assert result['diagnostics'][0]['help'] == [
        'Change the return annotation or return values so their types match.']
    for source in ['raise ValueError("initialization failed")', 'raise SystemExit(1)']:
        main.write_text(source)
        result = session.snapshot(main.as_uri())
        assert result['status'] == 'error'
        assert result['diagnostics'] == []
        assert result['message']


def test_imported_syntax_error_is_located(tmp_path, session):
    main = tmp_path / 'main.py'
    main.write_text('import helper\n' + SOURCE)
    helper = tmp_path / 'helper.py'
    helper.write_text('def broken(:\n')
    result = session.snapshot(main.as_uri())
    assert result['status'] == 'error'
    assert result['diagnostics'][0]['code'] == 'SyntaxError'
    assert result['diagnostics'][0]['primary']['file'] == str(helper)
    assert result['diagnostics'][0]['primary']['start'] == {'line': 0, 'column': 11}


@pytest.mark.parametrize('prefix', ['"""Doc\u2028line"""\n', '# before\x1cafter\n', '\f\n'])
def test_compiler_locations_ignore_non_python_line_separators(tmp_path, session, prefix):
    main = tmp_path / 'main.py'
    main.write_text(prefix + INVALID.replace('    label', '\f\n    label'))
    result = session.snapshot(main.as_uri())
    assert result['status'] == 'error', result
    assert result['diagnostics'][0]['primary'] == {
        'file': str(main), 'start': {'line': 5, 'column': 24},
        'end': {'line': 5, 'column': 31}, 'message': None,
    }


@pytest.mark.parametrize('attribute,value', [
    ('lineno', '"3"'), ('filename', 'Path("config.toml")'), ('offset', '1.5'),
    ('end_lineno', '"3"'), ('msg', 'Path("bad")'), ('offset', 'True'),
])
def test_malformed_syntax_errors_keep_the_original_failure_message(tmp_path, session, attribute, value):
    main = tmp_path / 'main.py'
    main.write_text('from pathlib import Path\n'
                    'error = SyntaxError("bad", ("config.toml", 1, 1, "bad"))\n'
                    f'error.{attribute} = {value}\nraise error\n')
    result = session.snapshot(main.as_uri())
    assert result['status'] == 'error', result
    assert result['message'].startswith('SyntaxError: bad')
    assert result['diagnostics'] == []


def test_changed_dependency_discards_located_errors(tmp_path, session):
    main = tmp_path / 'main.py'
    main.write_text('import helper\n' + SOURCE)
    helper = tmp_path / 'helper.py'
    helper.write_text('from pathlib import Path\nfrom time import sleep\n'
                      'Path("started").touch()\n'
                      'while not Path("release").exists(): sleep(0.01)\n'
                      'raise SyntaxError("old error", (__file__, 5, 1, "old"))\n')
    with concurrent.futures.ThreadPoolExecutor() as pool:
        pending = pool.submit(session.snapshot, main.as_uri())
        try:
            deadline = time.monotonic() + 10
            while not (tmp_path / 'started').exists() and not pending.done() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert (tmp_path / 'started').exists()
            helper.write_text('VALUE = 1\n')
        finally:
            (tmp_path / 'release').touch()
        result = pending.result(timeout=15)
    assert result['status'] == 'superseded', result
    assert result['diagnostics'] == []


def test_stdio_returns_diagnostics_with_snapshot(tmp_path):
    main = tmp_path / 'main.py'
    main.write_text(SOURCE)
    child = subprocess.Popen([sys.executable, '-m', 'pyjs', 'lsp', '--root', str(tmp_path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        write_message(child.stdin, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})
        assert read_message(child.stdout)['id'] == 1
        write_message(child.stdin, {'jsonrpc': '2.0', 'id': 2, 'method': 'pyjs/moduleSnapshot',
            'params': {'uri': main.as_uri(), 'version': 3, 'text': INVALID}})
        response = read_message(child.stdout)
        assert response['id'] == 2
        assert response['result']['status'] == 'error'
        assert response['result']['version'] == 3
        assert response['result']['diagnostics'][0]['code'] == 'PYJS1001'
        write_message(child.stdin, {'jsonrpc': '2.0', 'id': 3, 'method': 'shutdown'})
        assert read_message(child.stdout)['id'] == 3
        write_message(child.stdin, {'jsonrpc': '2.0', 'method': 'exit'})
        assert child.wait(timeout=5) == 0
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)
