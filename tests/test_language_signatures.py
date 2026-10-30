import pytest

from pyjs.language.session import AnalysisSession


def query(root, source, *, documents=()):
    offset = source.index('§')
    source = source.replace('§', '')
    line = source[:offset].count('\n') + 1
    column = len(source[:offset].rsplit('\n', 1)[-1])
    path = root / 'example.py'
    path.write_text(source)
    session = AnalysisSession(root, cache_dir=root / '.cache')
    try:
        session.replace_documents([{'uri': path.as_uri(), 'text': source, 'version': 7}, *documents])
        return session.signatures(path.as_uri(), line, column)
    finally:
        session.shutdown()


def signature(result):
    assert result['status'] == 'ready', result
    assert len(result['signatures']) == 1, result
    assert result['version'] == 7
    return result['signatures'][0]


@pytest.mark.parametrize('arguments,active', [('§1, "a"', 0), ('1, §"a"', 1),
    ('1, title=§"a"', 1), ('1, title="a"§', 1)])
def test_function_parameters_and_documentation(tmp_path, arguments, active):
    item = signature(query(tmp_path, '''from pyjs import js
@js
def render(count: int, title: str = "Default") -> str:
    """Render the requested title."""
    return title * count
@js
def example():
    return render(''' + arguments + ''')
'''))
    assert item['label'] == "render(count: int, title: str = 'Default') -> str"
    assert item['parameters'] == ['count: int', "title: str = 'Default'"]
    assert item['activeParameter'] == active
    assert item['documentation'] == 'Render the requested title.'


def test_bound_method_and_unicode_position(tmp_path):
    item = signature(query(tmp_path, '''from pyjs import js
@js
class Model:
    def render(self, title: str, repeat: int = 2) -> str:
        return title * repeat
@js
def example(model: Model):
    "🐍"; return model.render("hello", §3)
'''))
    assert item['parameters'] == ['title: str', 'repeat: int = 2']
    assert item['activeParameter'] == 1


def test_innermost_multiline_call(tmp_path):
    item = signature(query(tmp_path, '''from pyjs import js
@js
def inner(value: int) -> int:
    return value
@js
def outer(value: int) -> str:
    return str(value)
@js
def example():
    return outer(
        inner(§1)
    )
'''))
    assert item['label'] == 'inner(value: int) -> int'
    assert item['activeParameter'] == 0


def test_generic_call_uses_specialized_types(tmp_path):
    item = signature(query(tmp_path, '''from pyjs import js
@js
def identity[T](value: T) -> T:
    return value
@js
def example():
    return identity(§"hello")
'''))
    assert item['label'] == 'identity(value: str) -> str'


def test_positional_only_and_keyword_only(tmp_path):
    item = signature(query(tmp_path, '''from pyjs import js
@js
def render(value: int, /, *, title: str = "Default") -> str:
    return title * value
@js
def example():
    return render(2, title=§"hello")
'''))
    assert item['label'] == "render(value: int, /, *, title: str = 'Default') -> str"
    assert item['activeParameter'] == 1


@pytest.mark.parametrize('generated', [False, True])
def test_constructor(tmp_path, generated):
    declaration = ('''from dataclasses import dataclass
@js
@dataclass
class Model:
    title: str
    count: int = 2
''' if generated else '''@js
class Model:
    def __init__(self, title: str, count: int = 2):
        self.title = title
        self.count = count
''')
    item = signature(query(tmp_path, 'from pyjs import js\n' + declaration + '''@js
def example():
    return Model("hello", §3)
'''))
    assert item['label'] == 'Model(title: str, count: int = 2) -> Model'
    assert item['activeParameter'] == 1


def test_invalid_overlay_prevents_execution(tmp_path):
    sentinel = tmp_path / 'executed'
    result = query(tmp_path, f'''from pathlib import Path
Path({str(sentinel)!r}).touch()
from pyjs import js
@js
def example():
    return str(§1)
''', documents=[{'uri': (tmp_path / 'sibling.py').as_uri(), 'text': 'def incomplete(', 'version': 1}])
    assert result['status'] == 'pending'
    assert not sentinel.exists()


def test_outside_call(tmp_path):
    result = query(tmp_path, '''from pyjs import js
@js
def example():
    return str(1)§
''')
    assert result['status'] == 'ready'
    assert result['signatures'] == []


