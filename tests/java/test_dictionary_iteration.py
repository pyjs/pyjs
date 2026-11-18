import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import DICTIONARY_ITEMS_CONTRACT, DICTIONARY_KEYS_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


def test_shared_dictionary_keys_contract(tmp_path):
    assert_matches_python(DICTIONARY_KEYS_CONTRACT.source, tmp_path)


def test_shared_dictionary_items_contract(tmp_path):
    assert_matches_python(DICTIONARY_ITEMS_CONTRACT.source, tmp_path)


def test_dictionary_items_compile_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(DICTIONARY_ITEMS_CONTRACT.source, tmp_path)


def test_dictionary_keys_compile_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(DICTIONARY_KEYS_CONTRACT.source, tmp_path)


def test_key_iteration_observes_value_updates_and_rejects_size_changes(tmp_path):
    assert_text_matches_python('''
def main() -> str:
    mapping = {"first": 1, "last": 2}
    result = ""
    for key in mapping:
        mapping[key] = 3
        result += str(mapping[key])
    try:
        for key in mapping:
            mapping["new"] = 4
    except RuntimeError as error:
        result += ":" + str(error)
    else:
        return "mutation accepted"
    return result
''', tmp_path)


def test_nullable_reference_keys_and_nested_iteration(tmp_path):
    assert_text_matches_python('''
def main() -> str:
    values: dict[str | None, int] = {None: 1, "x": 2}
    result = ""
    view = values.keys()
    for outer in view:
        for inner in view:
            result += str(values[outer] + values[inner])
    flags: dict[bool | None, str] = {None: "n", True: "t", False: "f"}
    for key in flags:
        result += flags[key]
    return result
''', tmp_path)


def test_item_views_are_live_repeatable_and_yield_detached_tuples(tmp_path):
    assert_text_matches_python('''
from collections.abc import ItemsView

def inspect(view: ItemsView[str, int]) -> str:
    result = ""
    for key, value in view:
        result += key + str(value)
    return result

def main() -> str:
    mapping = {"first": 1, "last": 2}
    view = mapping.items()
    mapping["third"] = 3
    result = inspect(view)
    saved: list[tuple[str, int]] = []
    for item in view:
        saved.append(item)
        key, value = item
        mapping[key] = 7
    result += ":" + inspect(view)
    for key, value in saved:
        result += ":" + key + str(value)
    for key, value in list(view):
        result += ":" + key + str(value)
    empty: dict[str, int] = {}
    for key, value in empty.items():
        return "unexpected"
    else:
        result += ":empty"
    return result
''', tmp_path)


def test_item_iteration_rejects_size_changes(tmp_path):
    assert_text_matches_python('''
def main() -> str:
    mapping = {"first": 1, "last": 2}
    try:
        for key, value in mapping.items():
            mapping["new"] = 4
    except RuntimeError as error:
        return str(error)
    return "mutation accepted"
''', tmp_path)


@pytest.mark.parametrize("expression", ["view", "list(view)"])
def test_item_iteration_preserves_nullable_keys_and_native_reference_values(tmp_path, expression):
    assert_text_matches_python(f'''
from pyjs import jvm

@jvm.native("java/lang/StringBuilder")
class Builder:
    def __init__(self, value: str):
        self.value = value

    @jvm.native("java/lang/StringBuilder", name="toString", invocation="virtual")
    def text(self) -> str:
        return self.value

def main() -> str:
    values: dict[str | None, Builder | None] = {{None: Builder("value"), "empty": None}}
    view = values.items()
    result = ""
    for key, value in {expression}:
        result += "none" if key is None else key
        result += "missing" if value is None else value.text()
    return result
''', tmp_path)


@pytest.mark.parametrize(("kind", "value", "increment"), [
    ("int8", "127", "1"),
    ("int64", "9007199254740993", "2"),
    ("float32", "16777216.0", "1.0"),
])
@pytest.mark.parametrize("expression", ["view", "list(view)"])
def test_item_values_preserve_numeric_representation(tmp_path, kind, value, increment, expression):
    assert_matches_python(f'''
from collections.abc import ItemsView
from pyjs import {kind}
def main() -> int:
    mapping: dict[str, {kind}] = {{"item": {kind}({value})}}
    view: ItemsView[str, {kind}] = mapping.items()
    for key, item in {expression}:
        assert key == "item"
        assert item + {kind}({increment}) == {kind}({value}) + {kind}({increment})
    return 42
''', tmp_path)


