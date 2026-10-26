import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import transpile_jvm
from tests.backend_semantics import LOCAL_COLLECTION_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


def test_shared_local_collection_contract(tmp_path):
    assert_matches_python(LOCAL_COLLECTION_CONTRACT.source, tmp_path)


def test_local_collections_compile_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(LOCAL_COLLECTION_CONTRACT.source, tmp_path)


@pytest.mark.parametrize("source", [
    'values: list[str] = []',
    'values = ["a"]',
    'values = ["z", "a", "a", "😀", "\\ue000", "雪"]',
    'values = {"z": 1, "a": 2, "雪": 3}',
    'values = {"z": 1, "a": 2, "雪": 3}.keys()',
    'values = [4, -9, 4, 0, 100, 3, 2]',
    'values = [True, False, True]',
    'values = "z😀a\\ue000"',
])
def test_sorted_matches_python_and_leaves_input_unchanged(tmp_path, source):
    assert_text_matches_python(f'''def main() -> str:
    {source}
    ascending = sorted(values)
    descending = sorted(values, key=None, reverse=True)
    result = ""
    for value in ascending:
        result += str(value) + ","
    result += ";"
    for value in descending:
        result += str(value) + ","
    result += ";"
    for value in values:
        result += str(value) + ","
    return result
''', tmp_path)


def test_sorting_stability_and_single_argument_evaluation(tmp_path):
    assert_text_matches_python('''
class Row:
    def __init__(self, rank: int, label: str):
        self.rank = rank
        self.label = label
    def __lt__(self, other: Row) -> bool:
        return self.rank < other.rank
def rows(events: list[str]) -> list[Row]:
    events.append("rows")
    return [Row(2, "a"), Row(1, "b"), Row(2, "c"), Row(1, "d")]
def reverse(events: list[str]) -> bool:
    events.append("reverse")
    return True
def main() -> str:
    events: list[str] = []
    result = ""
    for row in sorted(rows(events), reverse=reverse(events)):
        result += row.label
    return result + ":" + ",".join(events)
''', tmp_path)


def test_floating_values_sort_numerically(tmp_path):
    assert_text_matches_python('''def main() -> str:
    values = [1.5, -9.0, 1.5, 0.0]
    ordered = sorted(values)
    assert ordered[0] == -9.0
    assert ordered[1] == 0.0
    assert ordered[2] == ordered[3] == 1.5
    assert values[0] == 1.5
    return "verified"
''', tmp_path)


def test_list_copy_is_shallow_but_has_independent_storage(tmp_path):
    assert_text_matches_python('''
class Entry:
    def __init__(self, value: str):
        self.value = value
def main() -> str:
    values = [Entry("original")]
    copied = values.copy()
    copied[0].value = "shared"
    copied.append(Entry("extra"))
    return values[0].value + str(len(values)) + str(len(copied))
''', tmp_path)


def test_key_callback_has_a_located_boundary():
    source = '''def key(value: int) -> int:
    return value
def main() -> int:
    return sorted([2, 1], key=key)[0]
'''
    with pytest.raises(CompilationError, match=r"JVM sorted\(\) key callbacks") as error:
        transpile_jvm(source, filename="sort_boundary.py")
    assert error.value.lineno == 4


def test_unmaterialized_range_has_a_located_boundary():
    with pytest.raises(CompilationError, match=r"JVM sorted\(\) requires"):
        transpile_jvm('def main() -> int:\n    return sorted(range(4))[0]\n')


@pytest.mark.parametrize("kind", ["int8", "int64", "float32"])
def test_represented_sort_has_an_explicit_boundary(kind):
    with pytest.raises(CompilationError, match=r"JVM sorted\(\) fixed-width item representations") as error:
        transpile_jvm(f'''from pyjs import {kind}
def main() -> int:
    values = [{kind}(2), {kind}(1)]
    return int(sorted(values)[0])
''', filename="represented_sort.py")
    assert error.value.lineno == 4


def test_sort_comparisons_are_bounded_and_failures_leave_input_intact(tmp_path):
    assert_matches_python('''
class Item:
    def __init__(self, value: int, calls: list[int], fail: bool):
        self.value = value
        self.calls = calls
        self.fail = fail
    def __lt__(self, other: Item) -> bool:
        self.calls[0] += 1
        if self.fail:
            raise ValueError("comparison failed")
        return self.value < other.value
def main() -> int:
    calls = [0]
    values: list[Item] = []
    for index in range(128):
        values.append(Item((index * 37) % 128, calls, False))
    ordered = sorted(values)
    assert calls[0] <= 128 * 7
    for index in range(128):
        assert ordered[index].value == index
        assert values[index].value == (index * 37) % 128
    failing = [Item(3, calls, True), Item(2, calls, True)]
    try:
        sorted(failing)
    except ValueError as error:
        assert str(error) == "comparison failed"
        assert len(failing) == 2
        assert failing[0].value == 3 and failing[1].value == 2
        return 42
    return 1
''', tmp_path)
