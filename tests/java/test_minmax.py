import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import POSITIONAL_MINMAX_CONTRACT
from tests.java.test_exceptions import assert_matches_python


def test_shared_positional_minmax_contract(tmp_path):
    assert_matches_python(POSITIONAL_MINMAX_CONTRACT.source, tmp_path)


def test_positional_minmax_supports_full_jvm_integer_range(tmp_path):
    assert_matches_python('''
        def main() -> int:
            if min(0, -9223372036854775808, 9223372036854775807) != -9223372036854775808:
                return 1
            if max(0, -9223372036854775808, 9223372036854775807) != 9223372036854775807:
                return 2
            return 0
    ''', tmp_path)


@pytest.mark.parametrize("operation", ["min", "max"])
@pytest.mark.parametrize("values", ["7, 3", "7, 3, 9", "-2, -8, -3, -8", "0, 0, 0"])
def test_positional_integer_minmax(operation, values, tmp_path):
    assert_matches_python(f"def main() -> int:\n    return {operation}({values}) + 10\n", tmp_path)


def test_all_arguments_run_once_and_in_source_order(tmp_path):
    assert_matches_python('''
        def observe(events: list[int], value: int) -> int:
            events.append(value)
            return value
        def main() -> int:
            events: list[int] = []
            value = min(observe(events, 7), observe(events, 3), observe(events, 9))
            if value != 3 or len(events) != 3:
                return 1
            if events[0] != 7 or events[1] != 3 or events[2] != 9:
                return 1
            return 0
    ''', tmp_path)


@pytest.mark.parametrize("expression", ["min([1, 2])", "max(1, 2, key=identity)"])
def test_other_minmax_forms_keep_focused_boundary(expression):
    with pytest.raises(JVMUnsupported, match="at least two positional integer arguments"):
        transpile_jvm("def identity(value: int) -> int:\n    return value\n"
                      + f"def main() -> int:\n    return {expression}\n")
