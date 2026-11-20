import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import DICT_BOOL_CONTRACT, LIST_BOOL_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


@pytest.mark.parametrize("contract", [LIST_BOOL_CONTRACT, DICT_BOOL_CONTRACT], ids=["list", "dict"])
def test_collection_bool_matches_python(tmp_path, contract):
    assert_matches_python(contract.source, tmp_path)


@pytest.mark.parametrize("contract", [LIST_BOOL_CONTRACT, DICT_BOOL_CONTRACT], ids=["list", "dict"])
def test_collection_bool_android_dex(tmp_path, contract):
    assert_compiles_to_android_dex(contract.source, tmp_path)


@pytest.mark.parametrize("annotation", ["list[int]", "dict[int, int]"])
def test_nullable_collection_bool_still_requires_a_presence_guard(annotation):
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(f'''def truth(values: {annotation} | None) -> bool:
    return bool(values)
def main() -> bool:
    return truth(None)
''')
    assert str(caught.value) == (
        "JVM bool conversion requires a numeric or string value at line 2 "
        "while compiling _pyjs_java_.truth"
    )


@pytest.mark.parametrize("name", ["list", "set", "dict"])
@pytest.mark.parametrize("generic", [False, True])
@pytest.mark.parametrize("field", ["value", "length"])
def test_collection_namesakes_keep_the_custom_bool_boundary(name, generic, field):
    declaration = name + ("[T]" if generic else "")
    annotation = name + ("[int]" if generic else "")
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(f'''class {declaration}:
    def __init__(self, value: int):
        self.{field} = value
    def __bool__(self) -> bool:
        return False
def truth(value: {annotation}) -> bool:
    return bool(value)
def main() -> int:
    builtin_values = [7]
    return int(truth({annotation}(len(builtin_values))))
''')
    assert str(caught.value) == (
        "JVM bool conversion requires a numeric or string value at line 2 "
        "while compiling _pyjs_java_.truth"
    )


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


@pytest.mark.parametrize("expression", ["value", "not value", "bool(value)", "not bool(value)"])
def test_dictionary_condition_evaluates_its_receiver_once(tmp_path, expression):
    condition = expression.replace("value", "create(events, full)")
    assert_text_matches_python(f'''
def create(events: list[int], full: bool) -> dict[int, int]:
    events.append(1)
    return {{0: 0}} if full else {{}}
def main() -> str:
    events: list[int] = []
    result = ""
    for full in [False, True]:
        if {condition}:
            result += "yes"
        else:
            result += "no"
    return str(len(events)) + ":" + result
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
