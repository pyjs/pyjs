import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.lifetime import LifetimeBoundary
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("expression, expected", [
    ("list(islice(range(9), 1, 8, 2))", "[1, 3, 5, 7]"),
    ("list(islice(range(4), None))", "[0, 1, 2, 3]"),
    ("list(islice(range(4), None, None, None))", "[0, 1, 2, 3]"),
    ("list(repeat(4, 3))", "[4, 4, 4]"),
    ("list(repeat(times=2, object='é'))", "['é', 'é']"),
    ("list(islice(repeat(7), 3))", "[7, 7, 7]"),
    ("list(pairwise([1, 2, 3]))", "[(1, 2), (2, 3)]"),
    ("[list(row) for row in batched([1, 2, 3], 2)]", "[[1, 2], [3]]"),
    ("[list(row) for row in batched(n=2, iterable=[True, False, True])]", "[[True, False], [True]]"),
    ("list(filterfalse(None, [0, 1, 0]))", "[0, 0]"),
    ("list(filterfalse(lambda n: n > 1, [1, 2, 3]))", "[1]"),
    ("list(takewhile(lambda n: n < 3, [1, 2, 3, 1]))", "[1, 2]"),
    ("list(dropwhile(lambda n: n < 3, [1, 2, 3, 1]))", "[3, 1]"),
    ("list(compress([1, 2, 3], [1, 0, 1]))", "[1, 3]"),
    ("list(compress(selectors=['', 'yes'], data=['a', 'b', 'c']))", "['b']"),
    ("list(chain([1, 2], range(3, 5), (5, 6)))", "[1, 2, 3, 4, 5, 6]"),
    ("list(chain.from_iterable([[1, 2], [3]]))", "[1, 2, 3]"),
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_lazy_stream_adapters(expression, expected, optimize):
    LLVM().assert_matches_python(f'''
        from itertools import islice, repeat, pairwise, batched, filterfalse, takewhile, dropwhile, compress, chain

        def main() -> int:
            assert {expression} == {expected}
            return 0
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_slice_consumption_and_constructor_validation(optimize):
    LLVM().assert_matches_python('''
        from itertools import islice, repeat, batched

        def record(events: list[int], value: int) -> int:
            events.append(value)
            return value

        def main() -> str:
            for start in range(7):
                for stop in range(7):
                    for step in [1, 2, 5, 9223372036854775807]:
                        source = iter(range(9))
                        sliced = islice(source, start, stop, step)
                        assert list(sliced) == list(range(9))[start:stop:step]
                        assert next(source) == max(start, stop)
                        assert list(sliced) == []
            events: list[int] = []
            values = islice(map(lambda n: record(events, n), range(8)), 1, 6, 3)
            assert events == []
            assert next(values) == 1 and events == [0, 1]
            assert next(values) == 4 and events == [0, 1, 2, 3, 4]
            assert list(values) == [] and events == [0, 1, 2, 3, 4, 5]
            errors = ""
            for value in [-1, -2]:
                try:
                    islice(range(4), value)
                except ValueError as error:
                    errors += str(error)
                try:
                    islice(range(4), value, 4)
                except ValueError as error:
                    errors += str(error)
                try:
                    islice(range(4), 0, None, value)
                except ValueError as error:
                    errors += str(error)
            for start in [-3, -1, 0]:
                for stop in [-2, -1, 0]:
                    for step in [-1, 0, 2]:
                        try:
                            islice(range(4), start, stop, step)
                        except ValueError as error:
                            errors += str(error)
            try:
                batched(range(5), 0)
            except ValueError as error:
                errors += str(error)
            assert list(repeat(5, -1)) == []
            assert list(repeat(5, 0)) == []
            return errors
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True])
def test_oversized_batch_allocation_is_deferred_and_retryable(optimize, managed):
    result = LLVM().assert_matches_python(f'''
        from itertools import batched
        from pyjs.native import gc_collect
        def main() -> int:
            failures = 0
            for size in [9223372036854775807, 1152921504606846976]:
                for values in [[], [1, 2]]:
                    source = iter(values)
                    cursor = batched(source, size)
                    for retry in range(2):
                        try:
                            next(cursor)
                        except MemoryError:
                            failures += 1
                        {"gc_collect()" if managed else "pass"}
                    assert list(source) == values
            return failures
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.python.returncode == 8
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_batch_strict_exhaustion_and_source_errors(optimize):
    LLVM().assert_matches_python('''
        from itertools import pairwise, batched, islice

        def checked(value: int) -> int:
            if value == 2:
                raise ValueError("two")
            return value

        def main() -> str:
            source = iter(range(5))
            batches = batched(source, 2, strict=True)
            assert list(next(batches)) == [0, 1]
            assert list(next(batches)) == [2, 3]
            message = ""
            try:
                next(batches)
            except ValueError as error:
                message = str(error)
            assert list(batches) == [] and next(source, -1) == -1
            for size in [1, 2, 8]:
                assert [list(row) for row in batched(range(0), size)] == []
            pairs = pairwise([1])
            assert list(pairs) == [] and list(pairs) == []
            source = map(checked, range(1, 5))
            pairs = pairwise(source)
            try:
                next(pairs)
            except ValueError:
                pass
            assert list(pairs) == [] and next(source) == 3
            source = map(checked, range(1, 5))
            batches = batched(source, 3)
            try:
                next(batches)
            except ValueError:
                pass
            assert list(batches) == [] and next(source) == 3
            source = map(checked, range(1, 5))
            values = islice(source, 1, None, 2)
            try:
                next(values)
            except ValueError:
                pass
            assert list(values) == [] and next(source) == 3
            return message
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_partial_batch_retains_a_resumable_callback_source(optimize):
    result = LLVM().assert_matches_python('''
        from itertools import batched
        from pyjs.native import gc_collect, gc_set_threshold
        def checked(value: int) -> int:
            if value == 2:
                raise StopIteration()
            gc_collect()
            return value
        def main() -> str:
            gc_set_threshold(1)
            cursor = batched(map(checked, range(1, 5)), 2)
            first = next(cursor)
            gc_collect()
            second = next(cursor)
            return str((first, second, list(cursor)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("adapter", ["filterfalse", "takewhile", "dropwhile"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_predicate_resume_and_consumption(adapter, optimize):
    LLVM().assert_matches_python(f'''
        from itertools import {adapter}

        def checked(events: list[int], value: int) -> bool:
            events.append(value)
            if value == 2:
                raise ValueError("two")
            if value == 4:
                raise StopIteration("four")
            return value < 5

        def main() -> str:
            events: list[int] = []
            source = iter(range(1, 8))
            values = {adapter}(lambda n: checked(events, n), source)
            result = ""
            assert events == []
            for attempt in range(8):
                try:
                    result += str(next(values, -1)) + ","
                except ValueError:
                    result += "error,"
            result += ":" + str(next(source, -1))
            for value in events:
                result += ":" + str(value)
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_compress_consumes_data_first_and_resumes(optimize):
    LLVM().assert_matches_python('''
        from itertools import compress

        def record(events: list[str], label: str, value: int) -> int:
            events.append(label + str(value))
            if label == "s" and value == 2:
                raise ValueError("selector")
            return value

        def main() -> str:
            events: list[str] = []
            data = map(lambda n: record(events, "d", n), range(6))
            selectors = map(lambda n: record(events, "s", n), range(4))
            values = compress(selectors=selectors, data=data)
            assert events == []
            assert next(values) == 1
            try:
                next(values)
            except ValueError:
                pass
            assert next(values) == 3
            assert next(values, -1) == -1
            assert next(values, -1) == -1
            return ",".join(events)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_portable_representations_survive_adapters(optimize):
    LLVM().assert_matches_python('''
        from itertools import repeat, islice, pairwise, batched, compress, filterfalse, takewhile, dropwhile, chain
        from pyjs import int8, float32

        def main() -> int:
            values = [int8(127), int8(126), int8(125)]
            total = 0
            for n in repeat(int8(127), 2):
                total += int(n + int8(1))
            for n in chain(values, values):
                total += int(n + int8(1))
            for n in chain.from_iterable([values, values]):
                total += int(n + int8(1))
            for left, right in pairwise(values):
                total += int(left + right)
            for batch in batched(values, 2):
                for n in batch:
                    total += int(n + int8(1))
            for n in islice(values, None):
                total += int(n + int8(1))
            for n in compress(values, [True, False, True]):
                total += int(n + int8(1))
            for n in filterfalse(lambda n: n == int8(126), values):
                total += int(n + int8(1))
            for n in takewhile(lambda n: n != int8(125), values):
                total += int(n + int8(1))
            for n in dropwhile(lambda n: n == int8(127), values):
                total += int(n + int8(1))
            for pair in pairwise([float32(16777216.0), float32(1.0)]):
                assert pair[0] + pair[1] == float32(16777216.0)
            return total
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_gc_retention_partial_rows_and_truth_callbacks(optimize, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import repeat, islice, pairwise, batched, filterfalse, compress
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, text: str):
                self.text = text

            def __bool__(self) -> bool:
                gc_collect()
                return bool(self.text)

        def make() -> Iterator[Box]:
            return repeat(Box("owned"), 3)

        def generated(value: int) -> Box:
            gc_collect()
            return Box(str(value))

        def main() -> str:
            gc_set_threshold(1)
            values = make()
            gc_collect()
            first = next(values)
            assert next(values) is first
            assert next(islice(values, None)) is first
            pairs = list(pairwise(map(generated, range(5))))
            batches = list(batched(map(generated, range(5)), 2))
            gc_collect()
            result = first.text
            for left, right in pairs:
                result += left.text + right.text
            for batch in batches:
                for box in batch:
                    result += box.text
            assert len(list(filterfalse(None, [Box(""), Box("a")]))) == 1
            selected = compress(selectors=[Box("a"), Box(""), Box("c")], data=map(generated, range(3)))
            for box in selected:
                result += box.text
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_chain_defers_inner_iterators_and_preserves_error_recovery(optimize):
    LLVM().assert_matches_python('''
        from itertools import chain
        from pyjs.native import gc_collect, gc_set_threshold

        def checked(value: int) -> int:
            gc_collect()
            if value == 2:
                raise ValueError("two")
            return value

        def main() -> str:
            gc_set_threshold(1)
            later = {3: "three"}
            values = chain([1], later, (5, 6))
            later[4] = "four"
            assert next(values) == 1
            assert list(values) == [3, 4, 5, 6]
            assert list(values) == []
            empty: list[int] = []
            assert list(chain(empty, (), range(0), [7])) == [7]
            assert len(list(chain(()))) == 0
            source = map(checked, range(4))
            values = chain(source, [8])
            assert next(values) == 0 and next(values) == 1
            try:
                next(values)
            except ValueError:
                pass
            gc_collect()
            assert list(values) == [3, 8]
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_chain_converts_each_source_without_reinterpreting_storage(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from itertools import chain, cycle, islice, tee
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int):
                self.value = value

            def __repr__(self) -> str:
                gc_collect()
                return "Box(" + str(self.value) + ")"

        def main() -> str:
            gc_set_threshold(1)
            numeric = chain([9007199254740993], [1.5], [True, False])
            alias = numeric
            first = next(alias)
            gc_collect()
            result = repr((first, list(numeric)))
            wide: list[int | float] = [2, 2.5]
            left, right = tee(chain((), wide, ["text"], [None]))
            result += repr(list(left)) + repr(list(right))
            result += repr(list(islice(cycle(chain([1], ["x"])), 5)))
            integers = [1]
            words = ["before"]
            mutable = chain(integers, words)
            result += repr(next(mutable))
            integers.append(2)
            words[0] = "after"
            gc_collect()
            result += repr((list(mutable), integers, words))
            later = {"a": 1}
            delayed = chain([7], later)
            result += repr(next(delayed))
            later["b"] = 2
            result += repr(list(delayed))
            result += repr(list(chain([int8(127)], [int8(-128)])))
            objects = list(chain([Box(3)], [1]))
            gc_collect()
            result += repr(objects)
            return result
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("inputs", [
    "[1, 2], (True,)",
    "[1.5], (True,)",
    "[1], (2.5,)",
    "range(2), (2.5,)",
])
def test_chain_prepares_narrower_tuple_source_iterators(tmp_path, inputs, optimize):
    result = LLVM().assert_matches_python(f'''
        from itertools import chain
        def main() -> str:
            output: list[str] = []
            for value in chain({inputs}):
                output.append(repr(value))
            return ",".join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_chain_preserves_nullable_exception_type_identity(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from itertools import chain
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            output: list[str] = []
            for value in chain([ValueError], [KeyError], [None]):
                gc_collect()
                output.append("N" if value is None else ("V" if value is ValueError else "K"))
            cursor = chain([ValueError], [None], [KeyError])
            first = next(cursor)
            gc_collect()
            second = next(cursor)
            third = next(cursor)
            assert first is ValueError and second is None and third is KeyError
            return ",".join(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_chain_mixed_application_acquisition_stays_lazy_and_reentrant(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import chain
        from pyjs.native import gc_collect, gc_set_threshold

        class Words:
            def __init__(self, parents: list[Iterator[int | str]], events: list[str]):
                self.parents = parents
                self.events = events

            def __iter__(self) -> Iterator[str]:
                self.events.append("acquired")
                gc_collect()
                self.events.append(repr(next(self.parents[0])))
                return iter(["word-" + str(len(self.events))])

        def main() -> str:
            gc_set_threshold(1)
            parents: list[Iterator[int | str]] = []
            events: list[str] = []
            values = chain([1], Words(parents, events), ["tail"])
            parents.append(values)
            assert events == []
            first = next(values)
            assert events == []
            gc_collect()
            return repr((first, list(values), events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_chain_mixed_active_cursor_errors_remain_retryable(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from itertools import chain
        from pyjs.native import gc_collect, gc_set_threshold

        def checked(value: int) -> int:
            gc_collect()
            if value == 1:
                raise ValueError("item")
            return value

        def main() -> str:
            gc_set_threshold(1)
            values = chain(map(checked, range(3)), ["tail"])
            first = next(values)
            try:
                next(values)
            except ValueError as error:
                message = str(error)
            else:
                message = "missing error"
            gc_collect()
            return repr((first, message, list(values)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("later", [False, True])
@pytest.mark.parametrize("optimize", [0, 2])
def test_chain_mixed_acquisition_allocation_failure_is_terminal(tmp_path, optimize, later):
    source = f'''
from itertools import chain
from pyjs.native import gc_collect, gc_set_threshold
from tests.native.allocation_support import arm

def main() -> int:
    gc_set_threshold(1)
    failures = 0
    for attempt in range(1, 16):
        values = chain([1], ["tail"])
        if {later}:
            assert repr(next(values)) == "1"
        complete = False
        try:
            arm(attempt)
            value = next(values)
            arm(0)
            complete = True
        except MemoryError:
            arm(0)
            failures += 1
            gc_collect()
            assert list(values) == []
        finally:
            arm(0)
        if complete:
            assert repr(value) == {repr(repr('tail') if later else '1')}
            assert repr(list(values)) == {repr('[]' if later else "['tail']")}
            return 0 if failures else 1
    return 2
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_chain_from_iterable_outer_failure_is_terminal_and_inner_failure_is_not(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import chain
        from pyjs.native import gc_collect, gc_set_threshold

        def checked(value: int) -> int:
            gc_collect()
            if value == 2:
                raise ValueError("two")
            return value

        def outer(value: int) -> list[int]:
            gc_collect()
            if value == 2:
                raise ValueError("two")
            return [value]

        def make() -> Iterator[str]:
            return chain.from_iterable([["a" + "1"], ["b" + "2"]])

        def main() -> str:
            gc_set_threshold(1)
            nested: list[list[int]] = [[0], [], [1]]
            assert list(chain.from_iterable(nested)) == [0, 1]
            values = chain.from_iterable(map(outer, range(4)))
            assert next(values) == 0 and next(values) == 1
            try:
                next(values)
            except ValueError:
                pass
            assert list(values) == []
            values = chain.from_iterable([map(checked, range(4)), map(checked, range(1))])
            assert next(values) == 0 and next(values) == 1
            try:
                next(values)
            except ValueError:
                pass
            assert list(values) == [3, 0]
            strings = make()
            gc_collect()
            return "".join(strings)
    ''', optimize=optimize)


@pytest.mark.parametrize("adapter, check", [
    ("repeat(words[0], 2)", 'list(result) == ["a", "a"]'),
    ("islice(map(collect, words), 1, None)", 'list(result) == ["é", "😀"]'),
    ("pairwise(map(collect, words))", 'list(result) == [("a", "é"), ("é", "😀")]'),
    ("batched(map(collect, words), 2)", '[list(row) for row in result] == [["a", "é"], ["😀"]]'),
    ("compress(map(collect, words), [1, 0, 1])", 'list(result) == ["a", "😀"]'),
    ("filterfalse(lambda word: len(collect(word)) > 1, words)", 'list(result) == words'),
    ("takewhile(lambda word: len(collect(word)) == 1, words)", 'list(result) == words'),
    ("dropwhile(lambda word: collect(word) == 'a', words)", 'list(result) == ["é", "😀"]'),
    ("chain(map(collect, words), words)", 'list(result) == words + words'),
    ("chain.from_iterable([words, words])", 'list(result) == words + words'),
])
@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("managed", [False, True], ids=["inferred", "gc-stress"])
def test_adapter_allocation_sweep(tmp_path, adapter, check, optimize, managed):
    source = f'''
from itertools import repeat, islice, pairwise, batched, compress, filterfalse, takewhile, dropwhile, chain
from pyjs.native import gc_collect, gc_set_threshold
from tests.native.allocation_support import arm

def collect(value: str) -> str:
    {"gc_collect()" if managed else "pass"}
    return value

def main() -> int:
    {"gc_set_threshold(1)" if managed else "pass"}
    words = ["a", "é", "😀"]
    failures = 0
    for attempt in range(1, 150):
        complete = False
        try:
            arm(attempt)
            result = {adapter}
            assert {check}
            arm(0)
            complete = True
        except MemoryError:
            arm(0)
            failures += 1
        finally:
            arm(0)
        {"gc_collect()" if managed else "pass"}
        assert words == ["a", "é", "😀"]
        result = {adapter}
        assert {check}
        if complete:
            return 0 if failures else 1
    return 2
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=managed, optimize=optimize)


@pytest.mark.parametrize("source, message", [
    ("chain()", "at least one typed iterable"),
    ("chain.from_iterable([1, 2])", "concrete inner iterable"),
    ("chain([int8(1)], [int16(1)])", "representation|expects"),
])
def test_adapter_diagnostics(source, message):
    with pytest.raises((CompilationError, LLVMUnsupported), match=message):
        transpile_llvm(f'''
from itertools import chain, islice, repeat
from pyjs import int8, int16
def main() -> int:
    result = {source}
    return 0
''')


@pytest.mark.parametrize("consumer", ["repr(next(values))", "repr(list(values))", "'unused'"])
def test_chain_ambiguous_item_layout_reports_creation_call(consumer):
    with pytest.raises(LLVMUnsupported, match="cannot distinguish different layouts") as caught:
        transpile_llvm(f'''
from itertools import chain
def main() -> str:
    left = [[1]]
    right = [["text"]]
    values = chain(left, right)
    return {consumer}
''')
    assert str(caught.value) == (
        "LLVM unions cannot distinguish different layouts of the same container class at line 4")
    assert caught.value.node.func.obj.py_func.__name__ == "chain"


def test_chain_requires_narrowing_a_union_of_iterable_objects():
    with pytest.raises(LLVMUnsupported, match="concrete iterable types; narrow unions before use at line"):
        transpile_llvm('''
from itertools import chain
def values(source: list[int] | tuple[int, ...]) -> str:
    return repr(list(chain(source, [2])))
def main() -> str:
    return values([1])
''')


@pytest.mark.parametrize("inputs", ["[1], (2, 'text')", "(2, 'text'), [1]"])
def test_chain_heterogeneous_tuple_diagnostic_has_source_location(inputs):
    with pytest.raises(LLVMUnsupported, match="concrete homogeneous item type.* at line 3") as caught:
        transpile_llvm(f'''
from itertools import chain
def main() -> int:
    marker = 1
    values = chain({inputs})
    return marker
''')
    assert caught.value.node.lineno == 3


@pytest.mark.parametrize("stop", ["stop", "None"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_reentrant_slice_preserves_nested_selection_and_consumption(stop, optimize, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    LLVM().assert_matches_python(f'''
        from collections.abc import Iterator
        from itertools import islice
        from pyjs.native import gc_collect, gc_set_threshold

        def item(cursors: list[Iterator[int]], events: list[int], trigger: int,
                 pulls: int, value: int) -> int:
            if value <= trigger:
                for attempt in range(pulls):
                    events.append(next(cursors[0], -1))
                gc_collect()
            return value

        def main() -> str:
            gc_set_threshold(1)
            result = ""
            for start in [0, 1, 3]:
                for stop in [0, 2, 6]:
                    for step in [1, 2, 9223372036854775807]:
                        for trigger in [1, 2]:
                            for pulls in [1, 3]:
                                cursors: list[Iterator[int]] = []
                                events: list[int] = []
                                source = map(lambda n: item(cursors, events, trigger, pulls, n), range(1, 9))
                                cursor = islice(source, start, {stop}, step)
                                cursors.append(cursor)
                                values = list(cursor)
                                gc_collect()
                                assert list(cursor) == []
                                result += f"{{start}}/{{stop}}/{{step}}/{{trigger}}/{{pulls}}="
                                result += ','.join(str(x) for x in values) + ':'
                                result += ','.join(str(x) for x in events) + ';'
                                result += str(next(source, -1)) + ';'
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("adapter", ["pairwise", "batched"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_reentrant_grouping_roots_captured_state_after_nested_exhaustion(adapter, optimize, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    element = "tuple[str, str]" if adapter == "pairwise" else "tuple[str, ...]"
    arguments = "source" if adapter == "pairwise" else "source, 2"
    LLVM().assert_matches_python(f'''
        from collections.abc import Iterator
        from itertools import {adapter}
        from pyjs.native import gc_collect, gc_set_threshold

        def item(cursors: list[Iterator[{element}]], events: list[str], value: int) -> str:
            if value == 2:
                for row in cursors[0]:
                    for text in row:
                        events.append(text)
                gc_collect()
            return "value:" + str(value)

        def main() -> str:
            gc_set_threshold(1)
            cursors: list[Iterator[{element}]] = []
            events: list[str] = []
            source = map(lambda n: item(cursors, events, n), range(1, 5))
            cursor = {adapter}({arguments})
            cursors.append(cursor)
            row = next(cursor)
            gc_collect()
            assert list(cursor) == []
            return "|".join(row) + ":" + "|".join(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("expression, result_type, source_type", [
    ("repeat(source[0], 2)", "str", "list[str]"),
    ("islice(source, None)", "str", "list[str]"),
    ("pairwise(source)", "tuple[str, str]", "list[str]"),
    ("batched(source, 2)", "tuple[str, ...]", "list[str]"),
    ("chain(source, source)", "str", "list[str]"),
    ("chain.from_iterable(source)", "str", "list[list[str]]"),
])
def test_adapter_lifetime_summary_retains_source(expression, result_type, source_type):
    with analyze_source(f'''
from collections.abc import Iterator
from itertools import repeat, islice, pairwise, batched, chain
def main(source: {source_type}) -> Iterator[{result_type}]:
    return {expression}
''', environment=NATIVE_ENVIRONMENT, entry_point="main") as analysis:
        lifetime = analysis.entry_point.ir.lifetime
        assert lifetime.returned_parameters == frozenset({"source"})
        assert lifetime.parameters["source"] is LifetimeBoundary.CALLER
