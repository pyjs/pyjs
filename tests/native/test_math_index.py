import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_math_converts_after_all_expressions_and_before_validation(optimize):
    result = LLVM().assert_matches_python('''
        import math
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, value: int, events: list[int]):
                self.value, self.events = value, events
            def __index__(self) -> int:
                self.events.append(self.value)
                gc_collect()
                if self.value == 99:
                    raise LookupError('index failed')
                return self.value
        def argument(value: int, events: list[int]) -> Index:
            events.append(1000 + value)
            gc_collect()
            if value == 98:
                raise LookupError('argument failed')
            return Index(value, events)
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            answers = [math.isqrt(argument(81, events)), math.factorial(argument(5, events)),
                math.comb(argument(5, events), argument(2, events)),
                math.perm(argument(5, events), argument(2, events)),
                math.perm(argument(4, events)),
                math.gcd(argument(18, events), argument(24, events)),
                math.lcm(argument(6, events), argument(8, events))]
            assert answers == [9, 120, 10, 20, 24, 6, 24]
            assert events == [1081, 81, 1005, 5, 1005, 1002, 5, 2,
                1005, 1002, 5, 2, 1004, 4, 1018, 1024, 18, 24, 1006, 1008, 6, 8]
            events.clear()
            assert math.comb(argument(5, events), argument(2, events)) == 10
            assert events == [1005, 1002, 5, 2]
            events.clear()
            try:
                math.comb(argument(5, events), argument(98, events))
            except LookupError:
                assert events == [1005, 1098]
            else:
                return 'converted before argument failure'
            events.clear()
            try:
                math.comb(argument(-1, events), argument(99, events))
            except LookupError:
                assert events == [999, 1099, -1, 99]
            else:
                return 'domain checked before conversion'
            events.clear()
            try:
                math.perm(argument(-1, events), argument(99, events))
            except LookupError:
                assert events == [999, 1099, -1, 99]
            else:
                return 'perm domain checked before conversion'
            events.clear()
            try:
                math.lcm(argument(0, events), argument(99, events))
            except LookupError:
                assert events == [1000, 1099, 0, 99]
            else:
                return 'zero skipped conversion'
            events.clear()
            try:
                math.gcd(argument(99, events), argument(1, events))
            except LookupError:
                assert events == [1099, 1001, 99]
            else:
                return 'missing callback error'
            assert math.comb(Index(5, events), Index(2, events)) == 10
            return repr(answers)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_math_dispatches_protocols_without_int_coercion(optimize):
    result = LLVM().assert_matches_python('''
        import math
        from enum import IntEnum
        from pyjs.native import gc_collect
        class Base:
            pass
        class Index(Base):
            def __index__(self) -> int:
                gc_collect()
                return 4
        class Other(Index):
            def __index__(self) -> int:
                gc_collect()
                return 9
        class IntOnly:
            def __int__(self) -> int:
                raise LookupError('must not use int')
        class Count(IntEnum):
            FOUR = 4
        def nominal(value: Base) -> str:
            try:
                return str(math.isqrt(value))
            except TypeError:
                return 'bad'
        def erased(value: object) -> str:
            try:
                return str(math.factorial(value))
            except TypeError:
                return 'bad'
        def tagged(value: Index | int | None | str) -> str:
            try:
                return str(math.gcd(value, 6))
            except TypeError:
                return 'bad'
        def perm(value: object) -> str:
            try:
                return str(math.perm(Index(), value))
            except TypeError:
                return 'bad'
        def main() -> str:
            return repr((nominal(Index()), nominal(Other()), nominal(Base()),
                erased(Index()), erased(Other()), erased(5), erased(True),
                erased(None), erased('3'), erased(1.5), erased(IntOnly()),
                tagged(Index()), tagged(Other()), tagged(12), tagged(None), tagged('bad'),
                perm(None), perm(Index()), perm(2), perm(1.5), math.isqrt(Count.FOUR)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_math_nested_calls_portable_inputs_and_stored_callbacks(optimize):
    result = LLVM().assert_matches_python('''
        import math
        from collections.abc import Callable
        from math import comb as choose
        from pyjs import int8, int64, uint32
        class Index:
            def __init__(self, value: int):
                self.value = value
            def __index__(self) -> int:
                return self.value
        def optional(value: int8 | None) -> int:
            return math.perm(int8(5), value)
        def main() -> str:
            factorial = math.factorial
            pair = math.comb
            assert factorial(Index(5)) == 120
            assert pair(Index(5), Index(2)) == 10
            typed: Callable[[int], int] = math.factorial
            protocol: Callable[[Index], int] = math.isqrt
            assert typed(6) == 720 and protocol(Index(81)) == 9
            assert math.gcd() == 0 and math.lcm() == 1
            assert math.gcd(True, False) == 1
            assert math.factorial(int8(6)) == 720
            assert math.isqrt(uint32(4294967295)) == 65535
            assert math.gcd(int64(9007199254740993), int64(3)) == 3
            assert math.comb(int8(10), int8(5)) == 252
            assert optional(int8(2)) == 20 and optional(None) == 120
            # Nested lexical bindings must not overwrite an outer argument.
            return repr((choose(Index(5), Index(math.isqrt(Index(4)))),
                math.gcd(Index(18), math.lcm(Index(4), Index(6))),
                math.perm(Index(4), None)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_math_binding_survives_generator_suspension(optimize):
    result = LLVM().assert_matches_python('''
        import math
        from collections.abc import Generator
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, events: list[int]):
                self.events = events
            def __index__(self) -> int:
                self.events.append(5)
                gc_collect()
                return 5
        def calculate(events: list[int]) -> Generator[int, int, None]:
            yield math.comb(Index(events), (yield 1))
        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            iterator = calculate(events)
            assert next(iterator) == 1 and events == []
            gc_collect()
            assert iterator.send(2) == 10 and events == [5]
            assert next(iterator, None) is None
            return repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", ["math.gcd(*[1, 2])", "math.isqrt(*[4])"])
def test_integer_math_packs_keep_a_located_boundary(expression):
    with pytest.raises(LLVMUnsupported, match="statically known parameters") as caught:
        transpile_llvm(f"import math\ndef main() -> int:\n    return {expression}\n")
    assert caught.value.node.lineno == 2


def test_integer_math_invalid_index_descriptor_has_original_location():
    with pytest.raises(LLVMUnsupported, match="instance method returning int") as caught:
        transpile_llvm('''
            import math
            class Index:
                @property
                def __index__(self) -> int:
                    return 1
            def main() -> int:
                return math.isqrt(Index())
        ''')
    assert caught.value.node.lineno == 2


def test_stored_variadic_math_keeps_shared_callable_boundary():
    with pytest.raises(CompilationError, match="Callable expects 0 arguments, got 2"):
        transpile_llvm('''
            import math
            def main() -> int:
                gcd = math.gcd
                return gcd(18, 24)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_math_nested_lexical_bindings_shadow_outer_substitutions(optimize):
    result = LLVM().assert_matches_python('''
        import math
        from pyjs.native import gc_collect
        class Index:
            def __init__(self, value: int, events: list[int]):
                self.value, self.events = value, events
            def __index__(self) -> int:
                self.events.append(self.value)
                gc_collect()
                return self.value
        def choose(flag: bool) -> int:
            return math.comb(5 if flag else 6, math.comb(4, 2) - 4)
        def gcd(flag: bool) -> int:
            return math.gcd(12 if flag else 18, math.lcm(2, 3))
        def main() -> str:
            events: list[int] = []
            custom = math.perm(Index(5, events), math.isqrt(Index(4, events)))
            assert events == [4, 5]
            return repr((math.perm(9, math.isqrt(4)), math.perm(6, math.isqrt(4)),
                math.comb(math.perm(4, 1) + 1, math.comb(4, 2) - 4),
                choose(True), choose(False), gcd(True), gcd(False), custom))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_math_lexical_bindings_are_not_closure_captures(optimize):
    result = LLVM().assert_matches_python('''
        import math
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, value: int):
                self.value = value
            def __index__(self) -> int:
                gc_collect()
                return self.value
        def main() -> str:
            gc_set_threshold(1)
            offset = 1
            callback: Callable[[int], int] = lambda value: math.isqrt(value) + offset
            nested: Callable[[int], Callable[[int], int]] = lambda n: lambda k: math.comb(n, k)
            items = [math.factorial(value) for value in range(5)]
            gcds = [math.gcd(value, 6) for value in range(5)]
            roots = {value: math.isqrt(value) for value in range(4)}
            indexes = [math.factorial(Index(value)) for value in range(5)]
            squares = sum(math.isqrt(value) for value in range(10))
            offset = 3
            choose = nested(6)
            gc_collect()
            return repr((items, gcds, roots, indexes, squares, callback(9), choose(2)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_math_starmap_adapts_fixed_arity_callbacks(optimize):
    result = LLVM().assert_matches_python('''
        import math
        from itertools import starmap
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __init__(self, value: int):
                self.value = value
            def __index__(self) -> int:
                gc_collect()
                return self.value
        def main() -> str:
            gc_set_threshold(1)
            integers = list(starmap(math.comb, [(5, 2), (6, 3)]))
            optional_rows: list[tuple[int, int | None]] = [(4, None), (5, 2)]
            optional = list(starmap(math.perm, optional_rows))
            indexed = starmap(math.comb, [(Index(5), Index(2)), (Index(-1), Index(2)), (Index(6), Index(3))])
            assert next(indexed) == 10
            try:
                next(indexed)
            except ValueError:
                pass
            else:
                return 'missing domain error'
            assert next(indexed) == 20 and next(indexed, None) is None
            return repr((integers, optional))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_integer_math_lexical_lowering_keeps_surrounding_expression_order(optimize):
    result = LLVM().assert_matches_python('''
        import math
        def record(events: list[int], value: int) -> int:
            events.append(value)
            return value
        def pair(left: int, right: int) -> int:
            return left + right
        def guarded(flag: bool, events: list[int]) -> bool:
            return flag and math.isqrt(record(events, 9)) == 3
        def main() -> str:
            events: list[int] = []
            first = pair(record(events, 1), math.factorial(record(events, 3)))
            assert first == 7 and events == [1, 3]
            events.clear()
            second = record(events, 2) + math.isqrt(record(events, 9))
            assert second == 5 and events == [2, 9]
            events.clear()
            values = (record(events, 4), math.factorial(record(events, 3)), record(events, 5))
            assert values == (4, 6, 5) and events == [4, 3, 5]
            events.clear()
            assert not guarded(False, events)
            assert events == []
            assert guarded(True, events) and events == [9]
            return repr(values)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
