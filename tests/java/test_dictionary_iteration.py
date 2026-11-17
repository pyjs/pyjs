import pytest

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


def test_item_iteration_preserves_nullable_keys_and_native_reference_values(tmp_path):
    assert_text_matches_python('''
from pyjs import jvm

@jvm.native("java/lang/StringBuilder")
class Builder:
    def __init__(self, value: str):
        self.value = value

    @jvm.native("java/lang/StringBuilder", name="toString", invocation="virtual")
    def text(self) -> str:
        return self.value

def main() -> str:
    values: dict[str | None, Builder | None] = {None: Builder("value"), "empty": None}
    result = ""
    for key, value in values.items():
        result += "none" if key is None else key
        result += "missing" if value is None else value.text()
    return result
''', tmp_path)


@pytest.mark.parametrize(("kind", "value", "increment"), [
    ("int8", "127", "1"),
    ("int64", "9007199254740993", "2"),
    ("float32", "16777216.0", "1.0"),
])
def test_item_values_preserve_numeric_representation(tmp_path, kind, value, increment):
    assert_matches_python(f'''
from pyjs import {kind}
def main() -> int:
    mapping: dict[str, {kind}] = {{"item": {kind}({value})}}
    for key, item in mapping.items():
        assert key == "item"
        assert item + {kind}({increment}) == {kind}({value}) + {kind}({increment})
    return 42
''', tmp_path)
