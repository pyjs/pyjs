import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_object_sort_keys_are_stable_and_computed_once(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from types import NotImplementedType
        from pyjs.native import gc_collect, gc_set_threshold

        class Rank:
            def __init__(self, value: int):
                self.value = value

            def __lt__(self, other: Rank) -> bool | NotImplementedType:
                gc_collect()
                return NotImplemented

            def __gt__(self, other: Rank) -> bool:
                gc_collect()
                return self.value > other.value

        class Selector:
            def __init__(self):
                self.seen: list[int] = []

            def key(self, value: int) -> Rank:
                self.seen.append(value)
                gc_collect()
                return Rank(value % 10)

        def main() -> str:
            gc_set_threshold(1)
            selector = Selector()
            values = [23, 11, 32, 21, 12, 43]
            ascending = sorted(values, key=selector.key)
            values.sort(key=selector.key, reverse=True)
            empty: list[int] = []
            empty.sort(key=selector.key)
            singleton = sorted([99], key=selector.key)
            return str((ascending, values, singleton, selector.seen))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_sort_object_keys_restore_mutated_inputs_and_preserve_errors(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from types import NotImplementedType
        from pyjs.native import gc_collect, gc_set_threshold

        class Item:
            def __init__(self, value: int):
                self.value = value

        class Probe:
            def __init__(self, mode: int):
                self.mode = mode
                self.values = [Item(3), Item(1), Item(2)]

            def key(self, item: Item) -> Rank:
                if self.mode == 1 or self.mode == 2:
                    self.values.append(Item(99))
                gc_collect()
                if self.mode == 2:
                    raise KeyError("key failed")
                return Rank(item.value, self)

        class Rank:
            def __init__(self, value: int, probe: Probe):
                self.value = value
                self.probe = probe

            def __gt__(self, other: Rank) -> bool | NotImplementedType:
                if self.probe.mode == 3 or self.probe.mode == 4:
                    self.probe.values.append(Item(99))
                gc_collect()
                if self.probe.mode == 4:
                    raise KeyError("comparison failed")
                if self.probe.mode == 5:
                    return NotImplemented
                return self.value > other.value

        def main() -> str:
            gc_set_threshold(1)
            results: list[str] = []
            for mode in range(6):
                probe = Probe(mode)
                aliases = probe.values.copy()
                outcome = "ok"
                try:
                    probe.values.sort(key=probe.key)
                except (KeyError, ValueError, TypeError) as error:
                    outcome = str(error)
                gc_collect()
                results.append(outcome)
                # Partial order after a comparison error is algorithm-specific;
                # every original item must remain, and callback inserts vanish.
                results.append(str(sorted([item.value for item in probe.values])))
                probe.mode = 0
                probe.values.sort(key=probe.key)
                if probe.values != [aliases[1], aliases[2], aliases[0]]:
                    return "identity lost during retry"
            return "\\n".join(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_sort_object_keys_inside_first_class_callback(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        class Rank:
            def __init__(self, value: int):
                self.value = value

            def __gt__(self, other: Rank) -> bool:
                gc_collect()
                return self.value > other.value

        def key(value: int) -> Rank:
            gc_collect()
            return Rank(value % 10)

        def factory() -> Callable[[int], Rank]:
            modulus = 10
            return lambda value: Rank(value % modulus)

        def reverse() -> bool:
            gc_collect()
            return True

        def consume(callback: Callable[[list[int]], list[int]]) -> list[int]:
            return callback([23, 11, 32, 21, 12, 43])

        def main() -> str:
            gc_set_threshold(1)
            callback: Callable[[list[int]], list[int]] = lambda values: sorted(values, key=key)
            captured: Callable[[list[int]], list[int]] = lambda values: sorted(
                values, key=factory(), reverse=reverse(),
            )
            return str((consume(callback), consume(captured)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""