@pytest.mark.parametrize('arguments,active', [('1, §2, 3', 1), ('1, size=§2', 2)])
def test_variadic_parameters(tmp_path, arguments, active):
    item = signature(query(tmp_path, '''from pyjs import js
@js
def total(first: int, *values: int, **extras: int) -> int:
    return first + sum(values) + sum(extras.values())
@js
def example():
    return total(''' + arguments + ''')
'''))
    assert item['parameters'] == ['first: int', '*values: int', '**extras: int']
    assert item['activeParameter'] == active


def test_callable_parameter(tmp_path):
    item = signature(query(tmp_path, '''from collections.abc import Callable
from pyjs import js
@js
def example(callback: Callable[[str, int], bool]):
    return callback("hello", §2)
'''))
    assert item['parameters'] == ['arg0: str', 'arg1: int']
    assert item['label'] == 'callback(arg0: str, arg1: int) -> bool'
    assert item['activeParameter'] == 1


def test_loop_invalidation_does_not_publish_provisional_signature(tmp_path):
    result = query(tmp_path, '''from pyjs import js
@js
def example(value: str | None, enabled: bool):
    if value is None:
        return
    while enabled:
        value.replace(§"a", "b")
        value = None
''')
    assert result['status'] == 'error', result
    assert result['signatures'] == []


def test_unsaved_import_changes_parameter_types(tmp_path):
    sibling = tmp_path / 'model.py'
    saved = 'from pyjs import js\n@js\ndef render(value: int) -> int:\n    return value\n'
    sibling.write_text(saved)
    item = signature(query(tmp_path, '''from pyjs import js
from model import render
@js
def example():
    return render(§"hello")
''', documents=[{'uri': sibling.as_uri(), 'text': saved.replace('int', 'str'), 'version': 2}]))
    assert item['label'] == 'render(value: str) -> str'
    assert sibling.read_text() == saved


def test_async_call(tmp_path):
    item = signature(query(tmp_path, '''from pyjs import js
@js
async def render(value: int) -> str:
    return str(value)
@js
async def example():
    return await render(§1)
'''))
    assert item['parameters'] == ['value: int']
    assert item['label'] == 'render(value: int) -> str'


def test_partial_call_is_pending(tmp_path):
    result = query(tmp_path, '''from pyjs import js
@js
def example():
    return str(§
''')
    assert result['status'] == 'pending'
    assert result['signatures'] == []


@pytest.mark.parametrize('arguments,active', [('*(1, 2), §3', 2), ('§*(1, 2), 3', None)])
def test_starred_arguments_do_not_shift_the_active_parameter(tmp_path, arguments, active):
    item = signature(query(tmp_path, '''from pyjs import js
@js
def total(first: int, second: int, third: int) -> int:
    return first + second + third
@js
def example():
    return total(''' + arguments + ''')
'''))
    assert item['activeParameter'] == active


def test_union_receiver_preserves_alternative_signatures(tmp_path):
    result = query(tmp_path, '''from pyjs import js
@js
class First:
    def render(self, text: str = "first") -> str:
        return text
@js
class Second:
    def render(self, text: str = "second") -> int:
        return len(text)
@js
def example(model: First | Second):
    return model.render(§"hello")
''')
    assert result['status'] == 'ready', result
    assert {item['label'] for item in result['signatures']} == {
        "model.render(text: str = 'first') -> str",
        "model.render(text: str = 'second') -> int"}


