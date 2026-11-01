import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import LIST_CONCAT_CONTRACT
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


def test_shared_list_concatenation_contract(tmp_path):
    assert_matches_python(LIST_CONCAT_CONTRACT.source, tmp_path)


def test_concatenation_compiles_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(LIST_CONCAT_CONTRACT.source, tmp_path)


@pytest.mark.parametrize("expression", ["left(events, values) + right(events, values, False)",
                                       "left(events, values).__add__(right(events, values, False))"])
def test_both_operands_evaluate_once_before_result_is_copied(tmp_path, expression):
    assert_matches_python(f'''
        def left(events: list[int], values: list[int]) -> list[int]:
            events.append(1)
            return values
        def right(events: list[int], values: list[int], fail: bool) -> list[int]:
            events.append(2)
            values.append(9)
            if fail:
                raise ValueError("failed")
            return values
        def main() -> int:
            values = [1]
            events: list[int] = []
            result = {expression}
            assert len(events) == 2 and events[0] == 1 and events[1] == 2
            assert len(values) == 2 and len(result) == 4
            assert result[1] == 9 and result[3] == 9
            try:
                left(events, values) + right(events, values, True)
            except ValueError:
                assert len(values) == 3 and len(result) == 4
                assert len(events) == 4 and events[2] == 1 and events[3] == 2
                return 42
            return 0
    ''', tmp_path)


def test_nullable_reference_concatenation(tmp_path):
    assert_matches_python('''
        def main() -> int:
            left: list[str | None] = [None]
            right: list[str | None] = ["kept"]
            joined = left + right
            right[0] = None
            assert joined[0] is None and joined[1] == "kept"
            return 42
    ''', tmp_path)


@pytest.mark.parametrize("expression", ["empty + values", "values + empty"])
def test_empty_list_concatenation_is_an_independent_copy(tmp_path, expression):
    assert_matches_python(f'''
        def main() -> int:
            values = [42]
            empty: list[int] = []
            copied = {expression}
            copied.append(7)
            assert len(values) == 1 and len(copied) == 2 and copied[0] == 42
            return 42
    ''', tmp_path)


@pytest.mark.parametrize("expression", ["[] + values", "values + []"])
def test_untyped_empty_literal_retains_the_analysis_boundary(expression):
    with pytest.raises(CompilationError, match=r"Operator '\+' is not supported"):
        transpile_jvm(f'''def main() -> int:
    values = [1]
    return len({expression})
''', filename="concatenate.py")


def test_concatenation_rejects_different_item_storage():
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm('''def main() -> int:
    left = [1.5]
    right = [2]
    return len(left + right)
''', filename="concatenate.py")
    assert str(caught.value) == (
        "JVM list concatenation requires a list with matching item storage at line 4 "
        "while compiling concatenate.main"
    )
