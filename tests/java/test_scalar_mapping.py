import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import (
    SCALAR_MAPPING_VALUES_CONTRACT,
    TEXT_SERIALIZATION_CONTRACT,
)
from tests.java.test_exceptions import assert_matches_python


@pytest.mark.parametrize("contract", [SCALAR_MAPPING_VALUES_CONTRACT, TEXT_SERIALIZATION_CONTRACT],
                         ids=["scalar-values", "text"])
def test_shared_serialization_primitives(tmp_path, contract):
    assert_matches_python(contract.source, tmp_path)


@pytest.mark.parametrize("value", ["1", "1.25", "False"])
def test_missing_scalar_item_raises_key_error(tmp_path, value):
    assert_matches_python(f'''
        def main() -> int:
            values = {{"present": {value}}}
            try:
                values["missing"]
            except KeyError as error:
                return 42 if str(error) == "'missing'" else 1
            return 2
    ''', tmp_path)


@pytest.mark.parametrize("arguments", ['"absent"', '"absent", None'])
def test_optional_scalar_dictionary_result_has_a_focused_boundary(arguments):
    with pytest.raises(JVMUnsupported, match="scalar dictionary get requires a matching default"):
        transpile_jvm(f'''
            def main() -> int:
                values = {{"present": 1}}
                return 0 if values.get({arguments}) is None else 1
        ''')


def test_scalar_value_boxing_preserves_object_key_guard(tmp_path):
    assert_matches_python('''
        from typing import cast
        def lookup(key: object) -> int:
            values: dict[object, int] = {key: 3}
            values[key] = 9
            return values.get(key, -1)
        def main() -> int:
            return lookup(cast(object, "key"))
    ''', tmp_path)


@pytest.mark.parametrize(("kind", "value", "increment"), [
    ("int8", "127", "1"),
    ("int64", "9007199254740993", "2"),
    ("float32", "16777216.0", "1.0"),
])
def test_represented_values_keep_arithmetic_and_storage_domain(tmp_path, kind, value, increment):
    assert_matches_python(f'''
        from pyjs import {kind}
        def main() -> int:
            values: dict[str, {kind}] = {{"value": {kind}({value})}}
            values["value"] += {kind}({increment})
            expected = {kind}({value}) + {kind}({increment})
            assert values["value"] == expected
            assert values.get("value", {kind}(0)) == expected
            assert values.get("missing", {kind}(7)) == {kind}(7)
            return 42
    ''', tmp_path)
