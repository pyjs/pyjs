import textwrap

import pytest

from .test_transpiler import execute


def assert_python_result(tmp_path, source):
    namespace = {}
    exec(source, namespace)
    assert execute(tmp_path, source) == str(namespace['main']())


@pytest.mark.parametrize('body', [
    'values = [1]\nother = values\nvalues += [2]\nreturn len(other)',
    'values = [1]\nother = values\nvalues += values\nreturn len(other) * 10 + other[-1]',
    'values: list[int] = []\nextend(values)\nreturn len(values)',
    'box = Box()\nother = box.values\nbox.values += [1]\nreturn len(other)',
    'rows = [[1]]\nother = rows[0]\nrows[0] += [2]\nreturn len(other)',
    'values: list[int] = []\nother = values\nfor i in range(3):\n    values += [i]\nreturn len(other)',
])
def test_augmented_list_concatenation_preserves_aliases(tmp_path, body):
    assert_python_result(tmp_path, '''
class Box:
    def __init__(self):
        self.values: list[int] = []

def extend(values: list[int]) -> None:
    values += [1]

def main() -> int:
''' + textwrap.indent(body, '    '))


@pytest.mark.parametrize('kind,value,read', [
    ('Box', 'Box(7)', 'result.value'),
    ('list[int]', '[7]', 'result[0]'),
    ('tuple[int, int]', '(7, 3)', 'result[0]'),
])
@pytest.mark.parametrize('ending', ['return', 'return None', ''])
def test_nullable_storage_and_returns(tmp_path, kind, value, read, ending):
    assert_python_result(tmp_path, f'''
class Box:
    def __init__(self, value: int):
        self.value = value

def choose(flag: bool) -> {kind} | None:
    result: {kind} | None = None
    if flag:
        result = {value}
        return result
    {ending}

def clear(value: {kind} | None) -> {kind} | None:
    value = None
    return value

def main() -> int:
    result = choose(True)
    score = 0
    if result is not None:
        score = {read}
    result = None
    if choose(False) is None:
        score += 10
    if clear(choose(True)) is None:
        score += 100
    return score
''')


@pytest.mark.parametrize('values,method', [
    ('[[1], [], [2, 3]]', ''),
    ('[0.0, 1.0, -1.5]', ''),
    ('[(0, 0), (1, 2)]', ''),
    ('[(), ()]', ''),
    ('[Box(0), Box(2)]', 'def __bool__(self) -> bool:\n    return self.value > 0'),
    ('[Box(0), Box(2)]', 'def __len__(self) -> int:\n    return self.value'),
    ('[Box(0), Box(2)]', ''),
])
def test_comprehension_filters_use_python_truth(tmp_path, values, method):
    assert_python_result(tmp_path, '''
class Box:
    def __init__(self, value: int):
        self.value = value
''' + textwrap.indent(method, '    ') + f'''

def main() -> int:
    values = {values}
    selected = [1 for value in values if value]
    return len(selected)
''')


def test_comprehension_nested_tuple_target(tmp_path):
    assert_python_result(tmp_path, '''
def main() -> int:
    values = [i + p + q for i, (p, q) in [(1, (2, 3)), (4, (5, 6))]]
    return values[0] * 100 + values[1]
''')


@pytest.mark.parametrize('name', ['missing', 'Box', 'data', 'sqrt', 'anonymous'])
@pytest.mark.parametrize('first', [True, False])
def test_exports_require_python_functions(name, first):
    from pyjs.webassembly import transpile_webassembly

    exports = (name, 'main') if first else ('main', name)
    with pytest.raises(ValueError, match=f"export '{name}' must name a function defined with def"):
        transpile_webassembly('''
from math import sqrt
class Box:
    pass
data = 1
anonymous = lambda: 1
def main() -> int:
    return 1
''', exports=exports)


@pytest.mark.parametrize('body', [
    'lo: float = 0\nhi: float = 1\nreturn (lo + hi) / 2 * 3.0',
    'value: float = 2 * 3\nreturn value * 0.25',
    'value: float = 1\nvalue = 3\nreturn value * 0.5',
    'value: float = len([1, 2, 3])\nreturn value / 2',
    'step: float = 2\ntotal = 0.0\nfor item in range(3):\n    total += step * 0.5\nreturn total / 2',
    'value: object = 1\nreturn 1.5',
    'value: int | None = 5\nreturn 1.5',
])
def test_local_annotations_do_not_coerce_inferred_scalar_storage(tmp_path, body):
    assert_python_result(tmp_path, 'def main() -> float:\n' + textwrap.indent(body, '    '))


@pytest.mark.parametrize('body', [
    'value: object = [7]\nreturn 7 if value is not None else 0',
    'value: object = (7, 2)\nreturn 7 if value is not None else 0',
    'value: object = Box(7)\nreturn 7 if value is not None else 0',
    'values: object = [1, 2]\nvalues = [3]\nreturn len(values)',
    'values: Iterable[int] = [1, 2]\nvalues = [3]\nreturn len(values)',
    'value: Box | Other = Box(1)\nvalue = Box(3)\nreturn value.value',
    'kept = [1]\nalias: object = kept\nkept.append(2)\nreturn len(kept)',
    'value: list[int] | tuple[int, int] = [1, 2]\nreturn 7',
    'events: list[int] = []\nvalue: object = take(events)\nreturn len(events)',
])
def test_broad_reference_annotations_keep_inferred_storage(tmp_path, body):
    assert_python_result(tmp_path, '''
from typing import Iterable

class Box:
    def __init__(self, value: int):
        self.value = value

class Other:
    def __init__(self, value: int):
        self.value = value

def take(events: list[int]) -> list[int]:
    events.append(7)
    return [3]

def main() -> int:
''' + textwrap.indent(body, '    '))


