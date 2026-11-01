import math
import subprocess
import textwrap

import pytest

from pyjs.webassembly import memory

from .test_transpiler import execute


@pytest.mark.parametrize('body', [
    '''
    value = 3
    selected = [value for value in range(value)]
    return len(selected) * 10 + value
    ''',
    '''
    selected = [[value for value in range(value)] for value in range(3)]
    return len(selected[-1])
    ''',
    '''
    selected = [value for value in range(3) for value in range(value)]
    return len(selected)
    ''',
    '''
    value: int8 = int8(7)
    selected = [value for value in range(130)]
    return selected[-1]
    ''',
    '''
    value = 1000
    selected = [value for value in [int8(127), int8(-128)]]
    return int(selected[-1] - 1)
    ''',
], ids=['outer-iterable', 'nested-shadow', 'repeated-target',
        'ordinary-target', 'represented-target'])
def test_comprehension_bindings_match_python(tmp_path, body):
    source = ('from pyjs import int8\n'
              'def main() -> int:\n' + textwrap.indent(textwrap.dedent(body), '    '))
    namespace = {}
    exec(source, namespace)
    assert execute(tmp_path, source) == str(namespace['main']())


@pytest.mark.parametrize('expression', ['pair(events)', '(take(events), 5)'])
def test_tuple_length_evaluates_its_argument_once(tmp_path, expression):
    source = f'''
def take(events: list[int]) -> int:
    events.append(9)
    return 4

def pair(events: list[int]) -> tuple[int, int]:
    return (take(events), 5)

def main() -> int:
    events = [0]
    return len({expression}) * 10 + len(events)
'''
    namespace = {}
    exec(source, namespace)
    assert execute(tmp_path, source) == str(namespace['main']()) == '22'


@pytest.mark.parametrize('outer', ['[10]', '[]'])
def test_zip_does_not_probe_unreached_nested_strict_source(tmp_path, outer):
    source = f'''
def main() -> int:
    total = 0
    outer: list[int] = {outer}
    for left, pair in zip(outer, zip([1], [2, 3], strict=True)):
        total += left + pair[0] + pair[1]
    return total
'''
    namespace = {}
    exec(source, namespace)
    assert execute(tmp_path, source) == str(namespace['main']())


@pytest.mark.parametrize('body', ['return value', 'break'])
def test_enumerate_does_not_overflow_before_current_body(tmp_path, body):
    source = f'''
def main() -> int:
    for index, value in enumerate([1, 2], 9223372036854775807):
        {body}
    return 1
'''
    assert execute(tmp_path, source) == '1'


def test_enumerate_detects_overflow_after_source_mutation(tmp_path):
    source = '''
def main() -> int:
    values = [1]
    for index, value in enumerate(values, 9223372036854775807):
        if value == 2:
            return index
        values.append(2)
    return 0
'''
    with pytest.raises(subprocess.CalledProcessError) as caught:
        execute(tmp_path, source)
    assert 'RuntimeError: unreachable' in caught.value.stderr


@pytest.mark.parametrize('offset', [2**32, -(2**32), -1, 2**32 - 1])
@pytest.mark.parametrize('kind,value', [('i32', '99'), ('f32', '99.0'), ('f64', '99.0')])
@pytest.mark.parametrize('operation', ['load', 'store'])
def test_memory_rejects_full_width_invalid_offsets(tmp_path, offset, kind, value, operation):
    name = f'{operation}_{kind}'
    arguments = f'{offset}, {value}' if operation == 'store' else str(offset)
    source = f'''
from pyjs.webassembly import {name}
def main() -> int:
    {name}({arguments})
    return 0
'''
    memory.reset_memory()
    namespace = {}
    exec(source, namespace)
    with pytest.raises(IndexError):
        namespace['main']()
    with pytest.raises(subprocess.CalledProcessError) as caught:
        execute(tmp_path, source)
    assert 'RuntimeError:' in caught.value.stderr


@pytest.mark.parametrize('pages', [-(2**32), -1, 65536, 2**32, 2**32 + 1])
def test_memory_growth_rejects_unrepresentable_sizes(tmp_path, pages):
    memory.reset_memory()
    assert memory.grow_memory(pages) == -1
    assert memory.memory_byte_length() == memory.PAGE_BYTES
    assert execute(tmp_path, f'''
from pyjs.webassembly import grow_memory
def main() -> int:
    return grow_memory({pages})
''') == '-1'


@pytest.mark.parametrize('value', [1e40, -1e40, 1e30])
def test_float32_memory_rounding_matches_wasm(tmp_path, value):
    memory.reset_memory()
    memory.store_f32(0, value)
    expected = memory.load_f32(0)
    result = float(execute(tmp_path, f'''
from pyjs.webassembly import load_f32, store_f32
def main() -> float:
    store_f32(0, {value})
    return load_f32(0)
'''))
    assert result == expected
    if abs(value) > 1e38:
        assert math.isinf(result)
