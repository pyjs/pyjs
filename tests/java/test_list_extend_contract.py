import pytest

from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import LIST_EXTEND_CONTRACT
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


def test_shared_list_extend_contract(tmp_path):
    assert_matches_python(LIST_EXTEND_CONTRACT.source, tmp_path)


def test_extend_compiles_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(LIST_EXTEND_CONTRACT.source, tmp_path)


def test_receiver_and_source_evaluate_once_in_order_and_failure_does_not_extend(tmp_path):
    assert_matches_python('''
        class Box:
            def __init__(self, value: int):
                self.value = value
        def receiver(values: list[Box], calls: list[int]) -> list[Box]:
            calls.append(1)
            return values
        def source(values: list[Box], calls: list[int], fail: bool) -> list[Box]:
            calls.append(2)
            if fail:
                raise ValueError("source failed")
            return values
        def main() -> int:
            first = Box(1)
            values = [first]
            calls: list[int] = []
            assert receiver(values, calls).extend(source(values, calls, False)) is None
            assert len(values) == 2 and values[0] is first and values[1] is first
            assert len(calls) == 2 and calls[0] == 1 and calls[1] == 2
            try:
                receiver(values, calls).extend(source(values, calls, True))
            except ValueError:
                assert len(values) == 2
                assert len(calls) == 4 and calls[2] == 1 and calls[3] == 2
                return 42
            return 0
    ''', tmp_path)


def test_nullable_references_and_empty_storage(tmp_path):
    assert_matches_python('''
        def main() -> int:
            values: list[str | None] = []
            other: list[str | None] = [None, "retained"]
            values.extend(other)
            values.extend(values)
            assert len(values) == 4 and values[0] is None and values[3] == "retained"
            other[1] = None
            assert values[1] == "retained"
            return 42
    ''', tmp_path)


@pytest.mark.parametrize("source", ["(2, 3)", "range(3)"])
def test_extend_rejects_other_iterable_storage(source):
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(f'''def main() -> int:
    values = [1]
    values.extend({source})
    return len(values)
''', filename="extension.py")
    assert str(caught.value) == (
        "JVM list.extend requires a list with matching item storage at line 3 "
        "while compiling extension.main"
    )


@pytest.mark.parametrize("item_type,initial,source_type,source", [
    ("float", "1.5", "int", "2"),
    ("int", "1", "bool", "True"),
    ("int | None", "None, 1", "int", "2"),
])
def test_extend_rejects_lists_with_different_item_storage(item_type, initial, source_type, source):
    with pytest.raises(JVMUnsupported) as caught:
        transpile_jvm(f'''def main() -> int:
    values: list[{item_type}] = [{initial}]
    other: list[{source_type}] = [{source}]
    values.extend(other)
    return len(values)
''', filename="extension.py")
    assert str(caught.value) == (
        "JVM list.extend requires a list with matching item storage at line 4 "
        "while compiling extension.main"
    )
