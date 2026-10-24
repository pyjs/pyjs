from tests.backend_semantics import DICTIONARY_KEYS_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


def test_shared_dictionary_keys_contract(tmp_path):
    assert_matches_python(DICTIONARY_KEYS_CONTRACT.source, tmp_path)


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