@pytest.mark.parametrize('body', [
    'values: list[float] = [item for item in [1, 2]]\nreturn len(values)',
    'pair = (1, 2)\nvalues: tuple[float, float] = pair\nreturn int(values[0])',
    'rows: list[list[int] | None] = [[item] for item in [1, 2]]\nreturn len(rows)',
    'values: list[float] = list([1, 2])\nreturn len(values)',
    'values: list[float] = [1] + [2]\nreturn len(values)',
    'values: tuple[list[int] | None, int] = pair()\nreturn values[1]',
])
def test_incompatible_reference_initializers_have_located_diagnostics(body):
    from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly

    source = ('def pair() -> tuple[list[int], int]:\n    return ([1], 2)\n'
              'def main() -> int:\n' + textwrap.indent(body, '    '))
    with pytest.raises(WebAssemblyUnsupported, match=r'storage conversion.*at line [0-9]+'):
        transpile_webassembly(source)


@pytest.mark.parametrize('body', [
    'value: tuple[int, list[int] | None] = (1, [2])\n'
    'return 0 if value[1] is None else len(value[1])',
    'value: list[int] | None = None\ncount = 0\n'
    'value, count = [1, 2], 2\nreturn len(value) + count',
])
def test_unnarrowed_nullable_length_has_located_diagnostic(body):
    from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly

    with pytest.raises(WebAssemblyUnsupported, match=r'len requires a narrowed.*at line [0-9]+'):
        transpile_webassembly('def main() -> int:\n' + textwrap.indent(body, '    '))


@pytest.mark.parametrize('value,expression', [
    ('float32(0.1)', 'float(VALUE) * 3.0'),
    ('[1, 2]', 'len(VALUE)'),
])
def test_unsupported_imported_values_have_located_diagnostics(tmp_path, monkeypatch, value, expression):
    import sys

    from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly

    name = 'wasm_constant_probe'
    (tmp_path / f'{name}.py').write_text(
        'from typing import Final\nfrom pyjs import JS, float32\n'
        f'VALUE: Final[JS] = {value}\n'
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        with pytest.raises(WebAssemblyUnsupported, match=r'at line [0-9]+'):
            transpile_webassembly(
                f'from {name} import VALUE\ndef main() -> float:\n'
                f'    return float({expression})\n'
            )
    finally:
        sys.modules.pop(name, None)


@pytest.mark.parametrize('body', [
    'value: object = empty()\nreturn 1 if value else 2',
    'value: object = empty()\nreturn 1 if not value else 2',
    'value: object = empty()\nif value:\n    return 1\nreturn 2',
    'value: object = empty()\ncount = 0\nwhile value:\n    count += 1\n    if count == 3:\n        break\nreturn count',
    'value: object = empty()\nreturn len([i for i in [1, 2] if value])',
    'pair = ()\nvalue: object = pair\nreturn 1 if value else 2',
    'value: object = Falsy()\nreturn 1 if value else 2',
    'value: object = Zero()\nreturn 1 if value else 2',
])
def test_object_reference_truth_requires_narrowing(body):
    from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly

    source = ('''
class Falsy:
    def __bool__(self) -> bool:
        return False

class Zero:
    def __len__(self) -> int:
        return 0

def empty() -> list[int]:
    return []

def main() -> int:
''' + textwrap.indent(body, '    '))
    with pytest.raises(WebAssemblyUnsupported, match=r'truth test requires a narrowed.*at line [0-9]+'):
        transpile_webassembly(source)


@pytest.mark.parametrize('nullable', [False, True])
@pytest.mark.parametrize('kind', ['A', 'B'])
@pytest.mark.parametrize('read', ['value.get()', 'value.twice(5)', 'value + 1'])
def test_union_method_receivers_match_physical_storage(tmp_path, nullable, kind, read):
    from pyjs.webassembly import WebAssemblyUnsupported, transpile_webassembly

    source = '''
class A:
    def __init__(self, value: int):
        self.value = value

    def get(self) -> int:
        return 1

    def twice(self, number: int) -> int:
        return number * 2

    def __add__(self, number: int) -> int:
        return self.value + number + 100

class B:
    def __init__(self, value: int):
        self.value = value

    def get(self) -> int:
        return 2

    def twice(self, number: int) -> int:
        return number * 3

    def __add__(self, number: int) -> int:
        return self.value + number + 200

'''
    body = f'value: A | B{" | None" if nullable else ""} = {kind}(1)\n'
    body += f'if value is not None:\n    return {read}\nreturn 0' if nullable else f'return {read}'
    source += 'def main() -> int:\n' + textwrap.indent(body, '    ')
    if kind == 'A':
        assert_python_result(tmp_path, source)
    else:
        with pytest.raises(WebAssemblyUnsupported, match=r'storage conversion.*at line [0-9]+'):
            transpile_webassembly(source)
