import pytest

from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_sorted_imports_keep_builtin_identity_when_the_name_is_shadowed(optimize):
    result = LLVM().assert_matches_python('''
        import builtins as standard
        from builtins import sorted as ordered
        def sorted(values: list[int]) -> list[int]:
            return [99]
        def main() -> str:
            values = [3, 1, 2]
            return repr((ordered(values), standard.sorted(values, reverse=True), sorted(values)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_sort_key_mutations_restore_state_and_preserve_exception_priority(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from builtins import sorted as sort_values
        from pyjs.native import gc_collect, gc_set_threshold

        class Probe:
            def __init__(self, mode: int):
                self.mode = mode
                self.values = [3, 1, 2]
                self.seen: list[int] = []

            def key(self, value: int) -> int:
                self.seen.append(len(self.values))
                if self.mode == 1 or self.mode == 8:
                    self.values.append(9)
                elif self.mode == 2:
                    self.values.append(9)
                    self.values.clear()
                elif self.mode == 3:
                    self.values[:] = [8, 9]
                elif self.mode == 4:
                    self.values.append(9)
                    raise KeyError("key failed")
                elif self.mode == 5:
                    self.values.clear()
                elif self.mode == 6:
                    self.values.sort()
                elif self.mode == 7:
                    self.values.append(9)
                    self.values.pop()
                elif self.mode == 9:
                    self.values[:] = []
                elif self.mode == 10:
                    self.values *= 0
                elif self.mode == 11:
                    self.values.extend([])
                elif self.mode == 12:
                    self.values.reverse()
                gc_collect()
                return value

        def main() -> str:
            gc_set_threshold(1)
            results: list[str] = []
            for mode in range(13):
                probe = Probe(mode)
                outcome = "ok"
                ordered: list[int] = []
                try:
                    if mode == 8:
                        ordered = sort_values(probe.values, key=probe.key)
                    else:
                        probe.values.sort(key=probe.key)
                except KeyError:
                    outcome = "key"
                except ValueError as error:
                    outcome = str(error)
                gc_collect()
                results.append(f"{mode}:{probe.values}:{probe.seen}:{ordered}:{outcome}")
                probe.mode = 0
                probe.values.sort(key=probe.key)
                if probe.values != sorted(probe.values):
                    return "invalid retry"
            return "\\n".join(results)

    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_sort_comparators_observe_detached_list_and_restore_on_error(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Probe:
            def __init__(self, mode: int):
                self.mode = mode
                self.values: list[Item] = []
                self.saw_nonempty = False

        class Item:
            def __init__(self, value: int, probe: Probe):
                self.value = value
                self.probe = probe

            def __lt__(self, other: object) -> bool:
                probe = self.probe
                if len(probe.values) != 0:
                    probe.saw_nonempty = True
                if probe.mode == 1:
                    probe.values.append(self)
                elif probe.mode == 2:
                    probe.values.append(self)
                    raise RuntimeError("ordering failed")
                elif probe.mode == 3:
                    probe.values.clear()
                gc_collect()
                if not isinstance(other, Item):
                    return False
                return self.value < other.value

        def main() -> str:
            gc_set_threshold(1)
            results: list[str] = []
            for mode in range(4):
                probe = Probe(mode)
                probe.values.extend([Item(3, probe), Item(1, probe), Item(2, probe)])
                outcome = "ok"
                try:
                    probe.values.sort()
                except RuntimeError:
                    outcome = "ordering"
                except ValueError as error:
                    outcome = str(error)
                gc_collect()
                values = [item.value for item in probe.values]
                if mode != 1 and probe.saw_nonempty:
                    return "list exposed during comparison"
                results.append(f"{mode}:{values}:{outcome}")
                probe.mode = 0
                probe.values.sort()
                if [item.value for item in probe.values] != [1, 2, 3]:
                    return "invalid retry"
            return "\\n".join(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_sort_evaluates_keyword_factories_in_order_before_detaching(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        class Probe:
            def __init__(self):
                self.values = [3, 1, 2]
                self.events: list[int] = []

            def key(self, value: int) -> int:
                self.events.append(len(self.values))
                gc_collect()
                return value

            def factory(self) -> Callable[[int], int]:
                self.events.append(len(self.values) + 10)
                self.values.append(0)
                gc_collect()
                return self.key

            def reverse(self) -> bool:
                self.events.append(len(self.values) + 20)
                gc_collect()
                return True

        def main() -> str:
            gc_set_threshold(1)
            first = Probe()
            first.values.sort(key=first.factory(), reverse=first.reverse())
            second = Probe()
            second.values.sort(reverse=second.reverse(), key=second.factory())
            return f"{first.events}:{first.values}:{second.events}:{second.values}"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
