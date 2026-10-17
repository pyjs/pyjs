import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


def test_plain_classes_do_not_expand_each_erased_repetition_site():
    def lines(classes, sites):
        definitions = ''.join(f'class Plain{i}:\n    pass\n' for i in range(classes))
        keep = ''.join(f'    keep.append(Plain{i}())\n' for i in range(classes))
        repeats = ''.join(f'    result += len([{i}] * count)\n' for i in range(sites))
        return str(transpile_llvm(definitions + '''
def repeat(count: object) -> int:
    result = 0
''' + repeats + '''    return result
def main() -> int:
    keep: list[object] = []
''' + keep + '    return repeat(2)\n')).count('\n')

    # Compare marginal cost, not a brittle absolute IR-size snapshot. Unrelated
    # classes still need constructors/vtables, but not per-site binary calls.
    assert lines(20, 4) - lines(20, 1) == lines(0, 4) - lines(0, 1)


def test_erased_repetition_names_an_incompatible_hidden_numeric_method():
    with pytest.raises(LLVMUnsupported, match=r"analyzed type for Vec\.__rmul__"):
        transpile_llvm('''
            class Vec:
                def __rmul__(self, other: float) -> list[int]:
                    return [1]
            def repeat(count: object) -> list[int]:
                return [0] * count
            def main() -> str:
                value = Vec()
                return repr(repeat(2)) + repr(value)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_invalid_erased_counts_use_value_errors_not_layout_diagnostics(optimize):
    result = LLVM().assert_matches_python('''
        class Plain:
            pass
        def repeat(count: object) -> str:
            try:
                return repr([1] * count)
            except TypeError as error:
                assert 'layout' not in str(error)
                return 'invalid count'
        def main() -> str:
            return repeat([2]) + repeat((2,)) + repeat(Plain())
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_operator_repetition_preserves_erased_numeric_priority(optimize):
    result = LLVM().assert_matches_python('''
        import operator
        from pyjs.native import gc_collect, gc_set_threshold
        class Index:
            def __index__(self) -> int:
                gc_collect()
                return 2
        class Override(Index):
            def __mul__(self, values: list[int]) -> list[int]:
                gc_collect()
                return [31]
            def __rmul__(self, values: list[int]) -> list[int]:
                values.append(9)
                gc_collect()
                return [42]
        def run(count: object) -> str:
            values = [1]
            alias = values
            forward = operator.mul(values, count)
            reflected = operator.mul(count, values)
            values = operator.imul(values, count)
            return repr((forward, reflected, values, alias, values is alias))
        def main() -> str:
            gc_set_threshold(1)
            return run(Index()) + run(Override()) + run(2)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_counts_validate_each_sequence_without_mutating_on_failure(optimize):
    result = LLVM().assert_matches_python('''
        from enum import IntEnum
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        class Number(IntEnum):
            TWO = 2
        class Index:
            def __index__(self) -> int:
                gc_collect()
                return 2
        class Disabled(Index):
            __mul__ = None
            __rmul__ = None
        class Invalid:
            def __index__(self) -> str:
                return 'wrong'
        def run(count: object, mode: int) -> str:
            values = [7]
            alias = values
            try:
                if mode == 0:
                    return repr(values * count)
                if mode == 1:
                    return repr(count * values)
                if mode == 2:
                    return repr((7,) * count)
                if mode == 3:
                    return repr(count * (7,))
                if mode == 4:
                    return repr('a' * count)
                if mode == 5:
                    return repr(count * 'a')
                if mode == 6:
                    return repr(b'a' * count)
                if mode == 7:
                    return repr(count * b'a')
                values *= count
                return repr((values, alias, values is alias))
            except TypeError:
                assert values == [7]
                assert values is alias
                return 'TypeError'
        def main() -> str:
            gc_set_threshold(1)
            counts: list[object] = [Index(), Disabled(), Invalid(), None, 1.5,
                                   '2', 0, -1, 2, True, False, int(Number.TWO)]
            counts.append(int(int8(258)))
            return repr([run(count, mode) for count in counts for mode in range(9)])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_index_consumers_share_callback_selection(optimize):
    result = LLVM().assert_matches_python('''
        from itertools import islice, repeat
        from math import factorial, gcd
        from pyjs.native import gc_collect, gc_set_threshold

        class Position:
            def __init__(self, events: list[int]):
                self.events = events

            def __index__(self) -> int:
                self.events.append(2)
                gc_collect()
                return 2

        def inspect(value: object) -> str:
            values = [1, 2, 3, 4]
            result = [str(values[value]), str((1, 2, 3, 4)[value]), "abcd"[value], repr(b"abcd"[value])]
            result.extend([repr(values * value), repr("a" * value), repr(b"a" * value)])
            result.extend([repr(values[value:]), repr("abcd"[value:]), repr(b"abcd"[value:])])
            result.extend([repr(list(range(value))), repr(list(enumerate(values, start=value)))])
            result.extend([str(factorial(value)), str(gcd(value, 6)), bin(value), chr(value), hex(value), oct(value)])
            result.extend([repr(list(islice(values, value))), repr(list(repeat(5, times=value)))])
            result.extend(["a\tb".expandtabs(tabsize=value), "ababa".replace("a", "c", count=value)])
            result.append(repr("a,b,c,d".split(",", maxsplit=value)))
            return repr(result)

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            result = inspect(Position(events))
            gc_collect()
            return result + repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))

    assert not result.native.stderr
