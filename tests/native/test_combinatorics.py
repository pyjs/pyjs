import ast
from textwrap import dedent

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.ir import Lambda
from pyjs.analysis.lifetime import LifetimeBoundary
from pyjs.analysis.source import analyze_source
from pyjs.analysis.value_representation import analyzed_representation
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.numeric import NumericFormat
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_starmap_uses_checked_callback_argument_adaptation(optimize):
    result = LLVM().assert_matches_python('''
        from itertools import starmap
        from pyjs.native import gc_collect, gc_set_threshold
        class Base:
            def __init__(self, value: int):
                self.value = value
        class Child(Base):
            pass
        def boxed(left: object, right: object) -> str:
            gc_collect()
            return repr((left, right))
        def nominal(left: Base, right: Base) -> int:
            gc_collect()
            return left.value + right.value
        def main() -> str:
            gc_set_threshold(1)
            values = list(starmap(boxed, [(1, 'a'), (2, 'b')]))
            flags = list(starmap(boxed, [(True, 'a'), (False, 'b')]))
            objects = list(starmap(nominal, [(Child(2), Child(3))]))
            return repr((values, flags, objects))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("argument, parameter", [("'bad'", "int"), ("int8(5)", "int"), ("float32(5)", "float")])
def test_starmap_rejects_incompatible_types_or_representations(argument, parameter):
    with pytest.raises(CompilationError, match="matching callback argument types and representations"):
        transpile_llvm(f'''
            from itertools import starmap
            from pyjs import int8, float32
            def read(value: {parameter}) -> {parameter}:
                return value
            def main() -> str:
                return repr(list(starmap(read, [({argument},)])))
        ''')


def test_starmap_union_rows_have_a_focused_diagnostic():
    with pytest.raises(CompilationError, match="native starmap requires typed tuple rows"):
        transpile_llvm('''
            import math
            from itertools import starmap
            def main() -> str:
                return repr(list(starmap(math.perm, [(4, None), (5, 2)])))
        ''')


@pytest.mark.parametrize("value, parameter", [("3", "float"), ("True", "int")])
def test_starmap_numeric_promotion_keeps_explicit_conversion_boundary(value, parameter):
    with pytest.raises(LLVMUnsupported, match="explicit numeric conversion") as caught:
        transpile_llvm(f'''
            from itertools import starmap
            def read(value: {parameter}) -> {parameter}:
                return value
            def main() -> str:
                return repr(list(starmap(read, [({value},)])))
        ''', filename="starmap_numeric.py")
    assert caught.value.__notes__ == [
        "Source location: starmap_numeric.py:6:22 "
        "(iterator_step.0; reported line above is function-relative)"
    ]


@pytest.mark.parametrize("optimize", [0, 2])
def test_map_projects_tuple_items_into_erased_callback_parameters(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
def read(value: tuple[object, object]) -> str:
    gc_collect()
    return repr(value)
def main() -> str:
    gc_set_threshold(1)
    return repr(list(map(read, [(3, 4), (5, 6)])))
''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


def test_iterator_callback_storage_diagnostic_locates_creation_call():
    source = (
        "from itertools import starmap\n"
        "def read(value: tuple[object, object]) -> str:\n"
        "    return repr(value)\n\n\n\n"
        "def main() -> str:\n"
        "    return repr(list(starmap(read, [((3, 4),)])))\n"
    )
    with pytest.raises(LLVMUnsupported) as caught:
        transpile_llvm(source, filename="iterator_storage.py")
    assert caught.value.__notes__ == [
        "Source location: iterator_storage.py:8:22 "
        "(iterator_step.0; reported line above is function-relative)"
    ]


@pytest.mark.parametrize("optimize", [0, 2])
def test_pooled_iteration_order_and_empty_rows(optimize):
    LLVM().assert_matches_python('''
        from itertools import product, combinations, combinations_with_replacement, permutations, starmap

        def add(left: int, right: int) -> int:
            return left + right

        def main() -> str:
            result = ""
            for length in range(5):
                for width in range(5):
                    for row in combinations(range(length), width):
                        result += "c" + ','.join(str(x) for x in row) + ";"
                    for row in combinations_with_replacement(range(length), width):
                        result += "r" + ','.join(str(x) for x in row) + ";"
                    for row in permutations(range(length), width):
                        result += "p" + ','.join(str(x) for x in row) + ";"
                for count in range(4):
                    for row in product(range(length), [6, 7], repeat=count):
                        result += "x" + ','.join(str(x) for x in row) + ";"
            assert list(starmap(add, [(1, 2), (3, 4)])) == [3, 7]
            assert list(starmap(add, combinations([1, 2, 3], 2))) == [3, 4, 5]
            assert [list(row) for row in permutations([1, 2])] == [[1, 2], [2, 1]]
            assert [list(row) for row in permutations([1, 2], None)] == [[1, 2], [2, 1]]
            assert len(list(product())) == 1
            assert len(list(product(repeat=0))) == 1
            assert len(list(product((), [1]))) == 0
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_product_remains_exhausted_with_empty_and_nonempty_pools(tmp_path, optimize):
    # Homogeneous pooled rows intentionally keep a variadic tuple type even
    # when this call happens to have two pools; the runtime contract is unchanged.
    comparison = LLVM().assert_matches_python('''
        from itertools import product

        def main() -> str:
            iterator = product([1], [2, 3])
            rows = list(iterator)
            empty: list[int] = []
            left = product(empty, [2, 3])
            right = product([1], empty)
            results: list[tuple[int, ...]] = []
            for _ in range(4):
                results.append(next(iterator, (-1, -1)))
                results.append(next(left, (-1, -1)))
                results.append(next(right, (-1, -1)))
            return str((rows, results))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_pool_snapshot_consumption_and_constructor_errors(optimize):
    LLVM().assert_matches_python('''
        from itertools import product, combinations, combinations_with_replacement, permutations

        def record(events: list[int], value: int) -> int:
            events.append(value)
            return value

        def size(events: list[int], value: int) -> int:
            events.append(9)
            return value

        def main() -> str:
            events: list[int] = []
            source = [1, 2, 3]
            rows = combinations(map(lambda n: record(events, n), source), size(events, 2))
            assert events == [9, 1, 2, 3]
            source.clear()
            assert [list(row) for row in rows] == [[1, 2], [1, 3], [2, 3]]
            assert list(rows) == []
            events.clear()
            empty = product(map(lambda n: record(events, n), range(3)), repeat=size(events, 0))
            assert events == [9] and len(list(empty)) == 1 and len(list(empty)) == 0
            source = [1, 2]
            repeated = product(source, repeat=2)
            source[0] = 7
            assert [list(row) for row in repeated] == [[1, 1], [1, 2], [2, 1], [2, 2]]
            shared = iter(range(3))
            assert len(list(product(shared, shared))) == 0
            empty_pool: list[int] = []
            events.clear()
            assert len(list(product(empty_pool, map(lambda n: record(events, n), range(3))))) == 0
            assert events == [0, 1, 2]
            errors = ""
            for width in [-1, -2]:
                events.clear()
                try:
                    combinations(map(lambda n: record(events, n), range(3)), width)
                except ValueError as error:
                    errors += str(error)
                assert events == [0, 1, 2]
                events.clear()
                try:
                    combinations_with_replacement(map(lambda n: record(events, n), range(3)), width)
                except ValueError as error:
                    errors += str(error)
                assert events == [0, 1, 2]
                events.clear()
                try:
                    permutations(map(lambda n: record(events, n), range(3)), width)
                except ValueError as error:
                    errors += str(error)
                assert events == [0, 1, 2]
                events.clear()
                try:
                    product(map(lambda n: record(events, n), range(3)), repeat=width)
                except ValueError as error:
                    errors += str(error)
                assert events == []
            assert [list(row) for row in combinations(r=2, iterable=[1, 2])] == [[1, 2]]
            assert [list(row) for row in permutations(r=1, iterable=[1, 2])] == [[1], [2]]
            assert [list(row) for row in combinations_with_replacement(r=1, iterable=[1])] == [[1]]
            return errors
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_pools_retain_objects_and_independent_rows(optimize, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import product, combinations, combinations_with_replacement, permutations, starmap
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: str):
                self.value = value

        def make() -> Iterator[tuple[Box, ...]]:
            return permutations([Box("a" + "1"), Box("b" + "2"), Box("c" + "3")], 2)

        def read(items: list[Box], left: Box, right: Box) -> str:
            items.clear()
            gc_collect()
            return left.value + right.value

        def main() -> str:
            gc_set_threshold(1)
            rows = make()
            gc_collect()
            first = next(rows)
            second = next(rows)
            assert first is not second and first[0] is second[0]
            first[0].value = "changed"
            assert second[0].value == "changed" and first[1].value == "b2"
            remaining = list(rows)
            gc_collect()
            assert len(remaining) == 4 and first[1].value == "b2"
            source = [Box("x"), Box("y")]
            choices = combinations(source, 2)
            repeats = combinations_with_replacement(source, 2)
            pairs = product(source, repeat=2)
            source.clear()
            gc_collect()
            assert len(list(choices)) == 1 and len(list(repeats)) == 3
            result = ""
            for row in pairs:
                gc_collect()
                result += row[0].value + row[1].value
            source = [Box("left"), Box("right")]
            calls = starmap(lambda a, b: read(source, a, b), combinations(source, 2))
            result += next(calls)
            assert source == []
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_starmap_callbacks_errors_reentry_and_rows(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import starmap, batched

        def checked(events: list[int], left: int, right: int) -> int:
            events.append(left)
            if left == 3:
                raise ValueError("three")
            if left == 5:
                raise StopIteration("five")
            return left + right

        def nested(cursors: list[Iterator[int]], left: int, right: int) -> int:
            if left == 1:
                return next(cursors[0]) + left + right
            return left + right

        def describe(number: int, text: str) -> str:
            return str(number) + text

        def nothing() -> int:
            return 42

        def main() -> str:
            events: list[int] = []
            rows = starmap(lambda a, b: checked(events, a, b), batched(range(1, 10), 2))
            assert events == []
            assert next(rows) == 3
            error = ""
            try:
                next(rows)
            except ValueError as caught:
                error = str(caught)
            assert next(rows, -1) == -1 and next(rows) == 15
            try:
                next(rows)
            except TypeError:
                error += "arity"
            assert events == [1, 3, 5, 7] and list(rows) == []
            cursors: list[Iterator[int]] = []
            stream = starmap(lambda a, b: nested(cursors, a, b), [(1, 2), (3, 4), (5, 6)])
            cursors.append(stream)
            assert list(stream) == [10, 11]
            assert list(starmap(nothing, [(), ()])) == [42, 42]
            return error + ''.join(starmap(describe, [(1, "a"), (2, "b")]))
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_pooled_portable_representations(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Callable
        from itertools import product, combinations, combinations_with_replacement, permutations, starmap
        from pyjs import int8, float32

        class Adder:
            def __init__(self, value: int8):
                self.value = value

            def add(self, left: int8, right: int8) -> int8:
                return self.value + left + right

        def rounded(left: float32, right: float32) -> float32:
            return left + right

        def main() -> int:
            values = [int8(127), int8(1)]
            adder = Adder(int8(1))
            callback: Callable[[int8, int8], int8] = adder.add
            assert list(starmap(callback, product(values, repeat=2))) == [int8(-1), int8(-127), int8(-127), int8(3)]
            for row in combinations(values, 1):
                assert row[0] + int8(1) in [int8(-128), int8(2)]
            for row in permutations(values, 1):
                assert row[0] + int8(1) in [int8(-128), int8(2)]
            for row in combinations_with_replacement(values, 1):
                assert row[0] + int8(1) in [int8(-128), int8(2)]
            floats = [float32(16777216.0), float32(1.0)]
            assert list(starmap(rounded, combinations(floats, 2))) == [float32(16777216.0)]
            return 0
    ''', optimize=optimize)


def test_starmap_lambda_ir_and_recursive_representations():
    source = '''
from itertools import product, starmap
from pyjs import int8
def main() -> int8:
    return next(starmap(lambda left, right: left + right, product([int8(127)], [int8(1)])))
'''
    with analyze_source(source, environment=NATIVE_ENVIRONMENT, wrap=False) as analysis:
        assert analysis.types.strip() == dedent('''
            def product(*iterables: tuple__Iterable__object__variadic, repeat: int=1) -> Iterator[tuple[object, ...]]:
                external

            def starmap(function: Callable[..., R], iterable: Iterable__object, /) -> Iterator[R]:
                external

            def main() -> int:
                block entry:
                    return next(starmap(lambda left, right:
                        block entry:
                            return left.[int]__add__(right), product(new[external] list[int](int(127)), new[external] list[int](int(1)))))
        ''').strip()
        nodes = [node for block in analysis.entry_point.ir.blocks for node in ast.walk(block)]
        callback = next(node for node in nodes if isinstance(node, Lambda))
        assert callback.lineno + analysis.entry_point.lineno - 1 == 5
        expected = NumericFormat("integer", 8, signed=True)
        assert [value.numeric for value in callback.obj.parameter_representations] == [expected] * 2
        assert callback.obj.return_representation.numeric == expected
        call = next(node for node in nodes if isinstance(node, ast.Call)
                    and getattr(getattr(node.func, "obj", None), "name", None) == "starmap")
        assert analyzed_representation(call).arguments[0].numeric == expected
    LLVM().assert_matches_python(source)


@pytest.mark.parametrize("optimize", [0, 2])
def test_pool_scalar_layouts_duplicate_positions_and_zero_width(optimize):
    LLVM().assert_matches_python('''
        from itertools import product, combinations, combinations_with_replacement, permutations

        def main() -> int:
            assert [list(row) for row in product([True, False], repeat=2)] == [
                [True, True], [True, False], [False, True], [False, False]]
            assert [list(row) for row in combinations("é😀é", 2)] == [["é", "😀"], ["é", "é"], ["😀", "é"]]
            assert [list(row) for row in combinations(iterable="é😀", r=1)] == [["é"], ["😀"]]
            assert [list(row) for row in permutations(b"ab", 2)] == [[97, 98], [98, 97]]
            assert [list(row) for row in combinations_with_replacement([1, 1], 2)] == [[1, 1], [1, 1], [1, 1]]
            assert [list(row) for row in permutations([1, 1], 2)] == [[1, 1], [1, 1]]
            empty: list[int] = []
            assert len(list(permutations(empty, 0))) == 1
            assert len(list(combinations((), 0))) == 1
            assert len(list(combinations_with_replacement((), 0))) == 1
            assert len(list(product([1], repeat=False))) == 1
            assert len(list(permutations([1], False))) == 1
            return 0
    ''', optimize=optimize)


@pytest.mark.parametrize("expression, message", [
    ("product([1], ['a'], repeat=257)", "matching pool item"),
    ("product([int8(1)], [int16(2)], repeat=257)", "matching pool item"),
    ("starmap(add, [(1,)])", "callback arity"),
    ("starmap(add, [(1, 'text')])", "matching callback argument"),
    ("starmap(add, [(int8(1), int8(2))])", "matching callback argument"),
    ("starmap(add, [[1, 2]])", "typed tuple rows"),
    ("permutations([1], 1.5)", "expects|overload"),
])
def test_pooled_diagnostics(expression, message):
    with pytest.raises((CompilationError, LLVMUnsupported), match=message):
        transpile_llvm(f'''
from itertools import product, starmap, permutations
from pyjs import int8, int16
def add(left: int, right: int) -> int:
    return left + right
def main() -> int:
    rows = {expression}
    return 0
''')


@pytest.mark.parametrize("callback", ["add", "lambda x, y=1: x + y"])
def test_starmap_default_arguments_have_an_explicit_static_boundary(callback):
    source = f'''
        from itertools import starmap
        def add(x: int, y: int = 1) -> int:
            return x + y
        def main() -> int:
            return next(starmap({callback}, [(5,)]))
    '''
    namespace = {}
    exec(dedent(source), namespace)
    assert namespace["main"]() == 6
    with pytest.raises(CompilationError, match="callback arity; defaults are not supplied"):
        transpile_llvm(source)


def test_starmap_default_arguments_have_an_explicit_dynamic_boundary():
    result = LLVM().compare_with_python('''
        from itertools import starmap, batched
        def add(x: int, y: int = 1) -> int:
            return x + y
        def main() -> str:
            rows = starmap(add, batched([5, 2, 8], 2))
            assert next(rows) == 7
            try:
                return str(next(rows))
            except TypeError as error:
                assert next(rows, -1) == -1
                return str(error)
    ''')
    assert result.python.returncode == result.native.returncode == 0
    assert result.python.stdout == "9"
    assert result.native.stdout == "starmap row does not match callback arity; defaults are not supplied"


@pytest.mark.parametrize("expression", [
    "product(source, repeat=2)", "combinations(source, 2)",
    "combinations_with_replacement(source, 2)", "permutations(source, 2)",
])
def test_pooled_lifetime_retains_members(expression):
    with analyze_source(f'''
from collections.abc import Iterator
from itertools import product, combinations, combinations_with_replacement, permutations
def main(source: list[str]) -> Iterator[tuple[str, ...]]:
    return {expression}
''', environment=NATIVE_ENVIRONMENT, entry_point="main") as analysis:
        lifetime = analysis.entry_point.ir.lifetime
        assert lifetime.returned_parameters == frozenset({"source"})
        assert lifetime.parameters["source"] is LifetimeBoundary.CALLER


@pytest.mark.parametrize("expression, expected", [
    ("product(words, repeat=2)", "9"),
    ("product([True], words, [3])", "3"),
    ("combinations(words, 2)", "3"),
    ("combinations_with_replacement(words, 2)", "6"),
    ("permutations(words, 2)", "6"),
    ("starmap(lambda a, b: a + b, product(words, repeat=2))", "9"),
])
@pytest.mark.parametrize("managed", [False, True], ids=["inferred", "gc-stress"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_pooled_allocation_failure_recovery(tmp_path, expression, expected, managed, optimize):
    source = f'''
from itertools import product, combinations, combinations_with_replacement, permutations, starmap
from pyjs.native import gc_collect, gc_set_threshold
from tests.native.allocation_support import arm

def main() -> int:
    {"gc_set_threshold(1)" if managed else "pass"}
    words = ["a", "é", "😀"]
    failures = 0
    for attempt in range(1, 250):
        complete = False
        try:
            arm(attempt)
            rows = {expression}
            assert len(list(rows)) == {expected}
            arm(0)
            complete = True
        except MemoryError:
            arm(0)
            failures += 1
        finally:
            arm(0)
        {"gc_collect()" if managed else "pass"}
        assert words == ["a", "é", "😀"]
        assert len(list({expression})) == {expected}
        if complete:
            return 0 if failures else 1
    return 2
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=managed, optimize=optimize)


def test_starmap_streams_settings_rows_into_the_dom():
    LLVM().assert_matches_python('''
        from itertools import starmap
        from pyjs.web.domx import div, span
        from pyjs.web.ssr import render_html
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            settings = [("work_mem", "4MB"), ("<private>", 'a&"b')]
            rows = starmap(lambda name, value: div({"class": "setting"}, span(name), span(value)), settings)
            gc_collect()
            return render_html(div({"id": "settings"}, *rows))
    ''')


@pytest.mark.parametrize("expression", [
    'combinations(iterable="é😀", r=1)',
    'permutations(iterable="é😀", r=1)',
    'combinations_with_replacement(iterable="é😀", r=1)',
    'product("é😀", repeat=1)',
])
def test_string_pool_consumption_reaches_its_runtime_helpers(expression):
    LLVM().assert_matches_python(f'''
        from itertools import product, combinations, combinations_with_replacement, permutations
        def main() -> str:
            return ''.join(''.join(row) for row in {expression})
    ''')


def test_starmap_roots_callback_while_evaluating_its_source(monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    LLVM().assert_matches_python('''
        from collections.abc import Callable
        from itertools import starmap
        from pyjs.native import gc_collect, gc_set_threshold

        class Reader:
            def __init__(self, label: str):
                self.label = label

            def read(self, value: str) -> str:
                gc_collect()
                return self.label + value

        def callback(events: list[str]) -> Callable[[str], str]:
            events.append("callback")
            return Reader("a" + "b").read

        def source(events: list[str]) -> list[tuple[str]]:
            gc_collect()
            events.append("source")
            return [("c",), ("d",)]

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            values = starmap(callback(events), source(events))
            assert events == ["callback", "source"]
            return ':'.join(values)
    ''', sanitizers=("address", "undefined"))


@pytest.mark.parametrize("adapter", ["product", "combinations", "combinations_with_replacement", "permutations"])
def test_pool_constructor_source_failure_precedes_size_validation(adapter):
    expression = f"{adapter}(source, repeat=1)" if adapter == "product" else f"{adapter}(source, -1)"
    LLVM().assert_matches_python(f'''
        from itertools import {adapter}
        from pyjs.native import gc_collect

        def checked(value: int) -> int:
            gc_collect()
            if value == 2:
                raise RuntimeError("source failure")
            return value

        def main() -> str:
            source = map(checked, range(5))
            result = ""
            try:
                rows = {expression}
            except RuntimeError as error:
                result = str(error)
            gc_collect()
            assert next(source) == 3
            return result
    ''')


@pytest.mark.parametrize("expression, arity, widths", [
    ("product([int8(1)], [int16(2)])", 2, (8, 16)),
    ("product([int8(1)], [int16(2)], repeat=2)", 4, (8, 16) * 2),
    ("product([int8(1)], [int16(2)], repeat=128)", 256, (8, 16) * 128),
    ("product([int8(1)], [int16(2)], repeat=0)", 0, None),
    ("combinations([int8(1)], 2)", None, (8,)),
    ("permutations([int8(1)], r=2)", None, (8,)),
    ("combinations_with_replacement([int8(1)], r=0)", None, (8,)),
    ("product(repeat=9223372036854775807)", None, None),
    ("product([int8(1)], repeat=256)", None, (8,)),
    ("product([int8(1)], repeat=257)", None, (8,)),
    ("combinations([int8(1)], width)", None, (8,)),
])
def test_pool_row_shape_and_portable_metadata(expression, arity, widths):
    with analyze_source(f'''
        from itertools import product, combinations, combinations_with_replacement, permutations
        from pyjs import int8, int16
        def main(width: int):
            return {expression}
    ''', environment=NATIVE_ENVIRONMENT, wrap=False) as analysis:
        iterator = analysis.entry_point.return_type
        row = iterator.generic_types["V"]
        assert row.tuple_variadic is (arity is None)
        assert len(row.generic_types) == (1 if arity is None else arity)
        representation = analysis.entry_point.return_representation
        if widths is None:
            assert representation is None
        else:
            assert tuple(value.numeric.bits for value in representation.arguments[0].arguments) == widths


@pytest.mark.parametrize("optimize", [0, 2])
def test_heterogeneous_product_preserves_layouts_snapshots_and_identity(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from itertools import product, starmap
        from pyjs import int8, int16
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, value: str): self.value = value
        def source(events: list[str], boxes: list[Box]):
            events.append("acquire")
            for box in boxes:
                gc_collect()
                yield box
        def describe(flag: bool, box: Box, number: int8, wide: int16) -> str:
            gc_collect()
            return repr((flag, box.value, int(number + 1), int(wide + 1)))
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            box = Box("old")
            boxes = [box]
            rows = product([True, False], source(events, boxes), [int8(127)], [int16(32767)])
            assert events == ["acquire"]
            alias = rows
            first = next(rows)
            assert first[1] is box
            boxes.clear()
            box.value = "updated"
            gc_collect()
            rest = list(starmap(describe, alias))
            assert first[1].value == "updated"
            assert list(rows) == []
            tagged: list[int | str] = [3, "tag"]
            mixed = list(product([True], tagged, ["tail"], repeat=2))
            return repr((describe(first[0], first[1], first[2], first[3]), rest, mixed))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_pooled_rows_support_checked_managed_destructuring(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from itertools import combinations, combinations_with_replacement, permutations, product
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, value: int): self.value = value
        def boxes() -> list[Box]: return [Box(2), Box(3), Box(5)]
        def main() -> str:
            gc_set_threshold(1)
            pairs = combinations(boxes(), 2)
            gc_collect()
            first = [(left.value, right.value) for left, right in pairs]
            repeated = [(left.value, right.value) for left, right in combinations_with_replacement(boxes(), 2)]
            ordered = [(left.value, right.value) for left, right in permutations(boxes(), 2)]
            expanded = [(left.value, number) for left, number in product(boxes(), [7, 9])]
            zero = list(product([True], ["ignored"], repeat=0))
            assert list(product(repeat=9223372036854775807)) == [()]
            empty = list(product([True], ()))
            assert list(product([1], [])) == []
            assert list(combinations([], 0)) == [()]
            for width in [0, 1, 2]:
                blank = ()
                assert len(list(product([1], blank, repeat=width))) == (1 if width == 0 else 0)
                assert len(list(product([1], [], repeat=width))) == (1 if width == 0 else 0)
                assert len(list(combinations([], width))) == (1 if width == 0 else 0)
            return repr((first, repeated, ordered, expanded, zero, empty))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_dynamic_heterogeneous_product_requires_a_fixed_row_shape():
    with pytest.raises(CompilationError, match="dynamic or large repeat requires matching"):
        transpile_llvm('''
            from itertools import product
            def rows(width: int):
                return product([1], ["a"], repeat=width)
            def main() -> int:
                return len(list(rows(2)))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True])
def test_mixed_product_row_allocation_failure_does_not_advance(tmp_path, optimize, managed):
    source = f'''
        from itertools import product
        from tests.native.allocation_support import arm
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> int:
            {"gc_set_threshold(1)" if managed else "pass"}
            failures = 0
            for attempt in range(1, 30):
                rows = product([True, False], ["first", "last"])
                complete = False
                try:
                    arm(attempt)
                    first = next(rows)
                    arm(0)
                    assert first == (True, "first")
                    complete = True
                except MemoryError:
                    arm(0)
                    failures += 1
                    assert next(rows) == (True, "first")
                finally:
                    arm(0)
                {"gc_collect()" if managed else "pass"}
                assert list(rows) == [(True, "last"), (False, "first"), (False, "last")]
                if complete:
                    return 0 if failures else 1
            return 2
    '''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_heterogeneous_tuple_inputs_keep_inferred_pool_item_domains(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from itertools import product, combinations, permutations, combinations_with_replacement
        from pyjs.native import gc_collect, gc_set_threshold
        def main() -> str:
            gc_set_threshold(1)
            source = (1, "text")
            rows = product(source, [False, True])
            gc_collect()
            assert list(product(source, [False], repeat=0)) == [()]
            return repr((list(rows), list(product(source, repeat=0)),
                         list(combinations(source, 2)), list(permutations(source, 2)),
                         list(combinations_with_replacement(source, 2))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_homogeneous_pool_widths_share_one_type_across_flow_and_storage(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from itertools import combinations, permutations, product
        from pyjs.native import gc_collect, gc_set_threshold
        def choose(values: list[int], wide: bool):
            if wide:
                return combinations(values, 3)
            return combinations(values, 2)
        def main() -> str:
            gc_set_threshold(1)
            rows = combinations([1, 2, 3], 2)
            result = list(rows)
            rows = combinations([4, 5, 6], 3)
            result += list(rows)
            rows = combinations([7, 8, 9], len("ab"))
            result += list(rows)
            rows = product([1], [2])
            result += list(rows)
            rows = product([1], [2], [3])
            result += list(rows)
            alternatives = [combinations("abc", 1), combinations("abc", 2)]
            selected = permutations([1, 2], 2) if len("ab") == 2 else permutations([1, 2], 1)
            gc_collect()
            return repr((result, [list(source) for source in alternatives], list(selected),
                         list(choose([1, 2, 3], True)), list(choose([1, 2, 3], False))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr
