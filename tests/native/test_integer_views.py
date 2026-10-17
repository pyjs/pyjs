"""Inferred integer views preserve bool; integer-only ABIs require conversion."""

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM

READ = '''
from typing import overload
@overload
def read(key: int) -> int | None: ...
@overload
def read(key: str) -> int | str | None: ...
def read(key: int | str) -> int | str | None:
    values: list[int | str | None] = [True, False, 4, None, 0]
    return values[key] if isinstance(key, int) else key
'''


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("source", ["overload", "narrowed"])
def test_inferred_integer_expression_joins(tmp_path, optimize, source):
    load = ("value = read(index)" if source == "overload" else '''
    values: list[int | str | None] = [True, False, 4, None, 0]
    value = values[index]
    if isinstance(value, str):
        return value
''')
    comparison = LLVM().assert_matches_python(READ + f'''
from pyjs.native import gc_collect, gc_set_threshold
def fail() -> int | None:
    raise ValueError('unselected')
def render(index: int, flag: bool) -> str:
    {load}
    chosen = value if flag else None
    fallback = value if value is not None else -1
    either = value or read(2)
    literal_default = value or 8080
    nested_default = (value or read(index)) or 10
    both = value and read(1)
    nested = (value or read(2)) if flag else (value and read(1))
    untouched = chosen if True else fail()
    short_or = read(0) or fail()
    short_and = read(1) and fail()
    converted: int | None = int(value) if value is not None else None
    gc_collect()
    return '|'.join([str(chosen), repr(fallback), str(either), str(both),
                     str(literal_default), str(nested_default), str(value or 5),
                     str(isinstance(literal_default, bool)), str(read(index) or 5),
                     str(nested), str(untouched), str(short_or), str(short_and),
                     str(converted), str(isinstance(chosen, bool))])
def main() -> str:
    gc_set_threshold(1)
    output: list[str] = []
    for index in [0, 1, 2, 3, 4]:
        output.append(render(index, True))
        output.append(render(index, False))
    return ';'.join(output)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("reader", [
    "lambda: str(value)",
    "(lambda: lambda: str(value))()",
    "lambda: ','.join([str(value) for _ in [1, 2]])",
    "lambda: ','.join(str(value) for _ in [1, 2])",
])
def test_inferred_integer_cells_share_layout_with_nested_readers(tmp_path, optimize, reader):
    comparison = LLVM().assert_matches_python(READ + f'''
from collections.abc import Callable
from pyjs.native import gc_collect, gc_set_threshold
def plain() -> int | None:
    return None
def main() -> str:
    gc_set_threshold(1)
    value = plain()
    reader: Callable[[], str] = {reader}
    output: list[str] = [reader()]
    for index in [0, 1, 2, 3, 4]:
        value = read(index)
        gc_collect()
        output.append(reader())
    return '|'.join(output)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_inferred_integer_cells_escape_and_survive_generator_suspension(tmp_path, optimize):
    comparison = LLVM().assert_matches_python(READ + '''
from collections.abc import Callable, Generator
from pyjs.native import gc_collect, gc_set_threshold
def factory(index: int) -> Callable[[], str]:
    value = read(index)
    return lambda: str(value)
def stream() -> Generator[str, None, None]:
    value = read(0)
    reader: Callable[[], str] = lambda: str(value)
    yield reader()
    value = read(3)
    gc_collect()
    yield reader()
def main() -> str:
    gc_set_threshold(1)
    readers: list[Callable[[], str]] = [factory(0), factory(1), factory(2), factory(3)]
    gc_collect()
    output: list[str] = [reader() for reader in readers]
    for value in stream():
        output.append(value)
        gc_collect()
    return '|'.join(output)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("converted", [False, True])
def test_explicit_integer_cell_remains_an_integer_only_boundary(tmp_path, converted):
    source = READ + f'''
from collections.abc import Callable
def main() -> str:
    value: int | None = None
    reader: Callable[[], str] = lambda: str(value)
    incoming = read(0)
    value = {"int(incoming) if incoming is not None else None" if converted else "incoming"}
    return reader()
'''
    if converted:
        comparison = LLVM().assert_matches_python(
            source, directory=tmp_path, sanitizers=("address", "undefined"))
        assert comparison.native.stderr == ""
    else:
        with pytest.raises(LLVMUnsupported, match="narrowed optional int may be bool"):
            transpile_llvm(source)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("initial", ["plain(False)", "read(0)"])
def test_inferred_integer_layout_is_independent_of_assignment_order(tmp_path, optimize, initial):
    comparison = LLVM().assert_matches_python(READ + f'''
from pyjs.native import gc_collect
def plain(present: bool) -> int | None:
    return 9 if present else None
def main() -> str:
    value = {initial}
    copied = value
    output: list[str] = []
    for index in [0, 1, 2, 3, 4]:
        output.append(str(value))
        output.append(str(copied))
        copied = value
        value = read(index)
        gc_collect()
    output.append(str(value))
    value = plain(True)
    output.append(str(value))
    return '|'.join(output)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_noncall_optional_narrowing_preserves_boolean_names_fields_properties(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
class Box:
    def __init__(self, value: int | str | None) -> None:
        self.value = value
    @property
    def item(self) -> int | str | None:
        return self.value
def render(box: Box) -> str:
    value = box.item
    if isinstance(value, str):
        return value
    copied = value
    text = str(copied)
    if copied is not None:
        text += ':' + str(copied + 1) + ':' + str(isinstance(copied, bool))
    if not isinstance(box.value, str):
        text += ':' + str(box.value)
    if not isinstance(box.item, str):
        text += ':' + str(box.item)
    return text
def main() -> str:
    output: list[str] = []
    for value in [True, False, 4, None, 'text']:
        output.append(render(Box(value)))
    return '|'.join(output)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("boundary", ["argument", "local", "return", "list", "dict", "field"])
@pytest.mark.parametrize("converted", [False, True])
def test_noncall_optional_integer_boundary_requires_explicit_conversion(tmp_path, boundary, converted):
    value = "int(value) if value is not None else None" if converted else "value"
    consume = {
        "argument": f"return accept({value})",
        "local": f"result: int | None = {value}; return str(result)",
        "return": f"return {value}",
        "list": f"items: list[int | None] = []; items.append({value}); return str(items)",
        "dict": f"items: dict[str, int | None] = {{}}; items['key'] = {value}; return str(items)",
        "field": f"box = Box(); box.value = {value}; return str(box.value)",
    }[boundary]
    source = f'''
class Box:
    def __init__(self) -> None:
        self.value: int | None = None
def accept(value: int | None) -> str:
    return str(value)
def render(value: int | str | None) -> {"int | None" if boundary == "return" else "str"}:
    if isinstance(value, str):
        return {"len(value)" if boundary == "return" else "value"}
    {consume}
def main() -> str:
    output: list[str] = []
    for value in [True, False, 4, None, 'text']:
        output.append(str(render(value)))
    return '|'.join(output)
'''
    if converted:
        comparison = LLVM().assert_matches_python(
            source, directory=tmp_path, sanitizers=("address", "undefined"))
        assert comparison.native.stderr == ""
    else:
        with pytest.raises(LLVMUnsupported, match="narrowed optional int may be bool"):
            transpile_llvm(source)
