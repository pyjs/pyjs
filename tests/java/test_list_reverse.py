import pytest

from tests.backend_semantics import LIST_REVERSE_CONTRACT
from tests.java.test_exceptions import assert_matches_python


def test_shared_list_reverse_contract(tmp_path):
    assert_matches_python(LIST_REVERSE_CONTRACT.source, tmp_path)


@pytest.mark.parametrize("kind, values", [
    ("int", "[1, 2, 3, 4, 5, 6]"),
    ("float", "[1.5, 2.5]"),
    ("str | None", '["first", None, "last"]'),
])
def test_reverse_twice_preserves_storage_and_allows_growth(tmp_path, kind, values):
    assert_matches_python(f'''
        def main() -> int:
            values: list[{kind}] = {values}
            first = values[0]
            count = len(values)
            original: list[{kind}] = {values}
            values.reverse()
            for index in range(count):
                assert values[index] == original[count - index - 1]
            values.reverse()
            for index in range(count):
                assert values[index] == original[index]
            values.append(first)
            assert len(values) == count + 1 and values[-1] == first
            return 42
    ''', tmp_path)


def test_reverse_evaluates_receiver_once_and_preserves_object_identity(tmp_path):
    assert_matches_python('''
        class Box:
            def __init__(self, value: int):
                self.value = value
        def receiver(values: list[Box], calls: list[int]) -> list[Box]:
            calls.append(1)
            return values
        def main() -> int:
            first = Box(1)
            second = Box(2)
            values = [first, second]
            calls: list[int] = []
            receiver(values, calls).reverse()
            assert len(calls) == 1
            assert values[0] is second and values[1] is first
            return 42
    ''', tmp_path)


@pytest.mark.parametrize("kind", ["i32", "f32", "f64"])
def test_reverse_retains_java_numeric_domains(tmp_path, kind):
    assert_matches_python(f'''
        from pyjs.java import {kind}
        def main() -> int:
            values = [{kind}(1), {kind}(2), {kind}(3)]
            values.reverse()
            assert int(values[0]) == 3 and int(values[-1]) == 1
            values.append({kind}(4))
            assert int(values[-1]) == 4
            return 42
    ''', tmp_path)