def test_lsp_signature_query(tmp_path):
    import subprocess
    import sys

    from pyjs.language.server import read_message, write_message

    path = tmp_path / 'example.py'
    source = ('from pyjs import js\n@js\ndef render(value: int) -> str:\n'
              '    return str(value)\n@js\ndef example():\n    return render(1)\n')
    process = subprocess.Popen([sys.executable, '-m', 'pyjs', 'lsp', '--root', str(tmp_path)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        write_message(process.stdin, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'})
        initialized = read_message(process.stdout)
        assert initialized['id'] == 1
        assert initialized['result']['capabilities']['experimental']['pyjsSourceQueries'] == {
            'schemaVersion': 1, 'methods': ['pyjs/completion', 'pyjs/signatureHelp']}
        write_message(process.stdin, {'jsonrpc': '2.0', 'id': 2, 'method': 'pyjs/signatureHelp',
            'params': {'uri': path.as_uri(), 'version': 7, 'text': source, 'line': 7, 'column': 18}})
        response = read_message(process.stdout)
        assert response['id'] == 2
        assert signature(response['result'])['label'] == 'render(value: int) -> str'
        write_message(process.stdin, {'jsonrpc': '2.0', 'id': 3, 'method': 'shutdown'})
        assert read_message(process.stdout)['id'] == 3
        write_message(process.stdin, {'jsonrpc': '2.0', 'method': 'exit'})
        assert process.wait(timeout=5) == 0
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


@pytest.mark.parametrize('expression', ['render(§)', 'render(§"wrong type")'])
@pytest.mark.parametrize('statement', ['', 'return '])
def test_incomplete_arguments_show_declaration(tmp_path, expression, statement):
    sentinel = tmp_path / 'initializations'
    item = signature(query(tmp_path, f'''from pathlib import Path
counter = Path({str(sentinel)!r})
counter.write_text(counter.read_text() + "x" if counter.exists() else "x")
from pyjs import js
@js
def render(value: int, title: str = "Default") -> str:
    return title * value
@js
def example():
    ''' + statement + expression + '\n'))
    assert item['label'] == "render(value: int, title: str = 'Default') -> str"
    assert item['activeParameter'] == 0
    assert sentinel.read_text() == 'x'


def test_incomplete_method_still_checks_loop_flow(tmp_path):
    result = query(tmp_path, '''from pyjs import js
@js
def example(value: str | None, enabled: bool):
    if value is None:
        return
    while enabled:
        value.replace(§)
        value = None
''')
    assert result['status'] == 'error', result
    assert result['signatures'] == []


def test_incomplete_assignment_uses_the_known_result_type(tmp_path):
    result = query(tmp_path, '''from pyjs import js
@js
def render(value: int) -> str:
    return str(value)
@js
def example():
    result = render(§)
    return result.upper()
''')
    assert signature(result)['label'] == 'render(value: int) -> str'


def test_incomplete_assignment_rejects_incompatible_later_use(tmp_path):
    result = query(tmp_path, '''from pyjs import js
@js
def render(value: int) -> int:
    return value
@js
def example():
    result = render(§)
    return result.upper()
''')
    assert result['status'] == 'error', result
    assert result['signatures'] == []


def test_incomplete_assignment_does_not_invent_a_generic_binding(tmp_path):
    result = query(tmp_path, '''from pyjs import js
@js
def identity[T](value: T) -> T:
    return value
@js
def example():
    result = identity(§)
    return result.upper()
''')
    assert result['status'] == 'error', result
    assert result['signatures'] == []


@pytest.mark.parametrize('expression', ['outer(render(§))', '(await render(§)).upper()'])
def test_nested_incomplete_call_preserves_result_modifiers(tmp_path, expression):
    async_word = 'async ' if 'await' in expression else ''
    result = query(tmp_path, '''from pyjs import js
@js
''' + async_word + '''def render(value: int) -> str:
    return str(value)
@js
def outer(value: str) -> int:
    return len(value)
@js
''' + async_word + '''def example():
    return ''' + expression + '\n')
    assert signature(result)['label'] == 'render(value: int) -> str'


def test_assigned_incomplete_call_still_checks_loop_flow(tmp_path):
    result = query(tmp_path, '''from pyjs import js
@js
def example(value: str | None, enabled: bool):
    if value is None:
        return
    while enabled:
        result = value.replace(§)
        value = None
        print(result)
''')
    assert result['status'] == 'error', result
    assert result['signatures'] == []


def test_incomplete_constructor_can_supply_known_instance_fields(tmp_path):
    result = query(tmp_path, '''from pyjs import js
@js
class Model:
    def __init__(self, value: str):
        self.value = value
@js
def example():
    result = Model(§)
    return result.value.upper()
''')
    assert signature(result)['label'] == 'Model(value: str) -> Model'


def test_incomplete_overloads_do_not_select_an_arbitrary_result(tmp_path):
    result = query(tmp_path, '''from typing import overload
from pyjs import js
@overload
def render(value: int) -> int: ...
@overload
def render(value: str) -> str: ...
@js
def render(value: object) -> object:
    return value
@js
def example():
    result = render(§)
    return result.upper()
''')
    assert result['status'] == 'error', result
    assert result['signatures'] == []
