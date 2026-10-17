import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", [
    "dict[str, int]", "dict[tuple[int, int], str]", "set[int]", "frozenset[str]",
    "list[dict[str, int]]", "tuple[dict[str, int], int]",
])
def test_mapping_comparison_without_any_mapping_construction(tmp_path, optimize, annotation):
    # Do not format a dictionary or construct one: either would independently
    # select its runtime and conceal the comparison's missing dependency.
    result = LLVM().assert_matches_python(f'''
        def value() -> {annotation} | None:
            return None

        def main() -> int:
            left = value()
            right = value()
            return 0 if left == right and not left != right else 1
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.returncode == 0
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_mapping_equality_reuses_hashes_and_retains_detached_values(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, value: int):
                self.value = value
                self.fail = False
                self.owner: dict[Key, str] = {}
            def __hash__(self) -> int:
                if self.fail: raise ValueError("rehash")
                return 0
            def __eq__(self, other: "Key") -> bool:
                self.owner.clear()
                gc_collect()
                return self.value == other.value
        def main() -> str:
            gc_set_threshold(1)
            first, second = Key(1), Key(1)
            left, right = {first: "value" * 100}, {second: "value" * 100}
            first.fail = True
            second.fail = True
            cached = left == right
            second.owner = left
            detached = left == right
            return str((cached, detached, len(left), len(right)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_mapping_equality_value_callback_deletes_current_source_entry(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Value:
            def __init__(self, number: int):
                self.number = number
                self.owner: dict[int, Value] = {}
            def __eq__(self, other: "Value") -> bool:
                if 1 in self.owner:
                    del self.owner[1]
                gc_collect()
                return self.number == other.number
        def main() -> str:
            gc_set_threshold(1)
            first = Value(1)
            left = {1: first, 2: Value(2)}
            right = {1: Value(1), 2: Value(3)}
            first.owner = left
            return str((left == right, len(left), left == left,
                        {1: None} == {1: None}, {1: None} == {2: None}))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
