import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_slice_replacement_materializes_supported_streams_and_preserves_layouts(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable, Iterator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        def replace(values: list[int], source: Iterable[int]) -> None:
            values[1:3] = source
        def reverse(values: list[int], source: Iterator[int]) -> None:
            values[slice(None, None, -1)] = source
        def main() -> str:
            gc_set_threshold(1)
            rows: list[str] = []
            values = [0, 1, 2, 3]
            alias = values
            replace(values, range(5))
            rows.append(repr(values))
            reverse(values, iter(values))
            rows.append(repr(values))
            values[::2] = (10, 11, 12, 13)
            rows.append(repr(values))
            values[slice(1, 3)] = (i + 20 for i in range(3))
            rows.append(repr(values))
            values[1:3] = ()
            values[slice(1, 3)] = []
            values[1:1] = b'AB'
            rows.append(repr((values, alias is values)))
            text = ['start', 'end']
            text[1:1] = 'é😀'
            text[slice(1, 3)] = iter(['new:' + str(i) for i in range(3)])
            gc_collect()
            rows.append(repr(text))
            represented = [int8(1), int8(2)]
            represented[:] = iter((int8(127), int8(-128)))
            represented[slice(0, 1)] = (int8(4), int8(5))
            rows.append(repr(represented))
            records: list[object] = [1, 'old']
            records[:] = iter(['new', 'text'])
            gc_collect()
            rows.append(repr(records))
            values[:] = {8: 1, 9: 2}.keys()
            values[slice(1, 1)] = {0: 10, 1: 11}.values()
            rows.append(repr(values))
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("explicit", [False, True], ids=["syntax", "slice-value"])
def test_slice_replacement_observes_iterator_mutation_before_length_and_shape(explicit, optimize):
    # CPython3.14 measures the destination after replacement iteration, including
    # an iterator's own mutations. Shape failure must retain only those effects.
    statement = ("values[slice(1, stop, step)] = Source(values, events)" if explicit
                 else "values[1:stop:step] = Source(values, events)")
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Cursor:
            def __init__(self, events: list[str]):
                self.index = 0
                self.events = events
            def __iter__(self) -> 'Cursor':
                self.events.append('cursor iter')
                return self
            def __next__(self) -> int:
                gc_collect()
                self.index += 1
                self.events.append('next:' + str(self.index))
                if self.index > 2:
                    raise StopIteration()
                return self.index + 7
        class Source:
            def __init__(self, values: list[int], events: list[str]):
                self.values = values
                self.events = events
            def __iter__(self) -> Cursor:
                self.events.append('source iter')
                self.values.extend([10, 11])
                gc_collect()
                return Cursor(self.events)
        def main() -> str:
            gc_set_threshold(1)
            rows: list[str] = []
            for step in [1, 2, -1, 0]:
                values = [0, 1, 2, 3]
                events: list[str] = []
                stop = 20 if step > 0 else -20
                try:
                    {statement}
                except ValueError as error:
                    rows.append(str(error))
                rows.append(repr(values) + repr(events))
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_slice_replacement_failed_iteration_preserves_aliases_and_can_resume(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Cursor:
            def __init__(self, values: list[str]):
                self.values = values
                self.index = 0
                self.fail = True
            def __iter__(self) -> 'Cursor':
                return self
            def __next__(self) -> str:
                gc_collect()
                self.index += 1
                if self.index == 2 and self.fail:
                    self.values.append('iterator effect')
                    raise RuntimeError('bad replacement')
                if self.index > 4:
                    raise StopIteration()
                return 'item:' + str(self.index)
        def main() -> str:
            gc_set_threshold(1)
            values = ['a', 'b', 'c', 'd']
            alias = values
            cursor = Cursor(values)
            rows: list[str] = []
            try:
                values[1:3] = cursor
            except RuntimeError as error:
                rows.append(str(error))
            gc_collect()
            rows.append(repr((values, values is alias, cursor.index)))
            cursor.fail = False
            values[slice(1, 3)] = cursor
            gc_collect()
            rows.append(repr((values, values is alias, cursor.index)))
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_slice_replacement_consumes_the_reacquired_cursor_and_propagates_its_errors(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Cursor:
            def __init__(self, events: list[str], redirected: bool, fail: bool):
                self.events = events
                self.redirected = redirected
                self.fail = fail
                self.index = 0
            def __iter__(self) -> 'Cursor':
                self.events.append('cursor iter')
                gc_collect()
                if self.fail:
                    raise RuntimeError('cannot reacquire')
                return Cursor(self.events, True, False)
            def __next__(self) -> str:
                gc_collect()
                self.index += 1
                if self.index > 2:
                    raise StopIteration()
                return ('right:' if self.redirected else 'wrong:') + str(self.index)
        class Source:
            def __init__(self, events: list[str], fail: bool):
                self.events = events
                self.fail = fail
            def __iter__(self) -> Cursor:
                self.events.append('source iter')
                return Cursor(self.events, False, self.fail)
        def main() -> str:
            gc_set_threshold(1)
            rows: list[str] = []
            for fail in [False, True]:
                values = ['original']
                events: list[str] = []
                try:
                    values[:] = Source(events, fail)
                except RuntimeError as error:
                    rows.append(str(error))
                gc_collect()
                rows.append(repr((values, events)))
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("selection", [":", "slice(None)"])
def test_slice_replacement_requires_narrowed_source_union(selection):
    with pytest.raises(LLVMUnsupported, match="concrete iterable type; narrow unions"):
        transpile_llvm(f'''
            def replace(values: list[int], source: list[int] | tuple[int, ...]) -> None:
                values[{selection}] = source
            def main() -> str:
                values = [0]
                replace(values, (1, 2))
                return repr(values)
        ''')
