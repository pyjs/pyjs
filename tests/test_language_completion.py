import pytest

from pyjs.language.session import AnalysisSession


def complete(root, source, *, marker='§', documents=()):
    offset = source.index(marker)
    source = source[:offset] + source[offset + len(marker):]
    line = source[:offset].count('\n') + 1
    column = len(source[:offset].rsplit('\n', 1)[-1])
    path = root / 'example.py'
    path.write_text(source)
    session = AnalysisSession(root, cache_dir=root / '.cache')
    try:
        session.replace_documents([{'uri': path.as_uri(), 'text': source, 'version': 1}, *documents])
        return session.completion(path.as_uri(), line, column)
    finally:
        session.shutdown()


def labels(result):
    assert result['status'] == 'ready', result
    return {item['label']: item for item in result['items']}


@pytest.mark.parametrize('annotation', ['', ' -> int'])
@pytest.mark.parametrize('receiver', ['scope', 'self', 'instance', 'imported'])
def test_descriptions_do_not_analyze_unrelated_broken_bodies(tmp_path, annotation, receiver):
    broken = 'def broken(value: int)' + annotation + ':\n    return value.upper()\n'
    if receiver in ('self', 'instance'):
        broken = broken.replace('def broken(', 'def broken(self, ')
        source = ('from pyjs import js\n@js\nclass View:\n'
                  '    def __init__(self):\n        self.title = "View"\n'
                  + ''.join('    ' + line + '\n' for line in broken.splitlines()))
        if receiver == 'self':
            source += '    def render(self) -> str:\n        return self.§title\n'
        else:
            source += '@js\ndef render(view: View):\n    return view.§title\n'
    elif receiver == 'imported':
        (tmp_path / 'helper.py').write_text('from pyjs import js\n@js\n' + broken)
        source = ('from pyjs import js\nfrom helper import broken\n'
                  '@js\ndef render():\n    return br§\n')
    else:
        source = 'from pyjs import js\n@js\n' + broken + '@js\ndef render():\n    return br§\n'
    items = labels(complete(tmp_path, source))
    assert items['broken']['detail'] == 'broken(value: int) -> ' + ('int' if annotation else 'unknown')
    if receiver in ('self', 'instance'):
        assert items['title']['detail'] == 'title: str'


def test_completion_still_validates_called_function_bodies(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
def broken(value: int) -> int:
    return value.upper()
@js
def example():
    broken(1)
    return br§
''')
    assert result['status'] == 'error'
    assert 'PYJS1003' in result['message']
    assert result['items'] == []


def test_unanalyzed_member_descriptions_preserve_binding_and_properties(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
class Model:
    @staticmethod
    def render(value: int) -> str:
        return value.upper()
    @classmethod
    def repeat(cls, value: str) -> str:
        return missing
    @property
    def result(self) -> int:
        return missing
@js
def example(model: Model):
    return model.r§
''')
    items = labels(result)
    assert items['render']['detail'] == 'render(value: int) -> str'
    assert items['repeat']['detail'] == 'repeat(value: str) -> str'
    assert items['result']['detail'] == 'result: int'


def test_locals_and_shadowing_at_the_cursor(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
def other():
    unrelated = 2
    return unrelated
@js
def example(value: int):
    local = value + 1
    return loc§
''')
    items = labels(result)
    assert list(items) == ['local']
    assert items['local']['detail'] == 'local: int'
    assert items['local']['startColumn'] == 11 and items['local']['endColumn'] == 14


@pytest.mark.parametrize('generated', [False, True])
def test_constructor_and_generated_fields(tmp_path, generated):
    declaration = ('''from dataclasses import dataclass
@js
@dataclass
class Model:
    name: str
    count: int = 42
''' if generated else '''@js
class Model:
    def __init__(self):
        self.name = "hello"
        self.count = 42
''')
    result = complete(tmp_path, 'from pyjs import js\n' + declaration + '''@js
def example(value: Model):
    return value.na§
''')
    assert labels(result)['name']['detail'] == 'name: str'


@pytest.mark.parametrize('helper', ['method', 'transitive', 'function'])
@pytest.mark.parametrize('suffix', ['', 'me'])
def test_members_in_constructor_dependencies(tmp_path, helper, suffix):
    source = '''from pyjs import js
@js
class Panel:
    def __init__(self):
        self.name = "Panel"
'''
    if helper == 'function':
        source += '''        inspect_panel(self)
@js
def inspect_panel(panel: Panel):
    return panel.na§SUFFIX
'''
    else:
        source += '        self.prepare()\n'
        if helper == 'transitive':
            source += '    def prepare(self):\n        return self.inspect()\n    def inspect(self):\n'
        else:
            source += '    def prepare(self):\n'
        source += '        return self.na§SUFFIX\n'
    items = labels(complete(tmp_path, source.replace('SUFFIX', suffix)))
    assert list(items) == ['name']
    assert items['name']['detail'] == 'name: str'


def test_narrowed_receiver_and_nullable_loop(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
def example(value: str | None):
    if isinstance(value, str):
        return value.up§
    return ""
''', marker='up§')
    # Use a real identifier in the next request; a bare trailing dot is invalid Python.
    assert result['status'] == 'pending'
    result = complete(tmp_path, '''from pyjs import js
@js
def example(value: str | None):
    if isinstance(value, str):
        return value.up§
    return ""
''')
    assert 'upper' in labels(result)
    result = complete(tmp_path, '''from pyjs import js
@js
def example(values: list[str | None]):
    value: str | None = ""
    for item in values:
        value.up§
        value = item
''')
    assert 'upper' not in labels(result)


