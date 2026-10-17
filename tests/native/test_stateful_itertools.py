import ast
from textwrap import dedent

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.objects import UnionType
from pyjs.analysis.source import analyze_source
from pyjs.analysis.value_representation import analyzed_representation
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.numeric import NumericFormat
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("expression, members", [
    ("count(1, 0.5)", {"int", "float"}),
    ("count(step=0.5)", {"int", "float"}),
    ("count(True, 0.5)", {"bool", "float"}),
    ("count(1.0, 2)", {"float"}),
    ("count(True, True)", {"int"}),
])
def test_count_infers_the_first_and_subsequent_item_domains(expression, members):
    with analyze_source(f'''
        from itertools import count
        def main():
            return {expression}
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        member = next(iter(analysis.entry_point.return_type.generic_types.values()))
        assert {value.name for value in (member.types if isinstance(member, UnionType) else (member,))} == members
        assert analysis.entry_point.return_representation is None


def test_zip_longest_infers_each_optional_column_representation():
    with analyze_source('''
        from itertools import zip_longest
        from pyjs import int8, float32
        def main():
            return zip_longest([int8(127)], ["x", "y"], [float32(3)])
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        row = next(iter(analysis.entry_point.return_type.generic_types.values()))
        assert [tuple(member.name for member in column.types) for column in row.generic_types.values()] == [
            ("int", "NoneType"), ("str", "NoneType"), ("float", "NoneType")]
        columns = analysis.entry_point.return_representation.arguments[0].arguments
        assert columns[0].arguments[0].numeric == NumericFormat("integer", 8, signed=True)
        assert columns[0].arguments[1] is None and columns[1] is None
        assert columns[2].arguments[0].numeric == NumericFormat("float", 32)
        assert columns[2].arguments[1] is None


@pytest.mark.parametrize("optimize", [0, 2])
def test_mixed_count_keeps_narrowed_integer_runtime_kind(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from itertools import count, islice
        from pyjs.native import gc_collect, gc_set_threshold
        def samples(value: int | str) -> str:
            if isinstance(value, int):
                direct = count(value, 0.5)
                keyword = count(step=-0.25, start=value)
                gc_collect()
                return repr((list(islice(direct, 3)), list(islice(keyword, 3))))
            return value
        def main() -> str:
            gc_set_threshold(1)
            return repr([samples(True), samples(False), samples(9007199254740993),
                         samples(-9223372036854775808), samples("not numeric")])
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression", ["count(value)", "count(value, 2)", "count(1.5, value)"])
def test_count_rejects_other_tagged_integer_operands_before_emitting_ir(expression):
    with pytest.raises(LLVMUnsupported, match="narrowed int may be bool"):
        transpile_llvm(f'''
            from itertools import count, islice
            def samples(value: int | str) -> str:
                if isinstance(value, int):
                    return repr(list(islice({expression}, 3)))
                return value
            def main() -> str:
                return samples(True)
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_mixed_count_preserves_initial_bits_aliases_and_composition(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import count, islice, tee, cycle
        from pyjs.native import gc_collect, gc_set_threshold

        def numbers(start: int, step: float) -> Iterator[int | float]:
            return count(start, step)
        def start(events: list[str]) -> int:
            events.append("start")
            gc_collect()
            return 9007199254740993
        def step(events: list[str]) -> float:
            events.append("step")
            gc_collect()
            return 0.5
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            values = count(step=step(events), start=start(events))
            alias = values
            gc_collect()
            first = next(alias)
            assert repr(first) == "9007199254740993"
            assert events == ["step", "start"]
            out = [repr((first, list(islice(values, 3))))]
            for initial in [0, -1, 9223372036854775807, -9223372036854775808]:
                for increment in [0.0, -0.0, 0.25, -0.5, float('inf'), float('nan')]:
                    out.append(repr(list(islice(numbers(initial, increment), 3))))
            out.append(repr(list(islice(count(False, -0.0), 3))))
            out.append(repr(list(islice(count(True, 1.0), 3))))
            left, right = tee(numbers(2, 0.25))
            assert next(left) == 2
            gc_collect()
            out.append(repr((list(islice(left, 3)), list(islice(right, 4)))))
            out.append(repr(list(islice(cycle(islice(numbers(3, -0.5), 3)), 7))))
            return repr(out)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("expression, expected", [
    ("list(islice(count(), 4))", "[0, 1, 2, 3]"),
    ("list(islice(count(step=-3, start=5), 4))", "[5, 2, -1, -4]"),
    ("list(islice(count(0.5), 3))", "[0.5, 1.5, 2.5]"),
    ("list(islice(count(2.0, -0.25), 3))", "[2.0, 1.75, 1.5]"),
    ("list(islice(count(True, True), 3))", "[1, 2, 3]"),
    ("list(islice(count(1.5, True), 3))", "[1.5, 2.5, 3.5]"),
    ("list(islice(count(1, 0.5), 3))", "[1, 1.5, 2.0]"),
    ("list(islice(count(True, 0.5), 3))", "[True, 1.5, 2.0]"),
    ("list(islice(count(step=0.5), 3))", "[0, 0.5, 1.0]"),
    ("list(islice(cycle([1, 2, 3]), 8))", "[1, 2, 3, 1, 2, 3, 1, 2]"),
    ("list(islice(cycle('é😀'), 5))", "['é', '😀', 'é', '😀', 'é']"),
    ("list(cycle(range(0)))", "[]"),
    ("list(zip_longest(range(3), [5], fillvalue=-1))", "[(0, 5), (1, -1), (2, -1)]"),
    ("list(zip_longest([True], [False, True], fillvalue=False))", "[(True, False), (False, True)]"),
    ("list(zip_longest())", "[]"),
    ("list(zip_longest(fillvalue=None))", "[]"),
    ("list(zip_longest((), [2, 3], fillvalue=-1))", "[(-1, 2), (-1, 3)]"),
    ("repr(list(zip_longest([1, 2, 3], 'ab')))", repr("[(1, 'a'), (2, 'b'), (3, None)]")),
    ("repr(list(zip_longest([1], (2.5, 3.5), fillvalue=False)))", repr("[(1, 2.5), (False, 3.5)]")),
    ("list(zip_longest([True], [1, 2], fillvalue=True))", "[(True, 1), (True, 2)]"),
    ("list(zip_longest([], [2, 3]))", "[(None, 2), (None, 3)]"),
    ("list(zip_longest((), [2, 3], fillvalue='x'))", "[('x', 2), ('x', 3)]"),
    ("list(accumulate([1, 2, 3]))", "[1, 3, 6]"),
    ("list(accumulate(initial=10, iterable=[1, 2, 3]))", "[10, 11, 13, 16]"),
    ("list(accumulate([1, 2, 3], lambda a, b: a * b))", "[1, 2, 6]"),
    ("list(accumulate([1.5, 0.25]))", "[1.5, 1.75]"),
    ("list(accumulate(['é', '😀']))", "['é', 'é😀']"),
    ("list(accumulate([b'a', b'b']))", "[b'a', b'ab']"),
    ("list(accumulate(range(0), initial=3))", "[3]"),
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_stateful_stream_values(expression, expected, optimize):
    LLVM().assert_matches_python(f'''
        from itertools import count, cycle, accumulate, zip_longest, islice

        def main() -> int:
            assert {expression} == {expected}
            return 0
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_stream_consumption_errors_and_resumption(optimize):
    LLVM().assert_matches_python('''
        from itertools import cycle, accumulate, zip_longest

        def checked(events: list[int], value: int) -> int:
            events.append(value)
            if value == 2:
                raise ValueError("two")
            if value == 4:
                raise StopIteration("four")
            return value

        def combine(events: list[int], left: int, right: int) -> int:
            checked(events, right)
            return left + right

        def main() -> str:
            events: list[int] = []
            result = ""
            source = map(lambda n: checked(events, n), range(1, 7))
            repeated = cycle(source)
            assert events == []
            for attempt in range(8):
                try:
                    result += str(next(repeated, -1)) + ","
                except ValueError:
                    result += "error,"
            assert events == [1, 2, 3, 4]
            assert next(source) == 5
            totals = accumulate(range(1, 7), lambda a, b: combine(events, a, b), initial=10)
            for attempt in range(8):
                try:
                    result += str(next(totals, -1)) + ","
                except ValueError:
                    result += "error,"
            totals = accumulate(map(lambda n: checked(events, n), range(1, 7)))
            for attempt in range(8):
                try:
                    result += str(next(totals, -1)) + ","
                except ValueError:
                    result += "error,"
            left = iter(range(8))
            right = map(lambda n: checked(events, n), range(1, 7))
            rows = zip_longest(left, right, fillvalue=-1)
            assert next(rows) == (0, 1)
            try:
                next(rows)
            except ValueError:
                pass
            assert list(rows) == [] and next(left) == 2 and next(right) == 3
            rows = zip_longest(range(3), map(lambda n: checked(events, n), [4, 5]), fillvalue=-1)
            assert list(rows) == [(0, -1), (1, -1), (2, -1)]
            shared = iter(range(5))
            assert list(zip_longest(shared, shared, fillvalue=-1)) == [(0, 1), (2, 3), (4, -1)]
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_stream_portable_representations_and_callbacks(optimize):
    LLVM().assert_matches_python('''
        from itertools import cycle, accumulate, zip_longest, islice, count
        from pyjs import int8, int64, float32

        def main() -> int:
            assert list(islice(cycle([int8(127), int8(-128)]), 3)) == [int8(127), int8(-128), int8(127)]
            assert list(accumulate([int8(127), int8(1), int8(1)])) == [int8(127), int8(-128), int8(-127)]
            assert list(accumulate([int8(120), int8(10)], lambda a, b: a + b, initial=int8(2))) == [int8(2), int8(122), int8(-124)]
            assert list(accumulate([float32(16777216), float32(1), float32(1)])) == [float32(16777216)] * 3
            assert list(zip_longest([int64(2**53+1)], [int64(7), int64(8)], fillvalue=int64(-1))) == [
                (int64(2**53+1), int64(7)), (int64(-1), int64(8))]
            assert list(islice(count(int8(127), 1), 3)) == [127, 128, 129]
            assert list(islice(count(0.5, int8(1)), 3)) == [0.5, 1.5, 2.5]
            return 0
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_count_stable_numeric_domains(optimize):
    LLVM().assert_matches_python('''
        from itertools import count, islice
        from pyjs import int8

        def integral(start: int, step: int) -> str:
            return ','.join(str(value) for value in islice(count(start, step), 3))

        def boolean_step(step: bool) -> str:
            return ','.join(str(value) for value in islice(count(5, step), 3))

        def floating(step: int8) -> str:
            return ','.join(str(value) for value in islice(count(0.5, step), 3))

        def unit(start: int8) -> str:
            return ','.join(str(value) for value in islice(count(start), 3))

        def main() -> str:
            result = unit(int8(127)) + ';'
            result += ','.join(str(value) for value in islice(count(start=int8(127), step=1), 3)) + ';'
            result += ','.join(str(value) for value in islice(count(int8(127), True), 3)) + ';'
            result += ','.join(str(value) for value in islice(count(True), 3)) + ';'
            result += ','.join(str(value) for value in islice(count(False, 1), 3)) + ';'
            for step in [0, 1, 2, -1]:
                result += integral(127, step) + ';'
                result += floating(int8(step)) + ';'
            result += boolean_step(False) + ';' + boolean_step(True) + ';'
            result += integral(int(int8(127)), int(int8(2)))
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("expression", [
    "count(int8(120), int8(10))", "count(int8(127), 2)",
    "count(True, 0)", "count(False, -1)", "count(int8(127), 0)",
    "count(int8(127), -1)", "count(127, int8(2))",
    "count(int8(127), int8(1))", "count(127, int8(1))",
    "count(start=int8(127), step=step)", "count(True, step)",
    "count(127, portable_step)", "count(int8(127), boolean_step)",
])
def test_count_changing_numeric_domains_are_diagnosed(expression):
    with pytest.raises(CompilationError, match="native count with bool or portable integer operands"):
        transpile_llvm(f'''
from itertools import count
from pyjs import int8
def values(step: int, portable_step: int8, boolean_step: bool) -> int:
    source = {expression}
    return next(source)
def main() -> int:
    return values(1, int8(1), True)
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_streams_retain_objects_and_cached_aliases(optimize, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import accumulate, cycle, zip_longest
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, text: str):
                self.text = text

            def combine(self, other: Box) -> Box:
                gc_collect()
                return Box(self.text + other.text)

        def collect(value: Box) -> Box:
            gc_collect()
            return value

        def make() -> Iterator[Box]:
            return cycle(map(collect, [Box("a" + str(1)), Box("b" + str(2))]))

        def main() -> str:
            gc_set_threshold(1)
            values = make()
            first = next(values)
            second = next(values)
            gc_collect()
            assert next(values) is first
            first.text += "!"
            assert next(values) is second and next(values).text == "a1!"
            totals = accumulate([first, second], lambda a, b: a.combine(b), initial=Box("start"))
            before = next(totals)
            middle = next(totals)
            gc_collect()
            end = next(totals)
            fill = Box("missing")
            rows = zip_longest(map(collect, [first]), map(collect, [second, first]), fillvalue=fill)
            assert next(rows)[0] is first
            row = next(rows)
            gc_collect()
            assert row[0] is fill and row[1] is first
            return before.text + middle.text + end.text
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_zip_longest_mixed_columns_keep_fill_identity_and_partial_rows(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from itertools import zip_longest
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, text: str):
                self.text = text

        def collect(value: str) -> str:
            gc_collect()
            return value

        def checked(value: int) -> str:
            gc_collect()
            if value == 1:
                raise ValueError("stop")
            return str(value)

        def main() -> str:
            gc_set_threshold(1)
            fill = Box("fill")
            words = ["a", "b"]
            stream = zip_longest([9007199254740993], map(collect, words), fillvalue=fill)
            first = next(stream)
            words.append("c")
            gc_collect()
            second = next(stream)
            third = next(stream)
            assert first[0] == 9007199254740993 and first[1] == "a"
            assert second[0] is fill and third[0] is fill
            assert second[1] == "b" and third[1] == "c"
            fill.text = "changed"
            retained = second[0]
            assert isinstance(retained, Box) and retained.text == "changed"
            assert list(stream) == []
            left = iter([1, 2, 3])
            right = map(checked, range(3))
            failing = zip_longest(left, right)
            assert next(failing) == (1, "0")
            try:
                next(failing)
            except ValueError:
                pass
            else:
                raise AssertionError("missing source error")
            assert list(failing) == [] and next(left) == 3 and next(right) == "2"
            shared = iter([True, False, True])
            return repr(list(zip_longest(shared, shared)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_zip_longest_shares_boxed_fill_and_roots_acquired_cursors(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import zip_longest
        from pyjs.native import gc_collect, gc_set_threshold

        class Words:
            def __init__(self, events: list[int]):
                self.events = events
            def __iter__(self) -> Iterator[str]:
                self.events.append(3)
                gc_collect()
                return iter(["a", "b"])

        def integers(events: list[int]) -> list[int]:
            events.append(1)
            return [7]

        def filler(events: list[int]) -> str:
            events.append(2)
            return "fill"

        def main() -> str:
            gc_set_threshold(1)
            empty: list[object] = []
            other: list[object | float] = []
            rows = zip_longest(empty, other, [1, 2], fillvalue=9007199254740993)
            first = next(rows)
            gc_collect()
            second = next(rows)
            assert first[0] is first[1] and second[0] is first[0] and second[1] is first[0]
            events: list[int] = []
            stream = zip_longest(integers(events), Words(events), fillvalue=filler(events))
            assert events == [1, 2, 3]
            return repr((first, second, list(stream)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_zip_longest_optional_columns_preserve_portable_representations(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from itertools import zip_longest
        from pyjs import int8, int64, float32
        def main() -> str:
            output: list[str] = []
            for small, large, real in zip_longest([int8(127)], [int64(9007199254740993), int64(4)], [float32(16777216)]):
                output.append("none" if small is None else repr(small + int8(1)))
                output.append("none" if large is None else repr(large))
                output.append("none" if real is None else repr(real + float32(1)))
            return ",".join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("adapter", ["cycle", "accumulate", "zip_longest", "zip_longest_none"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_recursive_source_advancement(adapter, optimize, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    if adapter == "zip_longest_none":
        row = "tuple[int | None, str | None]"
        expression = "zip_longest(source, [str(n) for n in range(8)])"
    else:
        row = "tuple[int, int]" if adapter == "zip_longest" else "int"
        expression = "zip_longest(source, range(8), fillvalue=-1)" if adapter == "zip_longest" else f"{adapter}(source)"
    value = "repr(value)"
    LLVM().assert_matches_python(f'''
        from collections.abc import Iterator
        from itertools import cycle, accumulate, zip_longest
        from pyjs.native import gc_collect, gc_set_threshold

        def fetch(cursors: list[Iterator[{row}]], events: list[str], trigger: int, pulls: int, item: int) -> int:
            if item <= trigger:
                for attempt in range(pulls):
                    try:
                        value = next(cursors[0])
                        events.append({value})
                    except StopIteration:
                        events.append("stop")
                gc_collect()
            return item

        def scenario(length: int, trigger: int, pulls: int) -> str:
            cursors: list[Iterator[{row}]] = []
            events: list[str] = []
            source = map(lambda n: fetch(cursors, events, trigger, pulls, n), range(1, length + 1))
            stream = {expression}
            cursors.append(stream)
            for attempt in range(8):
                try:
                    value = next(stream)
                    events.append({value})
                except StopIteration:
                    events.append("stop")
            return ",".join(events)

        def main() -> str:
            gc_set_threshold(1)
            result = ""
            for length in range(6):
                for trigger in [0, 1, 3]:
                    for pulls in [1, 2, 4]:
                        result += scenario(length, trigger, pulls) + ";"
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("expression, message", [
    ("count(int8(1), 0.5)", "native count requires"),
    ("count(int8(1), 1.0)", "native count requires"),
    ("count(1 if len('a') == 1 else 0.5, 0.5)", "native count requires"),
    ("count(float32(1))", "native count requires|representation"),
    ("zip_longest([int8(1)], fillvalue=int16(0))", "representation"),
    ("zip_longest([[1]], fillvalue=['text'])", "cannot distinguish different layouts"),
    ("accumulate([True, False])", "matching two-argument callback and result representation"),
    ("accumulate([int8(1)], initial=int16(0))", "representation|expects"),
    ("accumulate([1], lambda a, b: 'wrong')", "expects|return|incompatible|must accept"),
    ("accumulate([1], initial=0.5)", "initial must match"),
])
def test_stream_diagnostics(expression, message):
    with pytest.raises((CompilationError, LLVMUnsupported), match=message):
        transpile_llvm(f'''
from itertools import count, cycle, accumulate, zip_longest
from pyjs import int8, int16, float32
def main() -> int:
    values = {expression}
    return 0
''')


@pytest.mark.parametrize("expression, expected", [
    ("list(islice(count(1, 0.5), 3))", "[1, 1.5, 2.0]"),
    ("list(islice(cycle(map(collect, words)), 5))", '["a", "é", "😀", "a", "é"]'),
    ("list(accumulate(map(collect, words), initial='!'))", '["!", "!a", "!aé", "!aé😀"]'),
    ("list(zip_longest(map(collect, words), words[:1], fillvalue='?'))", '[("a", "a"), ("é", "?"), ("😀", "?")]'),
    ("repr(list(zip_longest(map(collect, words), range(1))))", repr("[('a', 0), ('é', None), ('😀', None)]")),
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_stream_allocation_sweep(tmp_path, expression, expected, optimize):
    source = transpile_llvm(f'''
from itertools import count, cycle, islice, accumulate, zip_longest
from pyjs.native import gc_collect, gc_set_threshold
from tests.native.allocation_support import arm
def collect(value: str) -> str:
    gc_collect()
    return value
def main() -> int:
    gc_set_threshold(1)
    words = ["a", "é", "😀"]
    failures = 0
    for attempt in range(1, 160):
        complete = False
        try:
            arm(attempt)
            assert {expression} == {expected}
            arm(0)
            complete = True
        except MemoryError:
            arm(0)
            failures += 1
        finally:
            arm(0)
        gc_collect()
        assert {expression} == {expected}
        if complete:
            return 0 if failures else 1
    return 2
''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


def test_stateful_streams_build_a_metrics_table():
    LLVM().assert_matches_python('''
        from itertools import count, cycle, accumulate, zip_longest
        from pyjs.web.domx import div, span
        from pyjs.web.ssr import render_html

        def main() -> str:
            sizes = accumulate([12, 3, 7, 2])
            labels = ["primary", "replica"]
            colors = cycle(["blue", "green"])
            numbers = count(1)
            rows = zip_longest(labels, [str(n) for n in sizes], fillvalue="pending")
            page = div(*(div(span(str(next(numbers))), span(label), span(size),
                             {"data-color": next(colors)}) for label, size in rows))
            return render_html(page)
    ''')


def test_stateful_stream_ir_preserves_nested_item_representations():
    source = '''
from itertools import accumulate, cycle, zip_longest
from pyjs import int8
def main() -> int8:
    values = accumulate([int8(127), int8(1)])
    pairs = zip_longest(cycle(values), [int8(3)], fillvalue=int8(0))
    return next(pairs)[0]
'''
    with analyze_source(source, environment=NATIVE_ENVIRONMENT, wrap=False) as analysis:
        assert analysis.types.strip() == dedent('''
            def accumulate(iterable: Iterable__T, func: Callable[[T, T], T] | None=None, *, initial: T | None=None) -> Iterator[T]:
                external

            def cycle(iterable: Iterable__T, /) -> Iterator[T]:
                external

            def zip_longest(*iterables: tuple__Iterable__object__variadic, fillvalue: object=None) -> Iterator[tuple[object, ...]]:
                external

            def main() -> int:
                block entry:
                    values: Iterator[int] = accumulate(new[external] list[int](int(127), int(1)))
                    pairs: Iterator[tuple[int, int]] = zip_longest(cycle(values), new[local] list[int](int(3)), fillvalue=int(0))
                    return next(pairs).[tuple__int_int]__getitem__(0)
        ''').strip()
        calls = {node.func.obj.name: node for block in analysis.entry_point.ir.blocks
                 for node in ast.walk(block) if isinstance(node, ast.Call)
                 and getattr(getattr(node.func, "obj", None), "name", None) in {"accumulate", "cycle", "zip_longest"}}
        expected = NumericFormat("integer", 8, signed=True)
        for name in ("accumulate", "cycle"):
            assert analyzed_representation(calls[name]).arguments[0].numeric == expected
        assert [value.numeric for value in analyzed_representation(calls["zip_longest"]).arguments[0].arguments] == [expected] * 2
    LLVM().assert_matches_python(source)


@pytest.mark.parametrize("optimize", [0, 2])
def test_accumulate_callback_reentry_preserves_live_totals(optimize, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import accumulate
        from pyjs.native import gc_collect, gc_set_threshold

        def combine(cursors: list[Iterator[str]], events: list[str], fail: bool, left: str, right: str) -> str:
            if right == "b":
                events.append(next(cursors[0]))
                gc_collect()
                if fail:
                    raise ValueError("after nested total")
            return left + right

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            for fail in [False, True]:
                cursors: list[Iterator[str]] = []
                source = ["a", "b", "c", "d"]
                totals = accumulate(func=lambda a, b: combine(cursors, events, fail, a, b),
                                    iterable=source, initial="!")
                cursors.append(totals)
                for attempt in range(6):
                    try:
                        events.append(next(totals, "stop"))
                    except ValueError:
                        events.append("error")
                    gc_collect()
                source.clear()
            return ",".join(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_cycle_caches_only_consumed_values_and_constructor_argument_order(optimize):
    LLVM().assert_matches_python('''
        from itertools import cycle, accumulate, count, zip_longest, islice

        def record(events: list[int], value: int) -> int:
            events.append(value)
            return value

        def main() -> str:
            values = [1, 2]
            repeated = cycle(values)
            assert next(repeated) == 1
            values.append(3)
            assert next(repeated) == 2 and next(repeated) == 3
            assert next(repeated) == 1
            values.clear()
            assert list(islice(repeated, 4)) == [2, 3, 1, 2]
            events: list[int] = []
            numbers = count(step=record(events, 2), start=record(events, 5))
            assert events == [2, 5] and next(numbers) == 5
            totals = accumulate(initial=record(events, 10), iterable=[record(events, 3)])
            assert events == [2, 5, 10, 3] and list(totals) == [10, 13]
            rows = zip_longest([record(events, 7)], [record(events, 8)], fillvalue=record(events, 9))
            assert list(rows) == [(7, 8)]
            return ",".join(str(value) for value in events)
    ''', optimize=optimize)
