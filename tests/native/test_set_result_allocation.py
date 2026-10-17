import pytest

from pyjs.native.llvm import transpile_llvm
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("custom", [False, True], ids=["scalar", "colliding-keys"])
def test_set_results_recover_allocation_failures_without_rehashing_sources(tmp_path, optimize, custom):
    # Retain the old set-difference fault matrix without depending on the old
    # backing-buffer count. Measure today's allocations, then deny each one.
    # Iterator inputs necessarily hash their items; concrete sets reuse hashes.
    item_type = "Key" if custom else "int"
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm, remaining

        class Key:
            def __init__(self, value: int):
                self.value = value
                self.hashes = 0

            def __hash__(self) -> int:
                self.hashes += 1
                return 1

            def __eq__(self, other: Key) -> bool:
                gc_collect()
                return self.value == other.value

        def calculate(left: set[{item_type}], frozen: frozenset[{item_type}],
                      right: set[{item_type}], small: set[{item_type}],
                      items: list[{item_type}], mode: int) -> int:
            if mode == 0:
                return len(left.difference(right))
            if mode == 1:
                return len(left - right)
            if mode == 2:
                return len(frozen.difference(right))
            if mode == 3:
                return len(frozen - right)
            if mode == 4:
                return len(left.difference())
            if mode == 5:
                return len(frozen.difference())
            if mode == 6:
                return len(left.difference(iter(items)))
            if mode == 7:
                return len(left.difference(small))
            if mode == 8:
                return len(left.symmetric_difference(right))
            if mode == 9:
                return len(left ^ right)
            if mode == 10:
                return len(frozen.symmetric_difference(right))
            if mode == 11:
                return len(frozen ^ right)
            return len(left.symmetric_difference(iter(items)))

        def main() -> int:
            gc_set_threshold(1)
            for mode in range(13):
                failure = 0
                stages = 1
                expected = 20 if mode in (4, 5) else 19 if mode == 7 else 16 if mode >= 8 else 10
                while failure <= stages:
                    # Source order/hash bookkeeping can be populated lazily;
                    # each failure must start as cold as the measured success.
                    keys = [{'Key(index)' if custom else 'index'} for index in range(26)]
                    left = set(keys[:20])
                    frozen = frozenset(left)
                    items = keys[10:]
                    right = set(items)
                    small = set(keys[:1])
                    before = {'sum(key.hashes for key in keys)' if custom else '0'}
                    caught = False
                    result = -1
                    arm(1000 if failure == 0 else failure)
                    try:
                        result = calculate(left, frozen, right, small, items, mode)
                    except MemoryError:
                        caught = True
                    if failure == 0:
                        stages = 1000 - remaining()
                    arm(0)
                    gc_collect()
                    if stages < 1 or stages >= 1000 or caught != (failure != 0):
                        print(mode, failure, stages, caught)
                        return 1
                    if result != (-1 if caught else expected):
                        return 2
                    if len(left) != 20 or len(frozen) != 20 or len(right) != 16:
                        return 3
                    if sorted({'key.value' if custom else 'key'} for key in left) != list(range(20)):
                        return 4
                    if sorted({'key.value' if custom else 'key'} for key in frozen) != list(range(20)):
                        return 7
                    if sorted({'key.value' if custom else 'key'} for key in right) != list(range(10, 26)):
                        return 8
                    if mode not in (6, 12) and before != {'sum(key.hashes for key in keys)' if custom else '0'}:
                        return 5
                    if calculate(left, frozen, right, small, items, mode) != expected:
                        return 6
                    failure += 1
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