@pytest.mark.parametrize("key_type,value_type", [("int8", "int64"), ("int64", "int8")])
def test_item_list_conversion_preserves_annotated_key_and_value_layouts(tmp_path, key_type, value_type):
    key = "127" if key_type == "int8" else "9007199254740993"
    value = "127" if value_type == "int8" else "9007199254740993"
    assert_matches_python(f'''
from collections.abc import ItemsView
from pyjs import int8, int64

def copy(view: ItemsView[{key_type}, {value_type}]) -> list[tuple[{key_type}, {value_type}]]:
    return list(view)

def main() -> int:
    source: dict[{key_type}, {value_type}] = {{{key_type}({key}): {value_type}({value})}}
    rows = copy(source.items())
    source[{key_type}({key})] = {value_type}(0)
    assert len(rows) == 1
    for key, value in rows:
        assert key + {key_type}(1) == {key_type}({key}) + {key_type}(1)
        assert value + {value_type}(1) == {value_type}({value}) + {value_type}(1)
    return 42
''', tmp_path)


@pytest.mark.parametrize("kind,value", [("int8", "127"), ("int64", "9007199254740993")])
@pytest.mark.parametrize("expression", ["mapping", "mapping.keys()"])
def test_dictionary_key_lists_preserve_numeric_representation(tmp_path, kind, value, expression):
    assert_matches_python(f'''
from pyjs import {kind}
def main() -> int:
    mapping: dict[{kind}, str] = {{{kind}({value}): "item"}}
    copied = list({expression})
    assert len(copied) == 1
    assert copied[0] + {kind}(1) == {kind}({value}) + {kind}(1)
    return 42
''', tmp_path)


def test_item_list_conversion_rejects_incompatible_tuple_storage():
    with pytest.raises(JVMUnsupported, match="dictionary view copying requires matching item storage"):
        transpile_jvm('''
def main() -> int:
    mapping = {"key": "value"}
    copied = list[tuple[object, object]](mapping.items())
    return len(copied)
''')


@pytest.mark.parametrize("kind,value", [
    ("str", '"key"'), ("int", "42"),
    ("int8", "int8(127)"), ("int64", "int64(9007199254740993)"),
])
@pytest.mark.parametrize("expression", ["mapping", "mapping.keys()"])
def test_explicit_dictionary_key_list_can_widen_to_nullable(tmp_path, kind, value, expression):
    assert_matches_python(f'''
from pyjs import int8, int64
def main() -> int:
    mapping: dict[{kind}, str] = {{{value}: "item"}}
    copied = list[{kind} | None]({expression})
    copied.append(None)
    assert len(copied) == 2
    assert copied[0] == {value}
    assert copied[1] is None
    return 42
''', tmp_path)


@pytest.mark.parametrize("expression", ["mapping", "mapping.keys()"])
def test_key_list_conversion_keeps_existing_nullable_keys(tmp_path, expression):
    assert_matches_python(f'''
def main() -> int:
    mapping: dict[str | None, int] = {{None: 1, "key": 2}}
    copied = list({expression})
    assert copied[0] is None
    assert copied[1] == "key"
    return len(copied)
''', tmp_path)


@pytest.mark.parametrize("expression", ["mapping", "mapping.keys()"])
@pytest.mark.parametrize("nullable", [False, True])
def test_explicit_dictionary_key_list_widens_subclasses(tmp_path, expression, nullable):
    target = "Base | None" if nullable else "Base"
    append = "    copied.append(None)\n" if nullable else ""
    assert_text_matches_python(f'''
class Base:
    def __init__(self, value: int):
        self.value = value
    def label(self) -> str:
        return "base" + str(self.value)
class Child(Base):
    def label(self) -> str:
        return "child" + str(self.value)
class Grandchild(Child):
    pass
def main() -> str:
    key = Grandchild(1)
    mapping = {{key: "first", Grandchild(3): "second"}}
    copied = list[{target}]({expression})
    copied.append(Base(2))
{append}    assert copied[0] is key
    mapping[key] = "changed"
    key.value = 9
    result = ""
    for item in copied:
        if item is None:
            result += "none"
        else:
            result += item.label()
    return result
''', tmp_path)


@pytest.mark.parametrize("expression", ["mapping", "mapping.keys()"])
def test_nullable_subclass_keys_widen_to_nullable_base(tmp_path, expression):
    assert_text_matches_python(f'''
class Base:
    def __init__(self, value: int):
        self.value = value
class Child(Base):
    pass
def main() -> str:
    mapping: dict[Child | None, str] = {{None: "empty", Child(4): "value"}}
    copied = list[Base | None]({expression})
    copied.append(Base(2))
    result = ""
    for item in copied:
        result += "none" if item is None else str(item.value)
    return result
''', tmp_path)


@pytest.mark.parametrize("source,target,value", [
    ("int8", "int | None", "int8(127)"),
    ("int", "int8 | None", "128"),
    ("int8", "int64 | None", "int8(127)"),
])
def test_dictionary_key_widening_cannot_change_numeric_representation(source, target, value):
    with pytest.raises(CompilationError, match="Stored iterable items use an incompatible representation"):
        transpile_jvm(f'''
from pyjs import int8, int64
def main() -> int:
    mapping: dict[{source}, str] = {{{value}: "item"}}
    return len(list[{target}](mapping.keys()))
''')
