import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_set_operations_follow_survivors_after_callback_source_deletion(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, value: int):
                self.value = value
                self.owner: set[Key] | None = None
                self.drop = False
            def __hash__(self) -> int: return 0
            def __eq__(self, other: "Key") -> bool:
                if self.drop and other.owner is not None:
                    self.drop = False
                    other.owner.remove(other)
                    gc_collect()
                return self.value == other.value
        def scenario(operation: int) -> str:
            first, second = Key(1), Key(2)
            source = {first, second}
            first.owner = source
            second.owner = source
            anchor = Key(1 if operation in (1, 3) else 0)
            target = {anchor, Key(2 if operation in (2, 3) else 3)}
            anchor.drop = True
            if operation == 0:
                target.update(source)
            elif operation == 1:
                return str(source.issubset(target))
            elif operation == 2:
                target.difference_update(source)
            else:
                target = source.intersection(target)
            return str(sorted(key.value for key in target))
        def main() -> str:
            gc_set_threshold(1)
            return "|".join(scenario(operation) for operation in range(4))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("mode", [0, 1, 2, 3])
def test_update_cursor_handles_earlier_later_and_multiple_deletions(tmp_path, optimize, mode):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Key:
            def __init__(self, value: int):
                self.value = value
                self.owner: set[Key] | None = None
                self.armed = False
            def __hash__(self) -> int: return 0
            def __eq__(self, other: "Key") -> bool:
                trigger = 1 if {mode} < 2 else 2
                if self.armed and other.owner is not None and other.value == trigger:
                    self.armed = False
                    for item in list(other.owner):
                        if ({mode} == 0 and item.value == 1
                            or {mode} == 1 and item.value == 2
                            or {mode} == 2 and item.value == 1
                            or {mode} == 3 and item.value <= 2):
                            other.owner.remove(item)
                    gc_collect()
                return self.value == other.value
        def main() -> str:
            gc_set_threshold(1)
            first, second, third = Key(1), Key(2), Key(3)
            source = {{first, second, third}}
            for item in source:
                item.owner = source
            anchor = Key(0)
            target = {{anchor}}
            anchor.armed = True
            target.update(source)
            return str((sorted(key.value for key in target), sorted(key.value for key in source)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
