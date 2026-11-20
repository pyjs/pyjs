import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import REVERSED_LIST_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)

REVERSE_REFERENCES = '''
from builtins import reversed as backwards
class Item:
    def __init__(self, label: str):
        self.label = label
def source(items: list[Item], events: list[str]) -> list[Item]:
    events.append("source")
    return items
def main() -> str:
    first = Item("first")
    last = Item("last")
    items = [first, last]
    events: list[str] = []
    for item in backwards(source(items, events)):
        events.append(item.label)
        assert item is first or item is last
    assert items[0] is first and items[1] is last
    return ",".join(events)
'''


def test_reversed_reference_list_preserves_identity_and_evaluates_source_once(tmp_path):
    assert_text_matches_python(REVERSE_REFERENCES, tmp_path)


def test_reversed_reference_list_compiles_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(REVERSE_REFERENCES, tmp_path)


def test_shared_reversed_list_contract(tmp_path):
    assert_matches_python(REVERSED_LIST_CONTRACT.source, tmp_path)


@pytest.mark.parametrize("mutation", ["pass", "items.append(9)", "items.pop()",
                                    "items.pop(); items.pop(); items.pop()",
                                    "items[0] = 8", "items.insert(0, 7)"])
def test_reversed_list_observes_python_mutation_semantics(tmp_path, mutation):
    assert_text_matches_python(f'''
def main() -> str:
    items = [1, 2, 3]
    output: list[str] = []
    for item in reversed(items):
        output.append(str(item))
        {mutation}
    else:
        output.append("done")
    return ",".join(output)
''', tmp_path)


def test_empty_nested_reverse_loops_and_break_continue_finally(tmp_path):
    assert_text_matches_python('''
def main() -> str:
    empty: list[str] = []
    output: list[str] = []
    for item in reversed(empty):
        output.append("unreachable")
    else:
        output.append("empty")
    for item in reversed(["a", "b", "c"]):
        for number in reversed([1, 2, 3]):
            try:
                if number == 3:
                    continue
                output.append(item + str(number))
                break
            finally:
                output.append(str(number))
        else:
            output.append("unreachable")
    return ",".join(output)
''', tmp_path)


def test_shadowed_reversed_uses_the_user_function(tmp_path):
    assert_text_matches_python('''
def reversed(items: list[str]) -> list[str]:
    return items
def main() -> str:
    output: list[str] = []
    for item in reversed(["first", "last"]):
        output.append(item)
    return ",".join(output)
''', tmp_path)


def test_stored_reverse_iterators_remain_unsupported():
    with pytest.raises(JVMUnsupported, match="unsupported JVM type annotation"):
        transpile_jvm('''
def main() -> int:
    items = [1, 2, 3]
    backward = reversed(items)
    total = 0
    for item in backward:
        total += item
    return total
''')


@pytest.mark.parametrize("value", ['"abc"', '(1, 2)', '{1, 2}'])
def test_other_reversed_iterables_have_a_focused_jvm_boundary(value):
    with pytest.raises(JVMUnsupported, match="JVM reversed iteration requires a list"):
        transpile_jvm(f"def main() -> int:\n    for item in reversed({value}):\n        pass\n    return 0\n")
