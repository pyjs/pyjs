import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.java.test_context_managers import assert_text_matches_python


def test_reference_set_operations_and_independent_copy(tmp_path):
    assert_text_matches_python('''def main() -> str:
    values: set[str] = set()
    assert not values
    values.add("雪")
    values.add("a")
    values.add("雪")
    assert len(values) == 2
    assert "雪" in values
    assert "missing" not in values
    copied = values.copy()
    values.discard("雪")
    values.discard("absent")
    assert "雪" in copied
    assert len(values) == 1
    values.clear()
    assert not values
    return ",".join(sorted(copied))
''', tmp_path)


def test_set_literals_and_nullable_reference_members(tmp_path):
    assert_text_matches_python('''def main() -> str:
    values = {"b", "a", "b"}
    assert len(values) == 2
    nullable: set[str | None] = {None, "present"}
    assert None in nullable
    nullable.discard(None)
    assert None not in nullable
    result = ""
    for value in nullable:
        if value is not None:
            result += value
    return ",".join(sorted(values)) + ":" + result
''', tmp_path)


def test_set_size_mutation_during_iteration_is_catchable(tmp_path):
    assert_text_matches_python('''def main() -> str:
    values = {"one", "two"}
    try:
        for value in values:
            values.add("new")
    except RuntimeError as error:
        return str(error)
    return "missed"
''', tmp_path)


@pytest.mark.parametrize("source", [
    'values: set[int] = set()',
    'values: set[float] = set()',
    'values: set[bool] = set()',
])
def test_numeric_set_items_keep_explicit_equality_boundary(source):
    with pytest.raises(JVMUnsupported, match="JVM sets currently require reference items"):
        transpile_jvm('def main() -> int:\n    ' + source + '\n    return len(values)\n')


def test_custom_equality_is_not_replaced_by_java_identity():
    source = '''class Item:
    def __eq__(self, other: object) -> bool:
        return True
    def __hash__(self) -> int:
        return 1
def main() -> int:
    values: set[Item] = set()
    values.add(Item())
    return len(values)
'''
    with pytest.raises(JVMUnsupported, match="Python __eq__/__hash__"):
        transpile_jvm(source)
