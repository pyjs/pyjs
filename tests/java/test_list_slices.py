from textwrap import dedent

import pytest

from pyjs.java import read_jvm_class, transpile_jvm
from tests.backend_semantics import LIST_SLICE_CONTRACT
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import (
    assert_compiles_to_android_dex,
    assert_matches_python,
)


def test_shared_list_slice_contract(tmp_path):
    assert_matches_python(LIST_SLICE_CONTRACT.source, tmp_path)


def test_slices_compile_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(LIST_SLICE_CONTRACT.source, tmp_path)


@pytest.mark.parametrize("size", [0, 1, 5])
def test_dynamic_optional_bounds_and_extreme_steps_match_python(tmp_path, size):
    assert_text_matches_python(dedent(f'''
        def check(values: list[int], start: int | None, stop: int | None,
                  step: int | None) -> int:
            result = values[start:stop:step]
            total = len(result)
            for item in result:
                total = total * 7 + item
            return total
        def main() -> str:
            values: list[int] = []
            for index in range({size}):
                values.append(index)
            bounds: list[int | None] = [None, -9223372036854775808, -6, -1, 0, 2, 5, 9223372036854775807]
            steps: list[int | None] = [None, -9223372036854775808, -7, -2, -1, 1, 2, 7, 9223372036854775807]
            result = ""
            for start in bounds:
                for stop in bounds:
                    for step in steps:
                        result += str(check(values, start, stop, step)) + ","
            return result
    '''), tmp_path)


def test_slice_evaluation_order_and_zero_step_leave_source_untouched(tmp_path):
    assert_matches_python('''
        def source(events: list[int], values: list[int]) -> list[int]:
            events.append(1)
            return values
        def bound(events: list[int], value: int) -> int:
            events.append(value)
            return value
        def main() -> int:
            events: list[int] = []
            values = [0, 1, 2, 3, 4]
            selected = source(events, values)[bound(events, 2):bound(events, 3):bound(events, 4)]
            assert len(events) == 4
            for index in range(4):
                assert events[index] == index + 1
            assert len(selected) == 1 and selected[0] == 2
            try:
                source(events, values)[bound(events, 2):bound(events, 3):bound(events, 0)]
            except ValueError as error:
                assert str(error) == "slice step cannot be zero"
                assert len(values) == 5 and values[0] == 0
                assert len(events) == 8 and events[7] == 0
                return 42
            return 0
    ''', tmp_path)


def test_boolean_bounds_and_nullable_items(tmp_path):
    assert_matches_python('''
        def selected(values: list[str | None], start: bool | None) -> list[str | None]:
            return values[start:True:True]
        def main() -> int:
            values: list[str | None] = [None, "kept"]
            assert selected(values, None)[0] is None
            assert len(selected(values, True)) == 0
            assert selected(values, False)[0] is None
            reverse = values[::-1]
            assert reverse[0] == "kept" and reverse[1] is None
            try:
                values[::False]
            except ValueError:
                return 42
            return 0
    ''', tmp_path)


def test_slice_runtime_is_emitted_once_and_only_when_reachable():
    for expression, expected in (("values[0]", 0), ("values[:][::-1][0]", 1)):
        compilation = transpile_jvm(f'''
def main() -> int:
    values = [1, 2]
    return {expression}
''')
        methods = [method.name for name, data in compilation.classes.items()
                   if "$list$" in name for method in read_jvm_class(data).methods]
        assert methods.count("slice") == expected
