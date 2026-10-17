import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_sequence_indices_convert_once_and_observe_callback_mutation(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, values: list[int], events: list[str], index: int, action: int):
                self.values, self.events = values, events
                self.index, self.action = index, action
            def __index__(self) -> int:
                self.events.append('index')
                if self.action == 1:
                    self.values.clear()
                elif self.action == 2:
                    self.values.extend(range(100))
                gc_collect()
                if self.action == 3:
                    raise ValueError('callback failed')
                return self.index
        def exercise(operation: int, action: int, index: int) -> str:
            values = [10, 20]
            events: list[str] = []
            offset = Index(values, events, index, action)
            answer = 'done'
            try:
                if operation == 0:
                    answer = str(values[offset])
                elif operation == 1:
                    values[offset] = 42
                elif operation == 2:
                    del values[offset]
                elif operation == 3:
                    answer = str(values.pop(offset))
                else:
                    values.insert(offset, 42)
            except IndexError as error:
                answer = 'index:' + str(error)
            except ValueError as error:
                answer = 'value:' + str(error)
            return repr((answer, values, events))
        def main() -> str:
            gc_set_threshold(1)
            rows: list[str] = []
            for operation in range(5):
                for action in range(4):
                    for index in [-99, -1, 0, 99]:
                        rows.append(exercise(operation, action, index))
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_sequence_index_evaluation_and_assignment_values_stay_rooted(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, value: int):
                self.value = value
        class Index:
            def __init__(self, events: list[str]):
                self.events = events
            def __index__(self) -> int:
                self.events.append('index')
                gc_collect()
                return 0
        def receiver(values: list[Box], events: list[str]) -> list[Box]:
            events.append('receiver')
            return values
        def offset(events: list[str]) -> Index:
            events.append('offset')
            return Index(events)
        def item(events: list[str]) -> Box:
            events.append('item')
            return Box(42)
        def temporary(events: list[str]) -> list[Box]:
            events.append('temporary')
            return [Box(9)]
        def main() -> str:
            gc_set_threshold(1)
            values = [Box(1)]
            events: list[str] = []
            receiver(values, events)[offset(events)] = item(events)
            answer = receiver(values, events)[offset(events)].value
            receiver(values, events).insert(offset(events), item(events))
            answer += receiver(values, events).pop(offset(events)).value
            receiver(values, events).__setitem__(offset(events), item(events))
            answer += receiver(values, events).__getitem__(offset(events)).value
            del receiver(values, events)[offset(events)]
            answer += temporary(events)[offset(events)].value
            answer += temporary(events).pop(offset(events)).value
            temporary(events).insert(offset(events), item(events))
            temporary(events)[offset(events)] = item(events)
            gc_collect()
            return repr((answer, events, len(values)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_indexed_builtin_sequences_and_stored_slice_overloads(optimize):
    result = LLVM().assert_matches_python('''
        from enum import IntEnum
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, value: int):
                self.value = value
            def __index__(self) -> int:
                gc_collect()
                return self.value
        class Previous(Index):
            def __index__(self) -> int:
                return super().__index__() - 1
        class Choice(IntEnum):
            FIRST = 0
        def pick(index: Index) -> str:
            return repr(('aé😀'[index], b'abc'[index], (3, 5, 7)[index],
                         range(10, 20)[index], [11, 13, 17][index]))
        def main() -> str:
            gc_set_threshold(1)
            rows = [pick(Previous(3)), pick(Index(-1)),
                    str([4, 9][True]), str([4, 9][Choice.FIRST]), str([4, 9][int8(1)])]
            bounds = slice(0, 2)
            values = [1, 2, 3]
            rows.append(repr(values[bounds]))
            rows.append(repr(values.__getitem__(bounds)))
            values[bounds] = [8]
            values.__setitem__(bounds, [10, 20, 30])
            rows.append(repr(values))
            rows.append(repr((b'abc'[bounds], 'abc'[bounds], (1, 2, 3)[bounds],
                              range(4)[bounds])))
            rows.append(repr((b'abc'.__getitem__(Index(1)),
                              'abc'.__getitem__(Index(1)), (1, 2, 3).__getitem__(Index(1)),
                              range(4).__getitem__(Index(1)))))
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_integer_indices_validate_without_mutation(tmp_path, optimize):
    # Optional scalars use a value/presence pair, unlike nullable object pointers.
    result = LLVM().assert_matches_python('''
        import operator
        from pyjs.native import gc_collect, gc_set_threshold
        def inspect(index: int | None, mode: int) -> str:
            values = [5, 6]
            try:
                if mode == 0:
                    return repr(values[index])
                if mode == 1:
                    return repr((5, 6)[index])
                if mode == 2:
                    return repr("ab"[index])
                if mode == 3:
                    return repr(b"ab"[index])
                if mode == 4:
                    return repr(range(5, 7)[index])
                if mode == 5:
                    values[index] = 7
                elif mode == 6:
                    del values[index]
                elif mode == 7:
                    return repr(operator.getitem(values, index))
                elif mode == 8:
                    operator.setitem(values, index, 7)
                else:
                    operator.delitem(values, index)
                return repr(values)
            except TypeError:
                assert values == [5, 6]
                gc_collect()
                return "TypeError"
            except IndexError:
                assert values == [5, 6]
                gc_collect()
                return "IndexError"
        def main() -> str:
            gc_set_threshold(1)
            return repr([inspect(index, mode) for index in [None, 0, -1, 5]
                         for mode in range(10)])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_tagged_and_optional_indices_fail_without_mutation(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __index__(self) -> int:
                gc_collect()
                return -1
        def erased(index: object) -> str:
            values = [3, 5]
            try:
                values.insert(index, 42)
                return str(values.pop(index))
            except TypeError:
                return repr(values)
        def tagged(index: Index | int | str) -> str:
            try:
                return str([1, 2][index])
            except TypeError:
                return 'type'
        def optional(index: Index | None) -> str:
            try:
                return str([1, 2][index])
            except TypeError:
                return 'none'
        def main() -> str:
            gc_set_threshold(1)
            return '|'.join([erased(Index()), erased(0), erased(True), erased(None),
                             erased('x'), erased(1.2), erased(slice(1)), tagged(Index()), tagged(0),
                             tagged('x'), optional(Index()), optional(None)])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("annotation", ["object", "object | int", "slice | None",
                                      "Annotated[slice | None, 'index']"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_dynamic_slice_domains_dispatch_without_narrowing(annotation, optimize):
    result = LLVM().assert_matches_python(f'''
            from typing import Annotated
            def pick(index: {annotation}) -> str:
                values: list[object] = [1, 2, 3]
                try:
                    before = repr((values[index], 'abc'[index], b'abc'[index],
                                   (1, 2, 3)[index], range(3)[index], values.__getitem__(index)))
                    values[index] = [9]
                    assigned = repr(values)
                    del values[index]
                    values.__setitem__(index, [8])
                    values.__delitem__(index)
                    return before + assigned + repr(values)
                except TypeError:
                    return 'type' + repr(values)
            def main() -> str:
                return pick(slice(0, 2)) + pick(None)
        ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", ["cuts.get('head')", "box.value"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_nullable_slice_from_storage_dispatches_without_narrowing(expression, optimize):
    result = LLVM().assert_matches_python(f'''
            class Box:
                def __init__(self, value: slice | None):
                    self.value = value
            def main() -> str:
                cuts: dict[str, slice] = {{'head': slice(2)}}
                box = Box(slice(2))
                return repr([1, 2, 3][{expression}])
        ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_slice_subscripts_work_after_none_narrowing(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        def pick(index: slice | None) -> str:
            if index is None:
                return 'absent'
            values = [1, 2, 3]
            gc_collect()
            selected = repr((values[index], 'abc'[index], b'abc'[index],
                             (1, 2, 3)[index], range(3)[index]))
            values[index] = [9]
            assigned = repr(values)
            del values[index]
            return '|'.join([selected, assigned, repr(values)])
        def main() -> str:
            gc_set_threshold(1)
            cuts: dict[str, slice] = {'head': slice(1)}
            return '|'.join([pick(cuts.get('head')), pick(cuts.get('missing'))])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_subscripts_work_after_narrowing_the_index_domain(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __index__(self) -> int:
                gc_collect()
                return 1
        def pick(index: object) -> str:
            values = [1, 2, 3]
            if isinstance(index, int):
                values[index] = 42
                selected = values[index]
                del values[index]
                return repr((selected, values, 'abc'[index], b'abc'[index],
                             (1, 2, 3)[index], range(3)[index]))
            if isinstance(index, Index):
                values[index] = 9
                selected = values[index]
                del values[index]
                return repr((selected, values, 'abc'[index], b'abc'[index],
                             (1, 2, 3)[index], range(3)[index]))
            return 'outside index domain'
        def main() -> str:
            gc_set_threshold(1)
            return '|'.join([pick(0), pick(True), pick(Index()), pick(None), pick(slice(1))])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", ["[42][Index()]", "[42].index(42, Index())"])
@pytest.mark.parametrize("definition", [
    "@property\n    def __index__(self) -> int:\n        return 0",
    "@staticmethod\n    def __index__() -> int:\n        return 0",
])
def test_unsupported_index_protocol_shapes_have_focused_diagnostics(expression, definition):
    with pytest.raises(LLVMUnsupported, match="__index__ requires an instance method returning int"):
        transpile_llvm(f"class Index:\n    {definition}\ndef main() -> int:\n    return {expression}\n")


def test_mixed_slice_and_item_indices_require_a_union_result_annotation():
    with pytest.raises(CompilationError, match=r"Function returns int \| list\[int\], not int"):
        transpile_llvm('''
            def pick(index: int | slice) -> int:
                return [1, 2][index]
            def main() -> int:
                return pick(slice(1))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_sequence_search_bounds_run_before_length_and_equality(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, value: int, events: list[str]):
                self.value, self.events = value, events
            def __eq__(self, other: object) -> bool:
                self.events.append('compare')
                gc_collect()
                return isinstance(other, Box) and self.value == other.value
        class Bound:
            def __init__(self, values: list[Box], events: list[str], value: int, clear: bool):
                self.values, self.events = values, events
                self.value, self.clear = value, clear
            def __index__(self) -> int:
                self.events.append('index:' + str(self.value))
                if self.clear:
                    self.values.clear()
                self.values.append(Box(42, self.events))
                gc_collect()
                if self.value == 99:
                    raise RuntimeError('failed bound')
                return self.value
        def bound(values: list[Box], events: list[str], value: int, clear: bool) -> Bound:
            events.append('bound:' + str(value))
            return Bound(values, events, value, clear)
        def exercise(start: int, stop: int, clear: bool) -> str:
            events: list[str] = []
            values = [Box(1, events), Box(2, events)]
            try:
                answer = str(values.index(Box(42, events), bound(values, events, start, clear),
                                          bound(values, events, stop, False)))
            except ValueError:
                answer = 'missing'
            except RuntimeError as error:
                answer = str(error)
            return repr((answer, events, len(values)))
        def main() -> str:
            gc_set_threshold(1)
            rows: list[str] = []
            for start, stop in [(-2, 10), (0, -1), (-99, 0), (99, 10), (0, 99)]:
                rows.append(exercise(start, stop, False))
                rows.append(exercise(start, stop, True))
            events: list[str] = []
            values: list[Box] = []
            rows.append(str((10, 20, 30).index(20, Bound(values, events, 0, False),
                                               Bound(values, events, -1, False))))
            rows.append(repr(events))
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_index_conversion_failure_unwinds_and_preserves_mutation_target(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm
        class Index:
            def __index__(self) -> int:
                temporary = [0]
                gc_collect()
                return temporary[0]
        def main() -> int:
            values = [7]
            index = Index()
            caught = 0
            for attempt in range(1, 40):
                succeeded = False
                arm(attempt)
                try:
                    values[index] = 42
                    succeeded = True
                except MemoryError:
                    caught += 1
                finally:
                    arm(0)
                gc_collect()
                if succeeded:
                    assert values[0] == 42
                    return 0 if caught else 1
                assert values[0] == 7
                assert values[index] == 7
            return 2
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr


@pytest.mark.parametrize("expression", ["[1][None]", "[1].pop(None)", "[1].insert(None, 2)",
    "[1].__setitem__(1.5, 2)", "[1].__delitem__('x')", "'abc'[None]", "b'abc'[1.5]",
    "(1, 2)[None]", "range(4)['x']", "[1].index(1, None)", "(1,).index(1, 0, 1.5)",
    "[1].pop(slice(1))", "[1].insert(slice(1), 2)"])
def test_invalid_sequence_indices_raise_typeerror_at_use(expression):
    result = LLVM().assert_matches_python(f'''
        def main() -> int:
            try:
                {expression}
            except TypeError:
                return 0
            return 1
    ''', optimize=2, sanitizers=("address", "undefined"))
    assert not result.native.stderr
