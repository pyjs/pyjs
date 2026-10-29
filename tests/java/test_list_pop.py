from textwrap import dedent

import pytest

from tests.backend_semantics import LIST_POP_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


def test_shared_list_pop_contract(tmp_path):
    assert_matches_python(LIST_POP_CONTRACT.source, tmp_path)


def test_pop_retains_fixed_width_arithmetic(tmp_path):
    assert_matches_python('''
        from pyjs import int8
        def main() -> int:
            value = [int8(127)].pop()
            assert int(value + 1) == -128
            return 42
    ''', tmp_path)


def test_list_operations_compile_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(LIST_POP_CONTRACT.source, tmp_path)


@pytest.mark.parametrize("index", ["", "False", "True", "0", "-1", "-3", "3", "9223372036854775807",
                                    "-9223372036854775808"])
@pytest.mark.parametrize("values", ["[]", "[1, 2]"])
def test_invalid_pop_matches_python_without_mutation(tmp_path, index, values):
    assert_text_matches_python(dedent(f'''
        def main() -> str:
            values: list[int] = {values}
            before = list(values)
            try:
                result = values.pop({index})
                return str(result) + ":" + str(len(values))
            except IndexError as error:
                assert len(before) == len(values)
                for position in range(len(before)):
                    assert values[position] == before[position]
                return str(error)
    '''), tmp_path)


@pytest.mark.parametrize("kind, value", [("bool", "True"), ("float", "1.25"),
                                        ("str | None", "None"), ("str", '"value"')])
def test_pop_storage_and_regrowth(tmp_path, kind, value):
    assert_matches_python(f'''
        def main() -> int:
            values: list[{kind}] = [{value}]
            for index in range(20):
                assert values.pop() == {value}
                assert len(values) == 0
                values.append({value})
            return 42
    ''', tmp_path)


def test_receiver_and_index_are_evaluated_once_in_order(tmp_path):
    assert_matches_python('''
        class Box:
            def __init__(self, value: int):
                self.value = value
        def receiver(values: list[Box], calls: list[int]) -> list[Box]:
            calls.append(1)
            return values
        def index(calls: list[int]) -> int:
            calls.append(2)
            return 0
        def main() -> int:
            first = Box(1)
            last = Box(2)
            values = [first, last]
            calls: list[int] = []
            assert receiver(values, calls).pop(index(calls)) is first
            assert values[0] is last
            assert len(calls) == 2 and calls[0] == 1 and calls[1] == 2
            return 42
    ''', tmp_path)


@pytest.mark.parametrize("expression", ["mapping", "mapping.keys()"])
def test_key_snapshot_allows_removal_during_iteration(tmp_path, expression):
    assert_matches_python(f'''
        def main() -> int:
            mapping = {{"a": 1, "b": 2, "c": 3}}
            snapshot = list({expression})
            for key in snapshot:
                del mapping[key]
            assert len(mapping) == 0
            assert len(snapshot) == 3
            assert snapshot[0] == "a" and snapshot[2] == "c"
            return 42
    ''', tmp_path)


def test_key_copy_does_not_inherit_value_representation(tmp_path):
    assert_matches_python('''
        from pyjs import int8
        def main() -> int:
            mapping = {"first": int8(127)}
            keys = list(mapping)
            assert keys[0] == "first"
            empty: dict[str, int] = {}
            assert len(list(empty)) == 0
            return 42
    ''', tmp_path)


def test_missing_dictionary_deletion_preserves_keys_and_raises_keyerror(tmp_path):
    assert_text_matches_python('''def main() -> str:
    values = {"present": 42}
    try:
        del values["missing"]
    except KeyError as error:
        assert len(values) == 1 and values["present"] == 42
        return str(error)
    return "missed"
''', tmp_path)
