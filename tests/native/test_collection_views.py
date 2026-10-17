"""Copies may adapt outer slots, but must not widen shared mutable members."""

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("nested", [False, True], ids=["scalar", "nested"])
@pytest.mark.parametrize("operation", [
    "values.extend(source)", "values += source", "values[:] = source",
    "values[slice(None)] = source", "values = source", "values = list(source)",
    "values = keep(source)",
])
def test_sequence_mutations_cannot_reinterpret_boolean_storage(nested, operation):
    item = "list[int]" if nested else "int"
    initial = "[[1]]" if nested else "[1]"
    source = "[[True, False]]" if nested else "[True, False]"
    # Bulk copies and scalar stores have different diagnostics, but both must
    # reject before one-byte bool slots can be interpreted as eight-byte ints.
    message = "matching concrete item storage" if nested else "matching.*(storage|item types)"
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f'''
def keep(values: list[{item}]) -> list[{item}]:
    return values
def main() -> int:
    values: list[{item}] = {initial}
    source = {source}
    {operation}
    return len(values)
''')


@pytest.mark.parametrize("operation", ["values.append(source)", "values[0] = source"])
def test_nested_sequence_member_writes_preserve_the_inner_layout(operation):
    with pytest.raises(LLVMUnsupported, match="matching concrete item storage"):
        transpile_llvm(f'''
def main() -> int:
    values = [[1]]
    source = [True, False]
    {operation}
    return len(values)
''')


@pytest.mark.parametrize("operation", [
    "values.update(source)", "values |= source", "values = values | source",
    "values.update(source.items())", "values |= source.items()",
    "values = dict[str, list[int]](source.items())",
    "values = dict[str, list[int]](source)",
    "values = dict[str, list[int]](**source)",
    "values = dict[str, list[int]](flag=source['flag'])",
    "values = {**values, **source}",
])
def test_mapping_copies_and_updates_do_not_widen_nested_mutable_items(operation):
    with pytest.raises(LLVMUnsupported, match="matching concrete item storage|compatible value layouts"):
        transpile_llvm(f'''
def main() -> int:
    values: dict[str, list[int]] = {{'value': [1]}}
    source = {{'flag': [True, False]}}
    {operation}
    return len(values)
''')


@pytest.mark.parametrize(("annotation", "source", "mutation"), [
    ("set[Base]", "{Child()}", "values.add(Base())"),
    ("tuple[list[Base]]", "([Child()],)", "values[0].append(Base())"),
    ("list[Base | None]", "[Child()]", "values.append(None)"),
    ("list[str | None]", "['first']", "values.append(None)"),
    ("list[int | str | None]", "[1, 'first']", "values.append(None)"),
])
def test_same_width_mutable_aliases_keep_their_write_contract(annotation, source, mutation):
    # Pointer-sized storage alone is not compatibility: writing a broader
    # value through the alias would invalidate reads through the original.
    with pytest.raises(LLVMUnsupported, match="matching concrete item storage"):
        transpile_llvm(f'''
class Base:
    pass
class Child(Base):
    pass
def mutate(values: {annotation}) -> None:
    {mutation}
def main() -> int:
    original = {source}
    mutate(original)
    return len(original)
''')


@pytest.mark.parametrize("annotation", ["tuple[list[int]]", "tuple[list[int]] | str"])
def test_tuple_view_cannot_hide_a_nested_mutable_layout(annotation):
    with pytest.raises(LLVMUnsupported, match="matching concrete item storage"):
        transpile_llvm(f'''
def main() -> int:
    source = ([True, False],)
    alias: {annotation} = source
    return 0
''')


@pytest.mark.parametrize("wrapped", [False, True])
def test_union_return_cannot_hide_a_mutable_layout(wrapped):
    actual = "list[bool] | str" if wrapped else "list[bool]"
    with pytest.raises(LLVMUnsupported, match="matching concrete item storage"):
        transpile_llvm(f'''
def source() -> {actual}:
    return [True, False]
def widen() -> list[int] | str:
    return source()
def main() -> int:
    value = widen()
    return 0
''')


@pytest.mark.parametrize("statement", ["Holder(original)", "callback()(original)"])
def test_field_and_callback_views_cannot_broaden_mutable_write_contracts(statement):
    with pytest.raises(LLVMUnsupported, match="matching concrete item storage"):
        transpile_llvm(f'''
from collections.abc import Callable
class Base:
    pass
class Child(Base):
    pass
class Holder:
    def __init__(self, values: list[Child]):
        self.values: list[Base] = values
def mutate(values: list[Base]) -> None:
    values.append(Base())
def callback() -> Callable[[list[Child]], None]:
    return mutate
def main() -> int:
    original = [Child()]
    {statement}
    return len(original)
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_copied_union_slots_and_dynamic_slice_keep_aliases_and_evaluate_once(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
def replacement(events: list[str], flags: list[bool]) -> list[bool]:
    events.append('replacement')
    gc_collect()
    return flags
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    flags = [True, True, False, True]
    values = list[bool | str](flags)
    alias = values
    selected = slice(None)
    values[selected] = replacement(events, flags)
    values[slice(None, None, 2)] = [False, True]
    saved = values.copy()
    try:
        values[slice(None, None, 2)] = [True]
        raise AssertionError('missing length check')
    except ValueError:
        assert values == saved
    values[selected] = []
    values[selected] = ['é', '雪']
    values[selected] = values
    values.extend(flags)
    values += (False, True)
    copied = list[bool | str]((True, False))
    from_mapping = list[bool | str]({True: 1, False: 2})
    from_frozen = list[bool | str](frozenset([True]))
    from_range = list[int | str](range(4))
    from_iterator = list[int | str](iter([3, 4]))
    mixed = list[int | str]((1, 'two'))
    repeated = list[bool | str]((True, False) * 129)
    child = ['word']
    nested: list[list[str] | str] = ['header']
    nested.extend([child])
    child.append('tail')
    gc_collect()
    return repr((events, values, values is alias, flags, copied, from_mapping,
                 from_frozen, from_range, from_iterator, mixed, repeated[-4:], nested))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_mapping_copies_share_compatible_inner_storage_without_sharing_outer_slots(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
def main() -> str:
    gc_set_threshold(1)
    source: dict[str, list[bool | int | str]] = {'value': [True, 'a']}
    copied = dict[str, list[bool | int | str]](source)
    expanded = dict[str, list[bool | int | str]](**source)
    named = dict[str, list[bool | int | str]](value=source['value'])
    values: dict[str, list[bool | int | str]] = {'old': [5]}
    united = values | source
    unpacked: dict[str, list[bool | int | str]] = {**values, **source}
    values.update(source)
    paired = dict[str, list[bool | int | str]](source.items())
    paired.update(source.items())
    values |= source
    source['value'].append('tail')
    gc_collect()
    aliases = [copied, expanded, named, united, unpacked, values, paired]
    assert all(row is not source and row['value'] is source['value'] for row in aliases)
    return repr((source, aliases))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
