import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_index_direct_and_lazy_callbacks_keep_effects_and_roots(optimize):
    result = LLVM().assert_matches_python('''
        import operator
        from collections.abc import Callable
        from operator import index as as_index
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, value: int, events: list[int]):
                self.value, self.events = value, events
            def __index__(self) -> int:
                self.events.append(self.value)
                gc_collect()
                if self.value == 99:
                    raise ValueError('bad index')
                return self.value
        def converted(value: Index) -> int:
            return operator.index(value)
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            direct = operator.index(Index(20, events))
            values = [Index(10, events), Index(99, events), Index(12, events)]
            mapped = map(operator.index, values)
            assert events == [20]
            first = next(mapped)
            try:
                next(mapped)
            except ValueError as error:
                assert str(error) == 'bad index'
            else:
                return 'missing error'
            last = next(mapped)
            assert next(mapped, None) is None
            filtered = list(filter(as_index, [Index(0, events), Index(7, events)]))
            gc_collect()
            assert len(filtered) == 1 and filtered[0].value == 7
            callback: Callable[[Index], int] = converted
            assert callback(Index(3, events)) == 3
            return repr((direct + first + last, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_index_dispatches_nominal_erased_and_tagged_values(optimize):
    result = LLVM().assert_matches_python('''
        import operator
        from enum import IntEnum
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            pass
        class Index(Base):
            def __index__(self) -> int:
                gc_collect()
                return 7
        class Other(Index):
            def __index__(self) -> int:
                gc_collect()
                return 9
        class IntOnly:
            def __int__(self) -> int:
                raise ValueError('must not use int')
        class Count(IntEnum):
            TWO = 2
        def erased(value: object) -> str:
            try:
                return str(operator.index(value))
            except TypeError:
                return 'bad'
        def nominal(value: Base) -> str:
            try:
                return str(operator.index(value))
            except TypeError:
                return 'bad'
        def tagged(value: int | Index | str | None) -> str:
            try:
                return str(operator.index(value))
            except TypeError:
                return 'bad'
        def main() -> str:
            gc_set_threshold(1)
            return repr((erased(Index()), erased(Other()), erased(True), erased(5),
                erased(None), erased(1.5), erased('5'), erased(IntOnly()),
                nominal(Index()), nominal(Other()), nominal(Base()),
                tagged(Index()), tagged(Other()), tagged(True), tagged(5), tagged('bad'), tagged(None),
                operator.index(Count.TWO)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["Index", "object", "Index | int"])
def test_disabled_inherited_index_and_reenabled_override(annotation, optimize):
    result = LLVM().assert_matches_python(f'''
        from operator import index
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, events: list[str]): self.events = events
            def __index__(self) -> int:
                self.events.append('base')
                gc_collect()
                return 1
        class Disabled(Index):
            __index__ = None
        class Reenabled(Disabled):
            def __index__(self) -> int:
                self.events.append('reenabled')
                gc_collect()
                return 2
        def consume(count: {annotation}) -> str:
            rows: list[str] = []
            values = [10, 20, 30]
            alias = values
            try: rows.append(str(index(count)))
            except TypeError: rows.append('bad index')
            try: rows.append(str(values[count]))
            except TypeError: rows.append('bad subscript')
            try: rows.append(repr([1] * count))
            except TypeError: rows.append('bad repeat')
            try: rows.append(repr([1].__mul__(count)))
            except TypeError: rows.append('bad explicit repeat')
            try: values *= count
            except TypeError: rows.append('bad inplace')
            rows.append(repr((values, values is alias)))
            return repr(rows)
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            disabled = consume(Disabled(events))
            try: [1] * Disabled(events)
            except TypeError: disabled += ':direct disabled'
            assert events == []
            live = consume(Index(events))
            restored = consume(Reenabled(events))
            return repr((disabled, live, restored, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_index_is_explicit_conversion_from_portable_integer_formats(optimize):
    result = LLVM().assert_matches_python('''
        import operator
        from operator import index
        from _operator import index as implementation_index
        from pyjs import int8, int64, uint32
        def main() -> str:
            ordinary = index(int8(-128))
            assert ordinary - 1 == -129
            return repr((ordinary, implementation_index(7), operator.index(uint32(4294967295)),
                list(map(operator.index, [int8(-128), int8(127)])),
                list(map(index, [int64(9007199254740993)]))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_operator_index_analysis_returns_an_ordinary_integer():
    with analyze_source('''
        import operator
        from pyjs import int8
        def main() -> int:
            return operator.index(int8(7))
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        assert analysis.entry_point.return_type.generic_name == 'int'
        assert analysis.entry_point.return_representation is None


@pytest.mark.parametrize("definition", [
    "@property\n    def __index__(self) -> int:\n        return 1",
    "@staticmethod\n    def __index__() -> int:\n        return 1",
])
def test_operator_index_rejects_unsupported_protocol_shapes(definition):
    with pytest.raises(LLVMUnsupported, match="__index__ requires an instance method returning int"):
        transpile_llvm(f"import operator\nclass Index:\n    {definition}\n"
                       "def main() -> int:\n    return operator.index(Index())\n")


@pytest.mark.parametrize("optimize", [0, 2])
def test_index_named_application_callback_keeps_receiver_evaluation(optimize):
    result = LLVM().assert_matches_python('''
        class Holder:
            def index(self, value: int) -> int:
                return value + 10
        def holder(events: list[str]) -> Holder:
            events.append('receiver')
            return Holder()
        def items(events: list[str]) -> list[int]:
            events.append('items')
            return [1, 2]
        def main() -> str:
            events: list[str] = []
            result = list(map(holder(events).index, items(events)))
            return repr((result, events))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", ["operator.index()", "operator.index(1, 2)", "operator.index(value=1)"])
def test_operator_index_preserves_positional_only_call_shape(expression):
    with pytest.raises(CompilationError):
        transpile_llvm(f'import operator\ndef main() -> int:\n    return {expression}\n')


def test_operator_index_callback_requires_one_iterable():
    with pytest.raises(CompilationError, match="conversion callbacks require exactly one iterable"):
        transpile_llvm('''
            import operator
            def main() -> str:
                return repr(list(map(operator.index, [1], [2])))
        ''')


@pytest.mark.parametrize("body, message", [
    ("return operator.index(*[1])", "operator.index takes one positional argument"),
    ("callback: Callable[[int], int] = operator.index\n    return callback(1)",
     "function values require an application function with fixed positional parameters"),
])
def test_operator_index_retains_pack_and_first_class_boundaries(body, message):
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f"import operator\nfrom collections.abc import Callable\n"
                       f"def main() -> int:\n    {body}\n")
