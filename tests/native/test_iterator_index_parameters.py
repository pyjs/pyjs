import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("error", ["RuntimeError", "MemoryError", "StopIteration"])
def test_islice_index_order_error_translation_and_recovery(optimize, error):
    result = LLVM().assert_matches_python(f'''
        from itertools import islice
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, value: int, name: str, failure: str, events: list[str]):
                self.value, self.name, self.failure, self.events = value, name, failure, events
            def __index__(self) -> int:
                self.events.append(self.name)
                gc_collect()
                if self.failure == self.name:
                    raise {error}('original callback error')
                return self.value
        class Source:
            def __init__(self, events: list[str]):
                self.events = events
            def __iter__(self) -> Iterator[int]:
                self.events.append('iter')
                gc_collect()
                return iter([0, 1, 2, 3, 4])
        def argument(value: int, name: str, failure: str, events: list[str]) -> Index:
            events.append('make:' + name)
            return Index(value, name, failure, events)
        def main() -> str:
            gc_set_threshold(1)
            rows: list[str] = []
            for start, stop, step in [(1, 5, 2), (-1, 5, 1), (1, -1, 1), (1, -2, 1),
                                      (1, 5, 0), (1, 5, -1), (-1, -1, -1)]:
                for failure in ['', 'start', 'stop', 'step']:
                    events: list[str] = []
                    try:
                        selected = islice(Source(events), argument(start, 'start', failure, events),
                            argument(stop, 'stop', failure, events), argument(step, 'step', failure, events))
                        rows.append(repr(list(selected)))
                    except ValueError as error:
                        rows.append(str(error))
                    rows.append(repr(events))
                    gc_collect()
            for failure in ['', 'stop']:
                events: list[str] = []
                try:
                    rows.append(repr(list(islice(Source(events), argument(3, 'stop', failure, events)))))
                except ValueError as error:
                    rows.append(str(error))
                rows.append(repr(events))
            try:
                raise RuntimeError('outer exception retained')
            except RuntimeError as outer:
                try:
                    islice([1, 2], Index(1, 'start', 'start', events), 2)
                except ValueError:
                    gc_collect()
                    rows.append(str(outer))
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_batched_repeat_callbacks_preserve_keyword_order_and_do_not_swallow_errors(optimize):
    result = LLVM().assert_matches_python('''
        from itertools import batched, repeat
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, n: int, events: list[str]):
                self.n, self.events = n, events
            def __index__(self) -> int:
                self.events.append('index')
                gc_collect()
                if self.n == 99:
                    raise TypeError('callback error')
                return self.n
        class Source:
            def __init__(self, events: list[str]):
                self.events = events
            def __iter__(self) -> Iterator[int]:
                self.events.append('iter')
                gc_collect()
                return iter([1, 2, 3])
        def size(n: int, events: list[str]) -> Index:
            events.append('size expression')
            return Index(n, events)
        def source(events: list[str]) -> Source:
            events.append('source expression')
            return Source(events)
        def main() -> str:
            gc_set_threshold(1)
            rows: list[str] = []
            for n in [2, 0, -1, 99]:
                events: list[str] = []
                try:
                    rows.append(repr(list(batched(n=size(n, events), iterable=source(events)))))
                except ValueError as error:
                    rows.append(str(error))
                except TypeError as error:
                    rows.append(str(error))
                rows.append(repr(events))
                events = []
                try:
                    item = source(events)
                    values = list(repeat(times=size(n, events), object=item))
                    rows.append(str(len(values)))
                    rows.append(str(all(value is item for value in values)))
                except TypeError as error:
                    rows.append(str(error))
                rows.append(repr(events))
                gc_collect()
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterator_indexes_preserve_optional_tagged_erased_and_override_semantics(optimize):
    result = LLVM().assert_matches_python('''
        from itertools import batched, repeat, islice
        from enum import IntEnum
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            pass
        class Index(Base):
            def __index__(self) -> int:
                gc_collect()
                return 2
        class N(IntEnum):
            TWO = 2
        def nominal(value: Base) -> str:
            return repr((list(batched([1, 2, 3], value)), list(repeat('x', value)),
                         list(islice([1, 2, 3], value))))
        def erased(value: object) -> str:
            rows: list[str] = []
            try:
                rows.append(repr(list(islice([0, 1, 2, 3], value, value, value))))
            except ValueError as error:
                rows.append(str(error))
            try:
                rows.append(repr(list(repeat('x', value))))
            except TypeError:
                rows.append('repeat type-error')
            try:
                rows.append(repr(list(batched([1, 2, 3], value))))
            except TypeError:
                rows.append('batched type-error')
            return '|'.join(rows)
        def optional(stop: int | None) -> str:
            return repr(list(islice([0, 1, 2, 3], None, stop, None)))
        def tagged(value: int | str | Index | None) -> str:
            try:
                return repr(list(islice([0, 1, 2, 3], value)))
            except ValueError as error:
                return str(error)
        def main() -> str:
            gc_set_threshold(1)
            return '|'.join([nominal(Index()), erased(Index()), erased(None), erased('bad'),
                            erased(1.5), optional(None), optional(2), tagged(Index()), tagged(2),
                            tagged(None), tagged('bad'),
                            repr((list(islice([1, 2, 3], N.TWO)), list(repeat(1, int8(2)))))])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", ["islice([1], Index())", "repeat(1, Index())", "batched([1], Index())"])
def test_iterator_index_descriptors_remain_a_compilation_boundary(expression):
    with pytest.raises(LLVMUnsupported, match="__index__ requires an instance method returning int"):
        transpile_llvm(f'''
            from itertools import batched, repeat, islice
            class Index:
                @property
                def __index__(self) -> int:
                    return 1
            def main():
                return list({expression})
        ''')


@pytest.mark.parametrize("expression", ["islice([1], -1.5)", "islice([1], 'bad')",
    "islice([1], 0, None, 'bad')", "repeat(1, None)", "repeat(1, 1.5)",
    "batched([1], None)", "batched([1], 'bad')"])
def test_invalid_iterator_index_values_raise_runtime_errors(expression):
    # The old islice float-only compilation diagnostic becomes a checked
    # ValueError now that bounds deliberately accept index-protocol objects.
    result = LLVM().assert_matches_python(f'''
        from itertools import islice, repeat, batched
        def main() -> str:
            try:
                {expression}
            except ValueError as error:
                return str(error)
            except TypeError:
                return 'type-error'
            return 'missing error'
    ''', optimize=2, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_islice_allocation_failures_translate_only_conversion_errors_and_recover(tmp_path, optimize):
    source = transpile_llvm('''
        from itertools import islice
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm
        class Index:
            def __init__(self, value: int):
                self.value = value
            def __index__(self) -> int:
                values = [self.value]
                gc_collect()
                return values[0]
        def construct() -> list[int]:
            return list(islice(range(6), Index(1), Index(5), Index(2)))
        def main() -> int:
            allocation_errors = 0
            conversion_errors = 0
            for attempt in range(1, 100):
                succeeded = False
                arm(attempt)
                try:
                    assert construct() == [1, 3]
                    succeeded = True
                except MemoryError:
                    allocation_errors += 1
                except ValueError:
                    conversion_errors += 1
                finally:
                    arm(0)
                gc_collect()
                assert construct() == [1, 3]
                if succeeded:
                    return 0 if allocation_errors and conversion_errors else 1
            return 2
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
