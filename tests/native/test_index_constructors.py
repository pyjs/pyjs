import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_range_index_callbacks_run_after_arguments_and_stop_on_failure(optimize):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, value: int, name: str, events: list[str]):
                self.value, self.name, self.events = value, name, events
            def __index__(self) -> int:
                self.events.append(self.name)
                gc_collect()
                if self.value == 99:
                    raise ValueError('failed:' + self.name)
                return self.value
        def argument(value: int, name: str, events: list[str]) -> Index:
            events.append('make:' + name)
            return Index(value, name, events)
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            rows = [repr(list(range(argument(3, 'one', events)))),
                    repr(list(range(argument(1, 'start', events), argument(4, 'stop', events)))),
                    repr(list(range(argument(7, 'start', events), argument(0, 'stop', events),
                                    argument(-2, 'step', events))))]
            for start, stop, step in [(99, 4, 1), (1, 99, 1), (1, 4, 99), (1, 4, 0)]:
                try:
                    range(argument(start, 'start', events), argument(stop, 'stop', events),
                          argument(step, 'step', events))
                except ValueError as error:
                    rows.append(str(error))
            rows.append(repr(list(range(False, True))))
            total = 0
            for value in range(argument(4, 'loop', events)):
                total += value
            rows.append(str(total))
            rows.append(repr(events))
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_enumerate_converts_start_before_acquisition_and_preserves_keyword_order(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, events: list[str], fail: bool):
                self.events, self.fail = events, fail
            def __index__(self) -> int:
                self.events.append('index')
                gc_collect()
                if self.fail:
                    raise ValueError('start failed')
                return -3
        class Source:
            def __init__(self, events: list[str]):
                self.events = events
            def __iter__(self) -> Iterator[int]:
                self.events.append('iter')
                gc_collect()
                return iter([7, 8])
        def start(events: list[str], fail: bool) -> Index:
            events.append('start expression')
            return Index(events, fail)
        def source(events: list[str]) -> Source:
            events.append('source expression')
            return Source(events)
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            rows = [repr(list(enumerate(source(events), start(events, False)))),
                    repr(list(enumerate(start=start(events, False), iterable=source(events)))),
                    repr(list(enumerate(iterable=source(events), start=start(events, False))))]
            try:
                enumerate(source(events), start(events, True))
            except ValueError as error:
                rows.append(str(error))
            rows.append(repr(list(enumerate([9], True))))
            rows.append(repr(events))
            return '|'.join(rows)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_index_constructors_dispatch_base_erased_optional_and_tagged_values(optimize):
    result = LLVM().assert_matches_python('''
        from enum import IntEnum
        from pyjs import int8, int64
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            pass
        class Index(Base):
            def __index__(self) -> int:
                gc_collect()
                return 2
        class Number(IntEnum):
            TWO = 2
        def nominal(value: Base) -> str:
            try:
                return repr((list(range(value)), list(enumerate([9], value))))
            except TypeError:
                return 'type-error'
        def erased(value: object) -> str:
            rows: list[str] = []
            try:
                rows.append(repr(list(range(value))))
            except TypeError:
                rows.append('range type-error')
            try:
                rows.append(repr(list(enumerate([9], value))))
            except TypeError:
                rows.append('enumerate type-error')
            return '|'.join(rows)
        def tagged(value: int | str | Index | None) -> str:
            try:
                return repr((list(range(value)), list(enumerate([9], value))))
            except TypeError:
                return 'type-error'
        def optional(value: Index | None) -> str:
            try:
                return repr((list(range(value)), list(enumerate([9], value))))
            except TypeError:
                return 'type-error'
        def main() -> str:
            gc_set_threshold(1)
            return '|'.join([nominal(Index()), nominal(Base()), erased(Index()), erased(2),
                erased(True), erased(None), erased('bad'), erased(1.5),
                tagged(Index()), tagged(2), tagged(True), tagged(None), tagged('bad'),
                optional(Index()), optional(None),
                repr((list(range(Number.TWO)), list(enumerate([9], Number.TWO)),
                      list(range(int8(2))), list(enumerate([9], int64(2)))))])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("consumer", ["range(Index())", "enumerate([1], Index())"])
@pytest.mark.parametrize("definition", [
    "@property\n    def __index__(self) -> int:\n        return 1",
    "@staticmethod\n    def __index__() -> int:\n        return 1",
])
def test_index_constructors_reject_unsupported_protocol_shapes(consumer, definition):
    with pytest.raises(LLVMUnsupported, match="__index__ requires an instance method returning int"):
        transpile_llvm(f"class Index:\n    {definition}\ndef main():\n    return list({consumer})\n")


@pytest.mark.parametrize("expression", ["range(None)", "range(1, None)", "range(1, 2, None)",
    "range(1.5)", "enumerate([1], None)", "enumerate([1], 1.5)", "enumerate([1], 'bad')"])
def test_explicit_invalid_constructor_arguments_raise_at_runtime(expression):
    # Explicit None is not an omitted constructor argument. Direct scalars also
    # reach a different storage path from the erased-value controls above.
    result = LLVM().assert_matches_python(f'''
        def main() -> int:
            try:
                {expression}
            except TypeError:
                return 0
            return 1
    ''', optimize=2, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", ["len(range(Index(3)))", "next(enumerate([7], Index(3)))[0]"])
def test_index_constructor_allocation_failures_unwind_and_recover(tmp_path, optimize, expression):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm
        class Index:
            def __init__(self, value: int):
                self.value = value
            def __index__(self) -> int:
                temporary = [self.value]
                gc_collect()
                return temporary[0]
        def construct() -> int:
            return {expression}
        def main() -> int:
            caught = 0
            for attempt in range(1, 40):
                succeeded = False
                arm(attempt)
                try:
                    assert construct() == 3
                    succeeded = True
                except MemoryError:
                    caught += 1
                finally:
                    arm(0)
                gc_collect()
                assert construct() == 3
                if succeeded:
                    return 0 if caught else 1
            return 2
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
