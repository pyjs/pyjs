import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_dictionary_augmented_update_keeps_partial_mutation_on_rhs_failure(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from collections.abc import Iterator
from pyjs.native import gc_collect, gc_set_threshold
class State:
    def __init__(self):
        self.values = {"first": 1}
        self.gets = 0
        self.sets = 0
    @property
    def selected(self) -> dict[str, int]:
        self.gets += 1
        return self.values
    @selected.setter
    def selected(self, value: dict[str, int]):
        self.sets += 1
        self.values = value
def pairs(fail: bool) -> Iterator[tuple[str, int]]:
    yield "next", 2
    gc_collect()
    if fail:
        raise ValueError("pairs failed")
    yield "last", 3
def main() -> str:
    gc_set_threshold(1)
    state = State()
    alias = state.values
    results: list[str] = []
    for fail in [True, False]:
        try:
            state.selected |= pairs(fail)
        except ValueError as error:
            results.append(str(error))
        results.append(str((state.gets, state.sets, alias, alias is state.values)))
    returned = alias.__ior__([("first", 9)])
    results.append(str((returned is alias, state.values)))
    return "|".join(results)
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_mapping_binary_union_still_requires_a_mapping():
    with pytest.raises(CompilationError, match="Operator '\\|' is not supported"):
        transpile_llvm('''
def main() -> str:
    values = {"key": 1}
    return str(values | [("other", 2)])
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_set_targets_retain_old_value_across_rebinding_rhs(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
class State:
    def __init__(self):
        self.rows = [{1, 2, 3}]
        self.events: list[str] = []
    @property
    def selected(self) -> set[int]:
        self.events.append("get")
        return self.rows[0]
    @selected.setter
    def selected(self, value: set[int]):
        self.events.append("set")
        self.rows[0] = value
def rhs(state: State) -> set[int]:
    state.events.append("rhs")
    state.rows[0] = {99}
    gc_collect()
    return {3, 4}
def main() -> str:
    gc_set_threshold(1)
    state = State()
    alias = state.rows[0]
    state.selected |= rhs(state)
    state.rows[0] &= {2, 3, 4}
    state.selected ^= {3, 5}
    state.rows[0] -= {4}
    gc_collect()
    return str((sorted(alias), alias is state.rows[0], state.events))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_augmented_collection_targets_keep_aliases_and_setter_effects(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class State:
            def __init__(self):
                self.values = [1]
                self.rows = [{"a": 2}]
                self.calls = 0
                self.gets = 0
                self.sets = 0
                self.reject = False

            @property
            def selected(self) -> list[int]:
                self.gets += 1
                gc_collect()
                return self.values

            @selected.setter
            def selected(self, value: list[int]):
                self.sets += 1
                gc_collect()
                if self.reject:
                    raise ValueError("setter rejected")
                self.values = value

        def receiver(state: State) -> State:
            state.calls += 1
            gc_collect()
            return state

        def main() -> str:
            gc_set_threshold(1)
            state = State()
            alias = state.values
            row = state.rows[0]
            receiver(state).values += range(2, 4)
            receiver(state).selected *= 2
            receiver(state).rows[0] |= [("b", 5)]
            state.reject = True
            caught = ""
            try:
                receiver(state).selected += [9]
            except ValueError as error:
                caught = str(error)
            gc_collect()
            return str((alias, state.values, row, state.rows,
                        alias is state.values, row is state.rows[0],
                        state.calls, state.gets, state.sets, caught))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_augmented_subscripts_reacquire_storage_after_rhs_mutation(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class State:
            def __init__(self):
                self.rows = [[1]]
                self.order = 0

        class Index:
            def __init__(self, state: State):
                self.state = state
                self.calls = 0

            def __index__(self) -> int:
                self.calls += 1
                gc_collect()
                return 0

        def receiver(state: State) -> list[list[int]]:
            state.order = state.order * 10 + 1
            return state.rows

        def index(state: State, value: Index) -> Index:
            state.order = state.order * 10 + 2
            return value

        def rhs(state: State) -> list[int]:
            state.order = state.order * 10 + 3
            state.rows.extend([[8] for unused in range(20)])
            state.rows[0] = [10]
            gc_collect()
            return [2]

        def main() -> str:
            gc_set_threshold(1)
            state = State()
            alias = state.rows[0]
            selected = Index(state)
            receiver(state)[index(state, selected)] += rhs(state)
            gc_collect()
            return str((state.order, selected.calls, alias,
                        state.rows[0], state.rows[0] is alias, len(state.rows)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_augmented_slices_and_custom_inplace_methods(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import StaticArray
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs.numeric import int8

        class Box:
            def __init__(self, value: int):
                self.value = value

            def __ifloordiv__(self, other: int) -> Box:
                gc_collect()
                self.value //= other
                return self

        class State:
            def __init__(self):
                self.order = 0
                self.values = [1, 2, 3]
                self.box = Box(17)
                self.small = int8(127)
                self.fixed = StaticArray[int8, 2]([int8(127), int8(2)])

        def receiver(state: State) -> State:
            state.order = state.order * 10 + 1
            return state

        def bound(state: State, value: int) -> int:
            state.order = state.order * 10 + value
            return value - 2

        def rhs(state: State) -> list[int]:
            state.order = state.order * 10 + 4
            gc_collect()
            return [8, 9]

        def main() -> str:
            gc_set_threshold(1)
            state = State()
            alias = state.box
            receiver(state).values[bound(state, 2):bound(state, 3)] += rhs(state)
            order = state.order
            receiver(state).box //= 3
            state.small += int8(1)
            fixed_alias = state.fixed
            state.fixed[0] += int8(1)
            gc_collect()
            return str((order, state.values, state.box.value,
                        state.box is alias, state.small,
                        fixed_alias[0], state.fixed[0], fixed_alias is state.fixed))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("target", ["values", "state.values"])
def test_whole_static_array_augmented_assignment_is_rejected(target):
    with pytest.raises(CompilationError, match="whole-array augmented assignment"):
        transpile_llvm(f'''
            from pyjs import StaticArray, int8

            class State:
                def __init__(self):
                    self.values = StaticArray[int8, 1]([int8(1)])

            def main() -> int:
                state = State()
                values = state.values
                {target} += values
                return 0
        ''')