def test_mid_identifier_unicode_and_no_suffix_duplication(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
def example():
    greeting = "hi"
    "🐍"; gre§eting
''')
    item = labels(result)['greeting']
    assert item['startColumn'] == 9 and item['endColumn'] == 17


def test_unsaved_imports(tmp_path):
    sibling = tmp_path / 'model.py'
    sibling.write_text('from pyjs import js\n@js\nclass Model:\n    def __init__(self):\n        self.saved = 1\n')
    draft = sibling.read_text().replace('saved', 'draft')
    result = complete(tmp_path, '''from pyjs import js
from model import Model
@js
def example(model: Model):
    return model.dr§
''', documents=[{'uri': sibling.as_uri(), 'text': draft, 'version': 3}])
    assert list(labels(result)) == ['draft']
    assert 'saved' in sibling.read_text()


def test_invalid_overlay_prevents_module_execution(tmp_path):
    sentinel = tmp_path / 'executed'
    source = f'''from pathlib import Path
Path({str(sentinel)!r}).touch()
from pyjs import js
@js
def example():
    local = 1
    return loc§
'''
    result = complete(tmp_path, source, documents=[{
        'uri': (tmp_path / 'sibling.py').as_uri(), 'text': 'def incomplete(', 'version': 1}])
    assert result['status'] == 'pending'
    assert not sentinel.exists()


def test_completion_does_not_poison_snapshots(tmp_path):
    path = tmp_path / 'example.py'
    source = 'from pyjs import js\n@js\ndef example(value: int):\n    return value\n'
    path.write_text(source)
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / '.cache')
    try:
        before = session.snapshot(path.as_uri())
        assert before['status'] == 'ready'
        result = session.completion(path.as_uri(), 4, 14)
        assert 'value' in labels(result)
        after = session.snapshot(path.as_uri())
        assert after['cached'] and after['occurrences'] == before['occurrences']
        assert 'items' not in after
    finally:
        session.shutdown()


@pytest.mark.parametrize('line,column', [(0,0),(1,-1),(99,0),(1,999),(True,0),(1,False)])
def test_invalid_coordinates(tmp_path, line, column):
    path = tmp_path / 'example.py'
    path.write_text('pass\n')
    session = AnalysisSession(tmp_path, cache_dir=tmp_path / '.cache')
    try:
        with pytest.raises(ValueError, match='position'):
            session.completion(path.as_uri(), line, column)
    finally:
        session.shutdown()


def test_unicode_normalization(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
def example():
    Kelvin = 273
    return K§
''')
    assert 'Kelvin' in labels(result)


