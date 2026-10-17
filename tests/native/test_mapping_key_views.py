import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_mapping_equality_preserves_subclass_priority_and_cached_hashes(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, value: int):
                self.value = value
                self.fail_hash = False
            def __hash__(self) -> int:
                if self.fail_hash:
                    raise ValueError("unexpected rehash")
                return self.value
            def __eq__(self, other: Key) -> bool:
                return False
        class Child(Key):
            def __init__(self, value: int):
                super().__init__(value)
                self.offset = 0
            def __hash__(self) -> int:
                return super().__hash__()
            def __eq__(self, other: Key) -> bool:
                gc_collect()
                return self.value + self.offset == other.value
        class Grandchild(Child):
            pass
        class Sibling(Key):
            pass
        def erased(left: object, right: object) -> bool:
            return left == right
        def main() -> str:
            gc_set_threshold(1)
            base: dict[Key, int] = {Key(1): 10}
            child: dict[Child, int] = {Child(1): 10}
            grandchild: dict[Grandchild, int] = {Grandchild(1): 10}
            sibling = {Sibling(1): 10}
            for key in base: key.fail_hash = True
            for key in child: key.fail_hash = True
            for key in grandchild: key.fail_hash = True
            return str((base == child, child == base, base != child, child != base,
                        child == grandchild, grandchild == child,
                        base == grandchild, grandchild == base,
                        erased(base, child), erased(child, base),
                        child == sibling, sibling == child))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stdout == "(True, True, False, False, True, True, True, True, True, True, False, True)"
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_mapping_key_upcast_comparison_roots_captured_values(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, value: int): self.value = value
            def __hash__(self) -> int: return self.value
            def __eq__(self, other: Key) -> bool: return False
        class Child(Key):
            def __init__(self, value: int, source: dict[Key, list[str]]):
                super().__init__(value)
                self.source = source
            def __hash__(self) -> int: return super().__hash__()
            def __eq__(self, other: Key) -> bool:
                self.source.clear()
                gc_collect()
                return self.value == other.value
        def main() -> str:
            gc_set_threshold(1)
            source = {Key(1): ["original"], Key(2): ["next"]}
            target = {Child(1, source): ["original"], Child(2, source): ["next"]}
            result = source == target
            gc_collect()
            return str((result, len(source), len(target)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_readonly_key_comparison_does_not_enable_writable_mapping_upcasts():
    with pytest.raises(LLVMUnsupported, match="matching concrete item storage"):
        transpile_llvm('''
            class Key:
                def __init__(self, value: int): self.value = value
                def __hash__(self) -> int: return self.value
                def __eq__(self, other: Key) -> bool: return self.value == other.value
            class Child(Key): pass
            def mutate(values: dict[Key, int]) -> int:
                values[Key(2)] = 20
                return len(values)
            def main() -> int:
                values = {Child(1): 10}
                return mutate(values)
        ''')
