import pytest

from tests.backend_semantics import (
    CONDITIONAL_EMPTY_COLLECTIONS,
    CONDITIONAL_EMPTY_MAPPING,
)
from tests.java.test_exceptions import assert_matches_python


@pytest.mark.parametrize("contract", [CONDITIONAL_EMPTY_COLLECTIONS, CONDITIONAL_EMPTY_MAPPING])
def test_shared_conditional_empty_collections(tmp_path, contract):
    assert_matches_python(contract.source, tmp_path)


def test_optional_input_selects_fresh_empty_storage(tmp_path):
    assert_matches_python('''
        def choose(values: list[int] | None) -> list[int]:
            result = values if values is not None else []
            result.append(7)
            return result
        def main() -> int:
            values = [2]
            chosen = choose(values)
            empty = choose(None)
            chosen.append(9)
            assert values[2] == 9
            assert len(empty) == 1 and empty[0] == 7
            return 42
    ''', tmp_path)
