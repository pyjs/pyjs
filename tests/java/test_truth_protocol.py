import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.java.test_context_managers import assert_text_matches_python


@pytest.mark.parametrize("condition", ["if value:", "if not value:"])
def test_list_condition_evaluates_once(tmp_path, condition):
    assert_text_matches_python(f'''
def create(events: list[int], full: bool) -> list[int]:
    events.append(1)
    return [7] if full else []
def main() -> str:
    events: list[int] = []
    results: list[str] = []
    for full in [False, True]:
        value = create(events, full)
        {condition}
            results.append("yes")
        else:
            results.append("no")
        results.append("full" if create(events, full) else "empty")
    return str(len(events)) + ":" + "|".join(results)
''', tmp_path)


@pytest.mark.parametrize("expression", ["if value:", "if not value:"])
def test_custom_length_truth_rejects_negative_result(tmp_path, expression):
    assert_text_matches_python(f'''
class Sized:
    def __init__(self, size: int):
        self.size = size
        self.calls = 0
    def __len__(self) -> int:
        self.calls += 1
        return self.size
def main() -> str:
    result: list[str] = []
    for size in [-1, 0, 3]:
        value = Sized(size)
        try:
            {expression}
                result.append("yes")
            else:
                result.append("no")
        except ValueError as error:
            result.append(str(error))
        result.append(str(value.calls))
    return "|".join(result)
''', tmp_path)


def test_non_boolean_bool_result_is_not_treated_as_length():
    with pytest.raises(JVMUnsupported, match="branch conditions must be bool"):
        transpile_jvm('''
class Invalid:
    def __bool__(self) -> int:
        return 2
def main() -> int:
    if Invalid():
        return 1
    return 0
''')
