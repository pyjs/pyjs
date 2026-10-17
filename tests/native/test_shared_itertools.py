import ast
from textwrap import dedent

import pytest

from pyjs.analysis.source import analyze_source
from pyjs.analysis.value_representation import analyzed_representation
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.numeric import NumericFormat
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_tee_forks_and_nested_cursors(optimize):
    LLVM().assert_matches_python('''
        from itertools import tee

        def main() -> str:
            a, b = tee(range(100))
            assert next(a) == 0
            c, d = tee(a)
            assert next(c) == next(d) == next(a) == 1
            assert list(a) == list(range(2, 100))
            assert list(b) == list(range(100))
            assert list(c) == list(d) == list(range(2, 100))
            assert len(tee(range(5), 0)) == 0
            assert len(tee(range(5), 1)) == 1
            assert list(tee([True, False], 1)[0]) == [True, False]
            return "ok"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", [
    "groupby([1, 1, 2, 1])", "groupby([1, 1, 2, 1], None)",
    "groupby([1, 1, 2, 1], lambda n: n % 2)",
    "groupby(key=lambda n: n % 2, iterable=[1, 1, 2, 1])",
])
def test_groupby_adjacent_runs(expression, optimize):
    LLVM().assert_matches_python(dedent(f'''
        from itertools import groupby

        def main() -> str:
            result = ""
            for key, group in {expression}:
                result += str(key) + ":"
                for value in group:
                    result += str(value) + ","
                result += ";"
            return result
    '''), optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_groupby_wide_values_and_keys(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from itertools import count, groupby, islice
        from pyjs.native import gc_collect, gc_set_threshold

        def produce() -> Generator[int | float, None, None]:
            yield 0
            yield 0.5
            yield 1.0
            yield 1.5

        def integer_key(value: int | float) -> int:
            gc_collect()
            return int(value)

        def main() -> str:
            gc_set_threshold(1)
            values: list[int | float] = [True, 1.0, 0, 0.5, 0.5, 9007199254740993]
            result: list[str] = []
            for key, group in groupby(values):
                gc_collect()
                result.append(repr((key, list(group))))
            for integer, integer_group in groupby(values, integer_key):
                result.append(repr((integer, list(integer_group))))
            for generated_key, generated_group in groupby(produce(), integer_key):
                result.append(repr((generated_key, list(generated_group))))
            for counted_key, counted_group in groupby(islice(count(0, 0.5), 6)):
                result.append(repr((counted_key, list(counted_group))))
            # Advancing only the parent must compare complete keys while
            # draining skipped groups, not just their common numeric tag.
            result.append(repr([skipped_key for skipped_key, _ in groupby(islice(count(0, 0.5), 6), integer_key)]))
            nullable: list[int | None] = [1, 1, None, None, 2]
            for nullable_key, nullable_group in groupby(nullable):
                result.append(repr((nullable_key, list(nullable_group))))
            return repr(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_groupby_wide_pointer_payloads_survive_callbacks_and_invalidation(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import groupby
        from pyjs.native import gc_collect, gc_set_threshold

        def produce() -> Iterator[int | str]:
            for index in range(6):
                yield "value-" + str(index // 2)
            yield 42

        def checked(value: int | str) -> int | str:
            gc_collect()
            return value

        def fresh_key(value: int) -> int | str:
            gc_collect()
            if value < 4:
                return "key-" + str(value // 2)
            return value

        def held() -> Iterator[int | str]:
            key, group = next(groupby(produce(), checked))
            return group

        def main() -> str:
            gc_set_threshold(1)
            result: list[str] = []
            values: list[int | str] = [1, "a", 2]
            for key, group in groupby(values, lambda value: 0):
                result.append(repr((key, list(group))))
            # Key and item have independently sized storage in both directions.
            for fresh, fresh_group in groupby(range(6), fresh_key):
                gc_collect()
                result.append(repr((fresh, list(fresh_group))))
            groups = groupby(produce(), checked)
            first_key, first = next(groups)
            result.append(repr(next(first)))
            second_key, second = next(groups)
            gc_collect()
            result.append(repr((first_key, list(first), second_key, list(second))))
            for remaining_key, remaining_group in groups:
                gc_collect()
                result.append(repr((remaining_key, list(remaining_group))))
            retained = held()
            gc_collect()
            result.append(repr(list(retained)))
            return repr(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_groupby_wide_application_keys_keep_equality_operands_rooted(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import groupby
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events

            def __eq__(self, other: object) -> bool:
                gc_collect()
                if isinstance(other, Key):
                    self.events.append(self.value * 10 + other.value)
                    return self.value == other.value
                return False

        def produce(events: list[int]) -> Iterator[Key | int]:
            for index in range(6):
                yield Key(index // 2, events)
            yield 7

        def checked(value: Key | int) -> Key | int:
            gc_collect()
            return value

        def describe(value: Key | int) -> str:
            if isinstance(value, Key):
                return "key-" + str(value.value)
            return str(value)

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            result: list[str] = []
            for key, group in groupby(produce(events), checked):
                gc_collect()
                result.append(describe(key) + ":" + ",".join(describe(value) for value in group))
            return repr((result, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_groupby_wide_pending_item_survives_publication_failure(tmp_path, optimize):
    source = '''
from itertools import groupby
from pyjs.native import gc_collect, gc_set_threshold
from tests.native.allocation_support import arm

def main() -> int:
    gc_set_threshold(1)
    failures = 0
    for attempt in range(1, 12):
        values: list[int | str] = [1, 1, "next", "next", 2]
        groups = groupby(values)
        first_key, first = next(groups)
        assert repr(next(first)) == "1"
        failed = False
        try:
            arm(attempt)
            row = next(groups)
        except MemoryError:
            arm(0)
            failed = True
            failures += 1
            gc_collect()
            row = next(groups)
        finally:
            arm(0)
        gc_collect()
        assert list(first) == []
        key, group = row
        assert repr((key, list(group))) == "('next', ['next', 'next'])"
        assert repr([(key, list(group)) for key, group in groups]) == "[(2, [2])]"
        # Sweep every publication allocation without fixing the implementation's
        # allocation count in the contract; stop at the first unaffected run.
        if not failed:
            return 0 if failures else 1
    return 2
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_tee_errors_reentry_and_cached_reads(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import tee
        from pyjs.native import gc_collect, gc_set_threshold

        def source(cursors: list[Iterator[int]], events: list[int], value: int) -> int:
            gc_collect()
            if value == 1:
                events.append(next(cursors[1]))
                try:
                    next(cursors[0])
                except RuntimeError:
                    events.append(-10)
            if value == 2:
                raise ValueError("two")
            if value == 4:
                raise StopIteration("four")
            return value

        def main() -> str:
            gc_set_threshold(1)
            cursors: list[Iterator[int]] = []
            events: list[int] = []
            a, b = tee(map(lambda n: source(cursors, events, n), range(7)))
            cursors.append(a)
            cursors.append(b)
            result = ""
            for attempt in range(8):
                try:
                    result += str(next(a, -1)) + ','
                except ValueError:
                    result += "error,"
            result += ';' + ','.join(str(value) for value in b)
            result += ';' + ','.join(str(value) for value in events)
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_groupby_invalidation_and_error_recovery(optimize):
    LLVM().assert_matches_python('''
        from itertools import groupby

        def checked(value: int, errors: bool) -> int:
            if errors and value == 2:
                raise ValueError("two")
            if errors and value == 4:
                raise StopIteration("four")
            return value // 3

        def main() -> str:
            result = ""
            for key_errors in [False, True]:
                groups = groupby(map(lambda n: n if key_errors else checked(n, True), range(9)),
                                 key=lambda n: checked(n, key_errors))
                first_key, first = next(groups)
                result += str(first_key) + ':' + str(next(first, -1)) + ';'
                for attempt in range(9):
                    try:
                        key, group = next(groups)
                        result += str(key) + ':'
                        for pull in range(2):
                            try:
                                result += str(next(group, -1)) + ','
                            except ValueError:
                                result += 'item-error,'
                        result += ';'
                    except ValueError:
                        result += 'key-error;'
                    except StopIteration:
                        result += 'stop;'
                    result += str(next(first, -1)) + ';'
            groups = groupby([1, 1, 2, 2, 3])
            first_key, first = next(groups)
            second_key, second = next(groups)
            assert first_key == 1 and second_key == 2
            assert list(first) == [] and list(second) == [2, 2]
            third_key, third = next(groups)
            assert third_key == 3 and list(third) == [3]
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_iterators_keep_values_and_key_identity(optimize, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import groupby, tee
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs import int8, int64, float32

        class Box:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events

            def __eq__(self, other: Box) -> bool:
                self.events.append(self.value * 10 + other.value)
                gc_collect()
                return self.value == other.value

        def make(events: list[int]) -> Iterator[Box]:
            values = [Box(1, events), Box(1, events), Box(2, events)]
            key, group = next(groupby(values))
            return group

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            first = Box(1, events)
            second = Box(1, events)
            values = [first, first, second, Box(2, events)]
            a, b = tee(values)
            assert next(a) is first and next(b) is first
            first.value = 7
            values.clear()
            gc_collect()
            assert list(a) == [] and list(b) == []
            values = [first, first, second, Box(2, events)]
            result = ''
            for key, group in groupby(values, lambda box: box):
                result += str(key.value) + ':'
                for box in group:
                    result += str(box.value) + ','
                    gc_collect()
            result += ';'
            for group in tee(make(events)):
                for box in group:
                    result += str(box.value)
            left, right = tee([int8(127), int8(-128)])
            assert list(left) == list(right) == [int8(127), int8(-128)]
            for integer_key, integers in groupby([int64(2**53+1), int64(2**53+1)]):
                assert integer_key == int64(2**53+1) and sum(integers, int64(0)) == int64(2**54+2)
            for float_key, floats in groupby([float32(1.5), float32(1.5)]):
                assert float_key == float32(1.5) and sum(floats, float32(0)) == float32(3)
            return result + ';' + ','.join(str(value) for value in events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_tee_dynamic_count_and_gc_buffer_bound(optimize):
    result = LLVM().run_source('''
        from itertools import tee
        from pyjs.native import gc_collect, gc_count, gc_set_threshold

        def live(length: int, count: int) -> int:
            forks = tee(range(length), count)
            for value in range(length):
                for fork in forks:
                    assert next(fork) == value
                if value % 16 == 0:
                    gc_collect()
            gc_collect()
            return gc_count()

        def main() -> int:
            gc_set_threshold(1)
            assert live(1024, 3) <= live(64, 3) + 10
            assert len(tee(range(2), False)) == 0
            for count in [-1, -2]:
                try:
                    tee(range(2), count)
                except ValueError:
                    pass
                else:
                    return 1
            return 0
    ''', optimize=optimize)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("expression, check", [
    ("tee(words)", "list(result[0]) == words and list(result[1]) == words"),
    ("list((key, list(group)) for key, group in groupby(words))", "result == [('a', ['a', 'a']), ('b', ['b'])]"),
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_iterator_allocation_sweep(tmp_path, expression, check, optimize):
    source = f'''
from itertools import tee, groupby
from pyjs.native import gc_collect, gc_set_threshold
from tests.native.allocation_support import arm

def main() -> int:
    gc_set_threshold(1)
    words = ["a", "a", "b"]
    failures = 0
    for attempt in range(1, 150):
        complete = False
        try:
            arm(attempt)
            result = {expression}
            arm(0)
            assert {check}
            complete = True
        except MemoryError:
            arm(0)
            failures += 1
        finally:
            arm(0)
        gc_collect()
        result = {expression}
        assert {check}
        if complete:
            return 0 if failures else 1
    return 2
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("phase", ["source", "key"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_groupby_recursive_source_and_key_callbacks(phase, optimize, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    LLVM().assert_matches_python(f'''
        from collections.abc import Iterator
        from itertools import groupby
        from pyjs.native import gc_collect, gc_set_threshold

        def observe(parents: list[Iterator[tuple[int, Iterator[int]]]], events: list[int], value: int, trigger: int) -> int:
            if value == trigger:
                try:
                    key, group = next(parents[0])
                    events.append(key)
                    events.append(next(group, -1))
                except StopIteration:
                    events.append(-2)
            gc_collect()
            return value

        def main() -> str:
            gc_set_threshold(1)
            result = ''
            for trigger in range(6):
                parents: list[Iterator[tuple[int, Iterator[int]]]] = []
                events: list[int] = []
                source = map(lambda n: {"observe(parents, events, n, trigger)" if phase == "source" else "n"}, range(6))
                groups = groupby(source, lambda n: {"observe(parents, events, n, trigger)" if phase == "key" else "n"} // 2)
                parents.append(groups)
                for key, group in groups:
                    result += str(key) + ':'
                    for value in group:
                        result += str(value) + ','
                result += ';' + ','.join(str(event) for event in events) + ';'
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_groupby_equality_exceptions_and_recursive_advancement(optimize, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import groupby
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int, mode: int, events: list[int], parents: list[Iterator[tuple[Key, Iterator[int]]]]):
                self.value = value
                self.mode = mode
                self.events = events
                self.parents = parents

            def __eq__(self, other: Key) -> bool:
                if len(self.events) == 0:
                    self.events.append(10 * self.value + other.value)
                    if self.mode == 0:
                        raise ValueError('comparison')
                    if self.mode == 1:
                        raise StopIteration('comparison')
                    if self.mode == 2:
                        key, group = next(self.parents[0])
                        self.events.append(key.value)
                        self.events.append(next(group, -1))
                gc_collect()
                return self.value == other.value

        def main() -> str:
            gc_set_threshold(1)
            result = ''
            for mode in range(3):
                parents: list[Iterator[tuple[Key, Iterator[int]]]] = []
                events: list[int] = []
                groups = groupby(range(6), lambda n: Key(n // 2, mode, events, parents))
                parents.append(groups)
                for attempt in range(8):
                    try:
                        key, group = next(groups)
                        result += str(key.value) + ':'
                        for pull in range(4):
                            try:
                                result += str(next(group, -1)) + ','
                            except ValueError:
                                result += 'item-error,'
                    except StopIteration:
                        result += 'stop;'
                    except ValueError:
                        result += 'key-error;'
                result += ';' + ','.join(str(event) for event in events) + ';'
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_tuple_assignment_and_grouped_metrics_ssr(optimize):
    LLVM().assert_matches_python('''
        from itertools import groupby, tee
        from pyjs import int8
        from pyjs.web.domx import tag
        from pyjs.web.ssr import render_html

        def pair(value: int) -> tuple[int8, tuple[str, int]]:
            return int8(value), ('row', value)

        def main() -> str:
            small, (text, number) = pair(127)
            small += int8(1)
            assert small == int8(-128) and text == 'row' and number == 127
            small, (text, number) = pair(1)
            assert small == int8(1) and number == 1
            values = [('database', 3), ('database', 5), ('web', 11), ('web', 17)]
            summary, details = tee(values)
            result = tag('table', tag('tr', tag('th', 'Service'), tag('th', 'Requests')))
            for service, group in groupby(summary, key=lambda row: row[0]):
                total = sum(row[1] for row in group)
                tag(result, tag('tr', tag('th', service), tag('td', str(total))))
            for service, requests in details:
                tag(result, tag('tr', tag('td', service), tag('td', str(requests))))
            for key, group in groupby([1, 1, 2], lambda value: [value]):
                assert key[0] == next(group)
            return render_html(result)
    ''', optimize=optimize)


@pytest.mark.parametrize("actual,expected,value,initial", [
    ("list[bool]", "list[int]", "[True, False, True]", "[10, 20, 30]"),
    ("list[int]", "list[float]", "[1, 2]", "[0.5]"),
    ("tuple[bool, bool, bool]", "tuple[int, ...]", "(True, False, True)", "(1, 2, 3)"),
    ("list[list[bool]]", "list[list[int]]", "[[True]]", "[[1]]"),
    ("dict[str, bool]", "dict[str, int]", "{'x': True}", "{'x': 1}"),
])
@pytest.mark.parametrize("assignment", ["values, count = produce()", "values = produce()[0]"])
def test_assignment_rejects_reinterpreted_collection_storage(actual, expected, value, initial, assignment):
    # Covariant source typing does not make unboxed element layouts compatible.
    # Both destructuring and direct stores must reject the same unsafe view.
    with pytest.raises(LLVMUnsupported, match="matching concrete item storage"):
        transpile_llvm(f'''
def produce() -> tuple[{actual}, int]:
    return {value}, 1
def main() -> int:
    values: {expected} = {initial}
    {assignment}
    return len(values)
''')


@pytest.mark.parametrize("operation", [
    "read(dogs)",
    "read(*[dogs])",
    "values: list[Animal] = dogs",
    "values: list[Animal] = []\n    values, count = (dogs, 1)",
    "produce(dogs)",
    "read_dict(pets)",
    "read_nested(packs)",
])
def test_collection_element_types_are_invariant_for_application_subclasses(operation):
    # Pointer-sized elements are not safely interchangeable: widening the
    # alias would let a callee append Animal into storage later read as Dog.
    with pytest.raises(LLVMUnsupported, match=r"element types \(invariant\)"):
        transpile_llvm(f'''
class Animal:
    def __init__(self):
        self.age = 1
class Dog(Animal):
    def __init__(self):
        self.age = 1
        self.tail = 2
def read(values: list[Animal]) -> int:
    return len(values)
def read_dict(values: dict[str, Animal]) -> int:
    return len(values)
def read_nested(values: list[list[Animal]]) -> int:
    return len(values)
def produce(values: list[Dog]) -> list[Animal]:
    return values
def main() -> int:
    dogs = [Dog()]
    pets = {{'pet': Dog()}}
    packs = [dogs]
    {operation}
    return 0
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_fresh_base_typed_collection_does_not_widen_subclass_alias(optimize):
    LLVM().assert_matches_python('''
        class Animal:
            def __init__(self):
                self.age = 1
        class Dog(Animal):
            def __init__(self):
                self.age = 1
                self.tail = 2
        def extend(values: list[Animal]) -> int:
            values.append(Animal())
            return len(values)
        def main() -> str:
            dogs = [Dog()]
            widened: list[Animal] = [dogs[0]]
            count = extend(widened)
            return str(count) + ':' + str(len(dogs)) + ':' + str(dogs[0].tail)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("kind", ["float", "float32", "float64"])
def test_groupby_nan_keys_consume_or_skip_opening_items(kind, optimize):
    LLVM().assert_matches_python(f'''
        from itertools import groupby
        from pyjs import float32, float64
        from pyjs.native import gc_collect, gc_set_threshold

        def observe(events: list[int], value: {kind}) -> {kind}:
            events.append(1)
            gc_collect()
            return value

        def main() -> str:
            gc_set_threshold(1)
            result = ''
            for consume in range(2):
                events: list[int] = []
                values = [{kind}(float('nan')), {kind}(1), {kind}(float('nan')), {kind}(2)]
                groups = groupby(values, key=lambda value: observe(events, value))
                # Bound both loops so a progress regression fails, never hangs.
                for attempt in range(6):
                    try:
                        key, group = next(groups)
                    except StopIteration:
                        result += 'end;'
                        break
                    count = 0
                    if consume:
                        for pull in range(6):
                            try:
                                next(group)
                            except StopIteration:
                                break
                            count += 1
                    result += str(count) + ','
                result += str(len(events)) + '|'
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("expression", ["tee([None])", "tee([None], 0)", "groupby([1], lambda value: None)"])
def test_shared_iterators_construct_none_storage(expression):
    LLVM().assert_matches_python(f'''
from itertools import tee, groupby
def main() -> int:
    value = {expression}
    return 0
''')


def test_tee_construction_without_advancement_links_runtime():
    LLVM().assert_matches_python('''
        from itertools import tee
        def main() -> int:
            return len(tee([1, 2, 3]))
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_shared_iterator_empty_and_large_arity_boundaries(optimize):
    LLVM().assert_matches_python('''
        from itertools import tee, groupby

        def main() -> int:
            empty: list[str] = []
            assert len(list(groupby(empty))) == 0
            assert len(list(groupby(range(0)))) == 0
            for fork in tee(()):
                assert len(list(fork)) == 0
            for fork in tee(empty, 3):
                assert len(list(fork)) == 0
            forks = tee([1, 2], 257)
            assert len(forks) == 257
            assert next(forks[256]) == next(forks[0]) == 1
            only, = tee([1, 2], True)
            assert list(only) == [1, 2]
            return 0
    ''', optimize=optimize)


@pytest.mark.parametrize("values", ["'éé😀é'", "b'aaba'", "[True, True, False, True]", "[1.5, 1.5, 2.0]"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_groupby_scalar_storage_kinds(values, optimize):
    LLVM().assert_matches_python(f'''
        from itertools import groupby

        def main() -> str:
            result = ''
            for key, group in groupby({values}):
                result += str(key) + ':' + str(len(list(group))) + ';'
            return result
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_tee_escaped_pointer_blocks_and_aliases(optimize, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import tee
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, text: str):
                self.text = text

        def make() -> tuple[Iterator[Box], ...]:
            return tee(map(lambda n: Box('box-' + str(n)), range(100)))

        def main() -> str:
            gc_set_threshold(1)
            forks = make()
            first = next(forks[0])
            first.text = 'changed'
            for box in forks[0]:
                gc_collect()
            result = ''
            for box in forks[1]:
                gc_collect()
                result += box.text + ','
            assert result.startswith('changed,box-1,')
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_groupby_reaches_nested_reflected_equality(optimize):
    LLVM().assert_matches_python('''
        from itertools import groupby
        from pyjs.native import gc_collect

        class Base:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events

            def __eq__(self, other: Base) -> bool:
                self.events.append(10 + self.value)
                gc_collect()
                return self.value == other.value

        class Child(Base):
            def __eq__(self, other: Base) -> bool:
                self.events.append(20 + self.value)
                gc_collect()
                return self.value == other.value

        def main() -> str:
            events: list[int] = []
            values: list[Base] = [Base(1, events), Child(1, events), Base(2, events)]
            result = ''
            for key, group in groupby(values, lambda value: [value]):
                result += str(key[0].value) + ':' + str(len(list(group))) + ';'
            return result + ','.join(str(event) for event in events)
    ''', optimize=optimize)


def test_shared_iterator_ir_and_nested_representations():
    source = '''
from itertools import groupby, tee
from pyjs import int8
def main() -> int8:
    left, right = tee([int8(127)])
    key, group = next(groupby(left))
    return key + next(group) + next(right)
'''
    with analyze_source(source, environment=NATIVE_ENVIRONMENT, wrap=False) as analysis:
        assert analysis.types.strip() == dedent('''
            def groupby(iterable: Iterable__T, key: Callable[[T], K] | None=None) -> Iterator[object]:
                external

            def tee(iterable: Iterable__T, n: int=2, /) -> tuple[Iterator[T], ...]:
                external

            def main() -> int:
                block entry:
                    $assignment0: tuple[Iterator[int], Iterator[int]] = tee(new[external] list[int](int(127)))
                    $assignment4: int = len($assignment0)
                    branch $assignment4.[int]__lt__(2):
                        true -> if_true
                        false -> if_done
                block if_true:
                    raise ValueError(f"not enough values to unpack (expected 2, got {format($assignment4, '')})")
                block if_done:
                    branch $assignment4.[int]__gt__(2):
                        true -> if_true_2
                        false -> if_done_2
                block if_true_2:
                    raise ValueError(f"too many values to unpack (expected 2, got {format($assignment4, '')})")
                block if_done_2:
                    $assignment5: Iterator[int] = $assignment0.[tuple__Iterator__int_Iterator__int]__getitem__(0)
                    $assignment6: Iterator[int] = $assignment0.[tuple__Iterator__int_Iterator__int]__getitem__(1)
                    left: Iterator[int] = $assignment5
                    right: Iterator[int] = $assignment6
                    $assignment9: tuple[int, Iterator[int]] = next(groupby(left))
                    $assignment10: int = len($assignment9)
                    branch $assignment10.[int]__lt__(2):
                        true -> if_true_3
                        false -> if_done_3
                block if_true_3:
                    raise ValueError(f"not enough values to unpack (expected 2, got {format($assignment10, '')})")
                block if_done_3:
                    branch $assignment10.[int]__gt__(2):
                        true -> if_true_4
                        false -> if_done_4
                block if_true_4:
                    raise ValueError(f"too many values to unpack (expected 2, got {format($assignment10, '')})")
                block if_done_4:
                    $assignment11: int = $assignment9.[tuple__int_Iterator__int]__getitem__(0)
                    $assignment12: Iterator[int] = $assignment9.[tuple__int_Iterator__int]__getitem__(1)
                    key: int = $assignment11
                    group: Iterator[int] = $assignment12
                    return key.[int]__add__(next(group)).[int]__add__(next(right))
        ''').strip()
        calls = {node.func.obj.name: node for block in analysis.entry_point.ir.blocks
                 for node in ast.walk(block) if isinstance(node, ast.Call)
                 and getattr(getattr(node.func, "obj", None), "name", None) in {"tee", "groupby"}}
        expected = NumericFormat("integer", 8, signed=True)
        forks = analyzed_representation(calls["tee"])
        assert [fork.arguments[0].numeric for fork in forks.arguments] == [expected, expected]
        row = analyzed_representation(calls["groupby"]).arguments[0]
        assert row.arguments[0].numeric == expected
        assert row.arguments[1].arguments[0].numeric == expected
    LLVM().assert_matches_python(source)
