import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import JVMUnsupported, transpile_jvm
from tests.backend_semantics import LIST_COPY_CONTRACT
from tests.java.test_exceptions import assert_matches_python


def test_shared_list_copy_contract(tmp_path):
    assert_matches_python(LIST_COPY_CONTRACT.source, tmp_path)


@pytest.mark.parametrize("size", [0, 1, 4, 5, 20])
def test_list_copy_has_independent_storage_and_can_grow(tmp_path, size):
    assert_matches_python(f'''
        def main() -> int:
            values: list[int] = []
            for index in range({size}):
                values.append(index)
            copied = list(values)
            assert copied is not values
            assert len(copied) == {size}
            for index in range({size}):
                assert copied[index] == values[index]
            for index in range(10):
                copied.append(100 + index)
            assert len(values) == {size}
            copied[0] = 99
            if {size} > 0:
                assert values[0] == 0
            return 42
    ''', tmp_path)


@pytest.mark.parametrize("value, kind", [
    ("True", "bool"), ("1.5", "float"), ('"saved"', "str"),
    ("None", "str | None"),
])
def test_list_copy_preserves_supported_item_storage(tmp_path, value, kind):
    assert_matches_python(f'''
        def main() -> int:
            values: list[{kind}] = [{value}]
            copied = list(values)
            assert len(copied) == 1 and copied[0] == {value}
            copied.append({value})
            assert len(values) == 1
            return 42
    ''', tmp_path)


def test_list_copy_is_shallow_and_evaluates_source_once(tmp_path):
    assert_matches_python('''
        class Box:
            def __init__(self, value: int):
                self.value = value
        def source(events: list[int], boxes: list[Box]) -> list[Box]:
            events.append(1)
            return boxes
        def main() -> int:
            box = Box(1)
            values = [box]
            events: list[int] = []
            copied = list(source(events, values))
            assert len(events) == 1
            assert copied[0] is box
            copied[0].value = 42
            assert values[0].value == 42
            copied[0] = Box(2)
            assert values[0] is box
            nested = [[42]]
            other = list(nested)
            other[0].append(43)
            assert len(nested[0]) == 2
            return 42
    ''', tmp_path)


@pytest.mark.parametrize("constructor", ["list", "list[int8]"])
def test_list_copy_preserves_fixed_width_items(tmp_path, constructor):
    assert_matches_python(f'''
        from pyjs import int8
        def main() -> int:
            source = [int8(127)]
            copied = {constructor}(source)
            assert int(copied[0] + 1) == -128
            return 42
    ''', tmp_path)


def test_list_copy_does_not_silently_change_item_representation():
    with pytest.raises(CompilationError, match="Stored iterable items use an incompatible representation"):
        transpile_jvm('''
from pyjs import int8
def main() -> int:
    source = [128]
    copied = list[int8](source)
    return int(copied[0])
''')


def test_list_copy_keeps_a_focused_boundary_for_different_item_layouts():
    with pytest.raises(JVMUnsupported, match="matching item storage and representation"):
        transpile_jvm('''
def main() -> int:
    source = ["saved"]
    copied = list[object](source)
    return len(copied)
''')