def test_union_fields_do_not_claim_only_one_alternatives_type(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
class First:
    def __init__(self):
        self.value = 1
        self.only_first = 2
@js
class Second:
    def __init__(self):
        self.value = "two"
@js
def example(model: First | Second):
    return model.va§
''')
    assert labels(result)['value']['detail'] == 'value: int | value: str'


def test_module_initializers_run_but_application_functions_do_not(tmp_path):
    sentinel = tmp_path / 'executed'
    result = complete(tmp_path, f'''from pathlib import Path
from pyjs import js
Path({str(sentinel)!r}).write_text("initialized")
@js
def example():
    local = 1
    return loc§
''')
    assert list(labels(result)) == ['local']
    assert sentinel.read_text() == 'initialized'


def test_lsp_completion(tmp_path):
    import subprocess
    import sys

    from pyjs.language.server import read_message, write_message

    path = tmp_path / 'example.py'
    source = 'from pyjs import js\n@js\ndef example(value: int):\n    return va\n'
    process = subprocess.Popen([sys.executable, '-m', 'pyjs', 'lsp', '--root', str(tmp_path)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        write_message(process.stdin, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'})
        assert read_message(process.stdout)['id'] == 1
        write_message(process.stdin, {'jsonrpc': '2.0', 'id': 2, 'method': 'pyjs/completion',
            'params': {'uri': path.as_uri(), 'version': 1, 'text': source, 'line': 4, 'column': 13}})
        response = read_message(process.stdout)
        assert response['id'] == 2
        assert 'value' in labels(response['result'])
        write_message(process.stdin, {'jsonrpc': '2.0', 'id': 3, 'method': 'shutdown'})
        assert read_message(process.stdout)['id'] == 3
        write_message(process.stdin, {'jsonrpc': '2.0', 'method': 'exit'})
        assert process.wait(timeout=5) == 0
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_method_before_its_constructor_sees_declared_fields(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
class Model:
    def read(self):
        return self.na§
    def __init__(self):
        self.name = "hello"
''')
    assert labels(result)['name']['detail'] == 'name: str'


def test_loop_backedge_invalidates_an_earlier_guard(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
def example(value: str | None, enabled: bool):
    if value is None:
        return
    while enabled:
        value.up§
        value = None
''')
    assert 'upper' not in labels(result)


@pytest.mark.parametrize('replacement,expected', [
    ('value = None', False),
    ('value = value.strip()', True),
])
def test_partial_call_after_a_loop_guard(tmp_path, replacement, expected):
    result = complete(tmp_path, '''from pyjs import js
@js
def example(value: str | None, enabled: bool):
    if value is None:
        return
    while enabled:
        value.up§()
        ''' + replacement + '\n')
    assert ('upper' in labels(result)) == expected


def test_partial_return_with_a_declared_result(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
def example(value: str) -> str:
    return value.up§()
''')
    assert 'upper' in labels(result)


@pytest.mark.parametrize('body', [
    'result = value.up§per()\n    return result',
    'return len(value.up§per())',
    'result = len(val§ue)\n    return result',
])
def test_complete_identifiers_in_larger_expressions(tmp_path, body):
    result = complete(tmp_path, 'from pyjs import js\n@js\ndef example(value: str):\n    ' + body + '\n')
    assert {'upper', 'value'}.intersection(labels(result))


def test_exception_exit_invalidates_receiver_proof(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
def example(value: str | None, enabled: bool):
    if value is None:
        return
    try:
        if enabled:
            value = None
            raise ValueError("failed")
    finally:
        value.up§()
''')
    assert 'upper' not in labels(result)


def test_partial_result_binding_uses_the_completed_member_type(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
def example(value: str):
    result = value.up§()
    return result
''')
    assert 'upper' in labels(result)


def test_partial_result_candidates_have_their_own_types(tmp_path):
    counter = tmp_path / 'initializations'
    source = f'''from pathlib import Path
from pyjs import js
counter = Path({str(counter)!r})
counter.write_text(counter.read_text() + 'x' if counter.exists() else 'x')
@js
def green():
    return 42
@js
def greet():
    return "hello"
@js
def example():
    result = gre§()
    return result.upper()
'''
    result = complete(tmp_path, source)
    assert list(labels(result)) == ['greet']
    assert counter.read_text() == 'x'


def test_partial_assignment_does_not_revive_a_loop_guard(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
def example(value: str | None, enabled: bool):
    if value is None:
        return
    while enabled:
        result = value.up§()
        value = None
        print(result)
''')
    assert labels(result) == {}


def test_unrelated_type_errors_are_not_silently_hidden(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
def example(value: str):
    result = value.up§per()
    return missing
''')
    assert result['status'] == 'error'
    assert result['items'] == []


def test_nested_function_scope(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
def outer(value: int):
    def inner(argument: int):
        local = argument + value
        return loc§
    return inner(value)
''')
    assert labels(result)['local']['detail'] == 'local: int'


def test_comprehension_binding(tmp_path):
    result = complete(tmp_path, '''from pyjs import js
@js
def example(values: list[str]):
    return [val§.upper() for value in values]
''')
    assert labels(result)['value']['detail'] == 'value: str'
