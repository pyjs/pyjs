"""Application iteration uses the same stream consumers and checked call ABI."""

from textwrap import dedent

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("descriptor,parameter", [("property", "self"), ("staticmethod", ""), ("classmethod", "cls")])
@pytest.mark.parametrize("expression", ["str(list(value))", "str([item for item in value])"])
def test_base_typed_iteration_rejects_reached_descriptor_overrides(descriptor, parameter, expression):
    with pytest.raises(LLVMUnsupported, match="LLVM application __iter__ requires an instance method"):
        transpile_llvm(f'''
            from collections.abc import Iterator
            class Base:
                def __iter__(self) -> Iterator[int]:
                    return iter([1])
            class Derived(Base):
                @{descriptor}
                def __iter__({parameter}) -> Iterator[int]:
                    return iter([2])
            def consume(value: Base) -> str:
                return {expression}
            def main() -> str:
                return consume(Derived())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_partial_batches_preserve_resumable_child(optimize):
    comparison = LLVM().assert_matches_python('''
        from itertools import batched
        from pyjs.native import gc_collect, gc_set_threshold

        class Done(StopIteration):
            pass

        def step(value: int) -> int:
            gc_collect()
            if value == 2:
                raise Done("temporary")
            return value

        def run(strict: bool) -> str:
            cursor = batched(map(step, [1, 2, 3, 4, 5]), 2, strict=strict)
            result = ""
            for attempt in range(4):
                gc_collect()
                try:
                    row = next(cursor)
                    result += str(len(row)) + "/" + str(sum(row)) + ";"
                except StopIteration:
                    result += "stop;"
                except ValueError as error:
                    result += str(error) + ";"
            return result

        def main() -> str:
            gc_set_threshold(1)
            return run(False) + "|" + run(True)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_chain_active_predicate_reenters_terminal_acquisition(optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import chain
        from pyjs.native import gc_collect, gc_set_threshold

        class Source:
            def __init__(self, fail: bool):
                self.fail = fail
                self.calls = 0
            def __iter__(self) -> Iterator[int]:
                self.calls += 1
                gc_collect()
                if self.fail:
                    raise ValueError("acquire")
                return iter([7, 8])

        def predicate(value: int, box: list[Iterator[int]], events: list[int]) -> bool:
            try:
                events.append(next(box[0], -1))
            except ValueError:
                events.append(-9)
            return False

        def main() -> str:
            gc_set_threshold(1)
            box: list[Iterator[int]] = []
            events: list[int] = []
            failed = Source(True)
            untouched = Source(False)
            head = filter(lambda value: predicate(value, box, events), [1])
            cursor = chain(head, failed, untouched)
            box.append(cursor)
            result = ""
            for index in range(4):
                gc_collect()
                result += str(next(cursor, -1)) + ","
            return result + str(events[0]) + ":" + str(failed.calls) + str(untouched.calls)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("body", [
    "result = 0\nfor value in values:\n    result += value\nreturn result",
    "return sum([value for value in values])",
    "return sum(value for value in values)",
    "return sum(values)",
    "return sum(list(values))",
    "return int(3 in values)",
])
def test_protocol_reachability_without_other_consumers(body):
    # Each program has only one consumer: another use must not accidentally
    # retain __iter__ and hide an omitted dependency in that consumer's IR.
    from textwrap import indent

    LLVM().assert_matches_python('''
from collections.abc import Iterator

class Values:
    def __iter__(self) -> Iterator[int]:
        return iter([1, 2, 3])

class Derived(Values):
    def __iter__(self) -> Iterator[int]:
        return iter([2, 3, 4])

def consume(values: Values) -> int:
''' + indent(body, "    ") + '''

def main() -> int:
    return consume(Derived())
''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_iterables_and_consumers(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import chain, pairwise, tee, groupby, zip_longest
        from pyjs.native import gc_collect, gc_set_threshold

        class Values:
            def __init__(self, n: int, events: list[int]):
                self.n = n
                self.events = events

            def __iter__(self) -> Iterator[int]:
                self.events.append(self.n)
                gc_collect()
                return iter(range(self.n))

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            values = Values(4, events)
            assert list(values) == [0, 1, 2, 3]
            assert set(values) == {0, 1, 2, 3}
            assert tuple(values) == (0, 1, 2, 3)
            assert sum(values) == 6
            assert any(values)
            assert not all(values)
            assert max(values) == 3
            assert min(values) == 0
            assert sorted(values, reverse=True) == [3, 2, 1, 0]
            assert list(map(lambda n: n + 1, values)) == [1, 2, 3, 4]
            assert list(filter(lambda n: n > 1, values)) == [2, 3]
            assert [n * 2 for n in values] == [0, 2, 4, 6]
            assert sum(n for n in values) == 6
            assert list(pairwise(values)) == [(0, 1), (1, 2), (2, 3)]
            assert list(chain(values, values)) == [0, 1, 2, 3, 0, 1, 2, 3]
            assert list(zip(values, values)) == [(0, 0), (1, 1), (2, 2), (3, 3)]
            assert list(zip_longest(values, Values(2, events), fillvalue=-1)) == [(0, 0), (1, 1), (2, -1), (3, -1)]
            a, b = tee(values)
            assert list(a) == list(b) == [0, 1, 2, 3]
            grouped = 0
            for key, group in groupby(values, lambda n: n // 2):
                grouped += sum(group) + key
            assert grouped == 7
            total = 0
            for value in values:
                total += value
            assert total == 6
            assert 3 in values and 8 not in values
            gc_collect()
            return str(len(events))
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("adapter", ["zip", "map", "zip_longest"])
def test_iterable_dispatch_order_and_intermediate_cursor_roots(optimize, adapter):
    expression = {
        "zip": "zip(make(1, events), make(2, events))",
        "map": "map(lambda x, y: x + y, make(1, events), make(2, events))",
        "zip_longest": "zip_longest(make(1, events), make(2, events), fillvalue=\"none\")",
    }[adapter]
    LLVM().assert_matches_python(dedent(f'''
        from collections.abc import Iterator
        from itertools import zip_longest
        from pyjs.native import gc_collect, gc_set_threshold

        class Values:
            def __init__(self, marker: int, events: list[int]):
                self.marker = marker
                self.events = events

            def __iter__(self) -> Iterator[str]:
                self.events.append(self.marker + 10)
                gc_collect()
                return iter([str(self.marker) + "a", str(self.marker) + "b"])

        class Derived(Values):
            def __iter__(self) -> Iterator[str]:
                self.events.append(self.marker + 20)
                gc_collect()
                return iter([str(self.marker) + "c", str(self.marker) + "d"])

        def make(marker: int, events: list[int]) -> Values:
            events.append(marker)
            return Derived(marker, events)

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            cursor = {expression}
            assert events == [1, 2, 21, 22]
            gc_collect()
            result = ""
            for row in cursor:
                result += {"row" if adapter == "map" else "row[0] + row[1]"}
                gc_collect()
            return result
    '''), optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterable_errors_generator_methods_and_short_circuit_cleanup(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Values:
            def __init__(self):
                self.fail = True

            def __iter__(self) -> Iterator[int]:
                if self.fail:
                    raise ValueError("iter")
                return iter([1, 2, 3])

        class Rows:
            def __init__(self):
                self.n = 3

            def __iter__(self) -> Iterator[str]:
                for i in range(self.n):
                    gc_collect()
                    yield str(i) + "x"

        def main() -> str:
            gc_set_threshold(1)
            values = Values()
            try:
                list(values)
            except ValueError as error:
                assert str(error) == "iter"
            values.fail = False
            assert any(values)
            assert all(values)
            assert 1 in values
            assert 9 not in values
            assert next(iter(values)) == 1
            gc_collect()
            rows = Rows()
            assert ",".join(rows) == "0x,1x,2x"
            return ";".join(list(rows))
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation, items, sentinel", [
    ("int", "[1, 2, 0, 9]", "0"),
    ("bool", "[True, True, False, True]", "False"),
    ("str", "['a', 'é', '', 'tail']", "''"),
    ("bytes", "[b'a', b'b', b'', b'tail']", "b''"),
    ("float", "[1.5, 2.5, 0.0, 9.0]", "0.0"),
    ("int8", "[int8(1), int8(2), int8(0), int8(9)]", "int8(0)"),
    ("float32", "[float32(1.5), float32(2.5), float32(0), float32(9)]", "float32(0)"),
])
def test_sentinel_values_closures_and_permanent_exhaustion(optimize, annotation, items, sentinel):
    LLVM().assert_matches_python(dedent(f'''
        from collections.abc import Callable
        from pyjs import int8, float32
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            values = {items}
            pull: Callable[[], {annotation}] = lambda: {annotation}(values.pop(0))
            cursor = iter(pull, {sentinel})
            gc_collect()
            result = ""
            for value in cursor:
                result += str(value) + ":"
                gc_collect()
            assert next(cursor, {sentinel}) == {sentinel}
            assert next(cursor, {sentinel}) == {sentinel}
            assert len(values) == 1
            return result
    '''), optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_sentinel_bound_callback_error_recovery_and_stop_subclass(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Done(StopIteration):
            pass

        class Source:
            def __init__(self):
                self.index = 0

            def pull(self) -> int:
                self.index += 1
                gc_collect()
                if self.index == 1:
                    raise ValueError("retry")
                if self.index == 3:
                    raise Done("stop")
                return self.index

        def main() -> str:
            gc_set_threshold(1)
            source = Source()
            cursor = iter(source.pull, 100)
            try:
                next(cursor)
            except ValueError as error:
                assert str(error) == "retry"
            assert next(cursor) == 2
            assert next(cursor, -1) == -1
            assert next(cursor, -1) == -1
            assert source.index == 3
            return "ok"
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_sentinel_equality_order_errors_and_identity(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events

            def __eq__(self, other: "Key") -> bool:
                self.events.append(self.value * 10 + other.value)
                gc_collect()
                if other.value == 1:
                    raise ValueError("equal")
                if other.value == 2:
                    raise StopIteration("temporary")
                return self.value == other.value

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            sentinel = Key(5, events)
            values = [Key(1, events), Key(2, events), Key(3, events), sentinel, Key(8, events)]
            pull: Callable[[], Key] = lambda: values.pop(0)
            cursor = iter(pull, sentinel)
            try:
                next(cursor)
            except ValueError:
                pass
            assert next(cursor, sentinel) is sentinel
            assert next(cursor).value == 3
            assert next(cursor, sentinel) is sentinel
            assert next(cursor, sentinel) is sentinel
            assert len(values) == 1
            assert events == [51, 52, 53]
            return "ok"
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("source", [
    "def value(n: int) -> int: return n\ndef main() -> int: return next(iter(value, 1))",
    "def value() -> int: return 1\ndef main() -> int: return next(iter(value, True))",
    "from pyjs import int8\ndef value() -> int8: return int8(1)\ndef main() -> int: return int(next(iter(value, 1)))",
    "def value() -> int: return 1\ndef main() -> int: return next(iter(value, sentinel=1))",
])
def test_sentinel_rejects_incompatible_call_contracts(source):
    with pytest.raises(CompilationError, match=r"\[PYJS1104\]"):
        transpile_llvm(source)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("phase", ["callback", "equality"])
def test_sentinel_reentrant_exhaustion_retains_inflight_values(optimize, phase):
    LLVM().assert_matches_python(dedent(f'''
        from collections.abc import Callable, Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Key:
            def __init__(self, value: int, cursors: list[Iterator[Key]], events: list[int]):
                self.value = value
                self.cursors = cursors
                self.events = events

            def __eq__(self, other: "Key") -> bool:
                self.events.append(self.value * 10 + other.value)
                if {phase == "equality"!r} and other.value == 1:
                    self.events.append(next(self.cursors[0], self).value + 100)
                gc_collect()
                return self.value == other.value

        def pull(values: list[Key], cursors: list[Iterator[Key]], events: list[int], sentinel: Key) -> Key:
            value = values.pop(0)
            if {phase == "callback"!r} and value.value == 1:
                events.append(next(cursors[0], sentinel).value + 100)
            gc_collect()
            return value

        def main() -> str:
            gc_set_threshold(1)
            cursors: list[Iterator[Key]] = []
            events: list[int] = []
            sentinel = Key(5, cursors, events)
            values = [Key(1, cursors, events), sentinel, Key(9, cursors, events)]
            callback: Callable[[], Key] = lambda: pull(values, cursors, events, sentinel)
            cursor = iter(callback, sentinel)
            cursors.append(cursor)
            first = next(cursor, sentinel).value
            second = next(cursor, sentinel).value
            gc_collect()
            return str(first) + ":" + str(second) + ":" + ",".join(str(e) for e in events)
    '''), optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_protocol_construction_allocation_recovery(tmp_path, optimize):
    from tests.native.allocation_support import run_allocation_case

    source = '''
from collections.abc import Callable, Iterator
from pyjs.native import gc_collect
from tests.native.allocation_support import arm, remaining

class Source:
    def __init__(self):
        self.calls = 0
    def pull(self) -> int:
        self.calls += 1
        return self.calls
    def __iter__(self) -> Iterator[int]:
        return iter([1, 2, 3])

def build(callback: Callable[[], int]) -> Iterator[int]:
    return iter(callback, 2)

def main() -> int:
    source = Source()
    callback = source.pull
    original = iter([9])
    arm(1000)
    cursor = build(callback)
    allocations = 1000 - remaining()
    arm(0)
    assert source.calls == 0
    assert allocations > 0
    for failure in range(1, allocations + 1):
        cursor = original
        arm(failure)
        try:
            cursor = build(callback)
        except MemoryError:
            pass
        finally:
            arm(0)
        assert cursor is original
        assert source.calls == 0
        gc_collect()
    cursor = build(callback)
    assert next(cursor) == 1
    assert next(cursor, -1) == -1
    assert next(cursor, -1) == -1
    for failure in range(1, 30):
        complete = False
        arm(failure)
        try:
            assert list(zip(Source(), Source())) == [(1, 1), (2, 2), (3, 3)]
            complete = True
        except MemoryError:
            pass
        finally:
            arm(0)
        gc_collect()
        assert list(source) == [1, 2, 3]
        if complete:
            return 0
    return 1
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_rows_render_through_native_dom(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.web.domx import div, span, tag
        from pyjs.web.ssr import render_html
        from pyjs.native import gc_collect, gc_set_threshold

        class Settings:
            def __init__(self, names: list[str]):
                self.names = names
            def __iter__(self) -> Iterator[str]:
                for name in self.names:
                    gc_collect()
                    yield name

        def main() -> str:
            gc_set_threshold(1)
            settings = Settings(["work_mem", "max_connections", "<log>"])
            page = div()
            for name in settings:
                tag(page, div(span(name), span("current")))
            gc_collect()
            return render_html(page)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_streams_share_materialization_and_reduction_paths(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from functools import reduce
        from itertools import accumulate, batched, combinations, compress, cycle, islice, product
        from math import fsum
        from pyjs.native import gc_collect, gc_set_threshold

        class Values:
            def __iter__(self) -> Iterator[int]:
                gc_collect()
                return iter([1, 2, 3])

        class Rows:
            def __iter__(self) -> Iterator[str]:
                gc_collect()
                return iter(["one", "two", "three"])

        def add_all(*values: int) -> int:
            return sum(values)

        def main() -> str:
            gc_set_threshold(1)
            values = Values()
            assert list(accumulate(values)) == [1, 3, 6]
            assert list(islice(cycle(values), 5)) == [1, 2, 3, 1, 2]
            assert list(compress(values, values)) == [1, 2, 3]
            assert [sum(batch) for batch in batched(values, 2)] == [3, 3]
            assert [row[0] * 10 + row[1] for row in combinations(values, 2)] == [12, 13, 23]
            assert sum(row[0] + row[1] for row in product(values, values)) == 36
            assert reduce(lambda a, b: a + b, values, 0) == 6
            assert fsum(values) == 6.0
            assert add_all(*values) == 6
            gc_collect()
            return ",".join(Rows())
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterable_method_can_retain_a_temporary_receiver(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Values:
            def __init__(self, saved: list[Values]):
                self.saved = saved
                self.value = "retained"
            def __iter__(self) -> Iterator[str]:
                return iter([self.value])

        class Retained(Values):
            def __iter__(self) -> Iterator[str]:
                self.saved.append(self)
                gc_collect()
                return iter([self.value])

        def consume(values: Values) -> None:
            for value in values:
                pass

        def remember(saved: list[Values]) -> None:
            consume(Retained(saved))

        def main() -> str:
            gc_set_threshold(1)
            saved: list[Values] = []
            for index in range(12):
                remember(saved)
            gc_collect()
            return ",".join(item.value for item in saved)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation, values, sentinel", [
    ("list[int]", "[[1], [2], [3], [4]]", "[3]"),
    ("tuple[int, int]", "[(1, 2), (3, 4), (5, 6)]", "(3, 4)"),
    ("list[list[int]]", "[[[1]], [[2]], [[3]]]", "[[2]]"),
    ("tuple[list[int], list[int]]", "[([1], [2]), ([3], [4]), ([5], [6])]", "([3], [4])"),
])
def test_sentinel_is_the_only_sequence_equality_dependency(optimize, annotation, values, sentinel):
    # An explicit sequence equality elsewhere would hide missing runtime helpers.
    LLVM().assert_matches_python(dedent(f'''
        from collections.abc import Callable
        from pyjs.native import gc_collect, gc_set_threshold

        def main() -> str:
            gc_set_threshold(1)
            values = {values}
            pull: Callable[[], {annotation}] = lambda: values.pop(0)
            cursor = iter(pull, {sentinel})
            count = 0
            for index in range(5):
                try:
                    next(cursor)
                    count += 1
                    gc_collect()
                except StopIteration:
                    break
            gc_collect()
            return str(count) + ":" + str(len(values))
    '''), optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("operation", ["isdisjoint", "issuperset", "issubset", "intersection", "intersection_update"])
def test_application_set_consumers_cleanup_short_circuits_and_exhaustion(optimize, operation):
    statement = f"result = selected.{operation}(Values(events))"
    if operation == "intersection":
        statement = "result = len(selected.intersection(Values(events)))"
    elif operation == "intersection_update":
        statement = "selected.intersection_update(Values(events))\n            result = len(selected)"
    LLVM().assert_matches_python(dedent(f'''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Values:
            def __init__(self, events: list[int]):
                self.events = events
            def __iter__(self) -> Iterator[int]:
                for value in [1, 2, 3]:
                    self.events.append(value)
                    gc_collect()
                    yield value

        def check(selected: set[int]) -> str:
            events: list[int] = []
            {statement}
            gc_collect()
            return str(result) + ":" + str(len(events)) + ";"

        def main() -> str:
            gc_set_threshold(1)
            empty: set[int] = set()
            return check({{1}}) + check({{4}}) + check({{1, 2, 3, 4}}) + check(empty)
    '''), optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_chain_outer_and_virtual_inner_acquisition_can_collect(optimize):
    # chain is the only consumer of either application protocol. The override
    # must be reached from the inner item type, not an unrelated explicit iter().
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import chain
        from pyjs.native import gc_collect, gc_set_threshold

        class Inner:
            def __iter__(self) -> Iterator[str]:
                return iter(["base"])

        class Derived(Inner):
            def __iter__(self) -> Iterator[str]:
                gc_collect()
                return iter(["a", "b"])

        class Outer:
            def __iter__(self) -> Iterator[Inner]:
                gc_collect()
                values: list[Inner] = [Derived(), Derived()]
                return iter(values)

        def main() -> str:
            gc_set_threshold(1)
            cursor = chain.from_iterable(Outer())
            gc_collect()
            result = ""
            for index in range(5):
                result += next(cursor, "")
                gc_collect()
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("exception", ["StopIteration", "Done"])
@pytest.mark.parametrize("expression", ["chain(values, values)", "chain.from_iterable([values, values])"])
def test_chain_acquisition_stop_iteration_exhausts_all_consumers(optimize, exception, expression):
    LLVM().assert_matches_python(dedent(f'''
        from collections.abc import Iterator
        from itertools import chain
        from pyjs.native import gc_collect, gc_set_threshold

        class Done(StopIteration):
            pass

        class Values:
            def __init__(self):
                self.calls = 0
            def __iter__(self) -> Iterator[int]:
                self.calls += 1
                gc_collect()
                raise {exception}("acquire")

        def check(consumer: int) -> str:
            values = Values()
            cursor = {expression}
            result = ""
            if consumer == 0:
                assert next(cursor, -1) == -1
            elif consumer == 1:
                assert len(list(cursor)) == 0
            elif consumer == 2:
                count = 0
                for item in cursor:
                    count += 1
                assert count == 0
            else:
                try:
                    next(cursor)
                    result = "missing error"
                except Done as error:
                    result = "Done:" + str(error)
                except StopIteration as error:
                    result = "StopIteration:" + str(error)
            gc_collect()
            assert next(cursor, -1) == -1
            assert next(cursor, -1) == -1
            return result + str(values.calls)

        def main() -> str:
            gc_set_threshold(1)
            return check(0) + check(1) + check(2) + check(3)
    '''), optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_adapters_preserve_or_consume_stop_iteration_at_their_boundary(optimize):
    # One compiled program covers forwarding vs consuming adapters, including
    # callback-raised StopIteration and strict-zip conversion to ValueError.
    expressions = [
        "chain(Bad())", "map(identity, chain(Bad()))", "filter(positive, chain(Bad()))",
        "filterfalse(positive, chain(Bad()))", "takewhile(positive, chain(Bad()))",
        "dropwhile(positive, chain(Bad()))", "compress(chain(Bad()), [True])",
        "enumerate(chain(Bad()))", "zip(chain(Bad()), [1, 2])",
        "zip(chain(Bad()), [1, 2], strict=True)",
        "islice(chain(Bad()), 5)", "tee(chain(Bad()))[0]", "groupby(chain(Bad()))",
        "accumulate(chain(Bad()))", "cycle(chain(Bad()))", "pairwise(chain(Bad()))",
        "batched(chain(Bad()), 2)", "zip_longest(chain(Bad()), [1, 2], fillvalue=-1)",
        "map(fail, [1, 2])", "filter(fail_predicate, [1, 2])",
        "takewhile(fail_predicate, [1, 2])", "groupby([1, 2], fail)",
        "accumulate([1, 2, 3], fail_sum)",
        "batched(chain([1], Bad()), 2)", "cycle(chain([1], Bad()))",
        "tee(chain([1], Bad()))[0]", "groupby(chain([1], Bad()))",
        "iter(item, Item())",
    ]
    source = dedent('''
        from collections.abc import Iterator
        from itertools import (accumulate, batched, chain, compress, cycle, dropwhile,
                               filterfalse, groupby, islice, pairwise, takewhile, tee, zip_longest)
        from pyjs.native import gc_collect, gc_set_threshold

        class Done(StopIteration):
            pass
        class Bad:
            def __iter__(self) -> Iterator[int]:
                gc_collect()
                raise Done("acquire")
        def identity(value: int) -> int:
            return value
        def positive(value: int) -> bool:
            return value > 0
        def fail(value: int) -> int:
            raise Done("callback")
        def fail_predicate(value: int) -> bool:
            raise Done("predicate")
        def fail_sum(left: int, right: int) -> int:
            raise Done("sum")
        class Item:
            def __eq__(self, other: "Item") -> bool:
                raise Done("equality")
        def item() -> Item:
            return Item()
    ''')
    for index, expression in enumerate(expressions):
        source += dedent(f'''
            def check_{index}() -> str:
                cursor = {expression}
                result = ""
                for attempt in range(3):
                    gc_collect()
                    try:
                        next(cursor)
                        result += "yield|"
                    except Done as error:
                        result += "Done:" + str(error) + "|"
                    except StopIteration as error:
                        result += "Stop:" + str(error) + "|"
                    except ValueError as error:
                        result += "Value:" + str(error) + "|"
                return result + ";"
        ''')
    source += "\ndef main() -> str:\n    gc_set_threshold(1)\n    return "
    source += " + ".join(f"check_{index}()" for index in range(len(expressions))) + "\n"
    LLVM().assert_matches_python(source, optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("behavior", ["fail", "resume", "drain", "swallow_empty", "swallow_nonempty",
                                      "stop_default", "stop_bare"])
def test_chain_reentrant_acquisition_selects_next_input(optimize, nested, behavior):
    expression = "chain.from_iterable([first, second, last])" if nested else "chain(first, second, last)"
    comparison = LLVM().assert_matches_python(dedent(f'''
        from collections.abc import Iterator
        from itertools import chain
        from pyjs.native import gc_collect, gc_set_threshold

        class Done(StopIteration):
            pass

        class Values:
            def __init__(self, kind: int, box: list[Iterator[int]], events: list[int]):
                self.kind = kind
                self.box = box
                self.events = events
                self.calls = 0

            def __iter__(self) -> Iterator[int]:
                self.calls += 1
                self.events.append(self.kind * 100 + self.calls)
                gc_collect()
                if self.kind == 0:
                    # Bound the regression: the old direct chain repeatedly
                    # acquired this same input during reentrant next().
                    if self.calls > 2:
                        raise RuntimeError("repeated acquisition")
                    try:
                        if {behavior == 'stop_bare'}:
                            self.events.append(next(self.box[0]))
                        else:
                            self.events.append(next(self.box[0], -1))
                    except ValueError:
                        self.events.append(-9)
                    except StopIteration:
                        self.events.append(-8)
                    if {behavior == 'drain'}:
                        self.events.append(next(self.box[0], -1))
                        self.events.append(next(self.box[0], -1))
                    if {behavior == 'fail'}:
                        raise Done("acquire")
                    if {behavior in ('swallow_empty', 'stop_default', 'stop_bare')}:
                        return iter(range(0))
                    return iter([10, 11])
                if self.kind == 1 and {behavior in ('swallow_empty', 'swallow_nonempty')}:
                    raise ValueError("inner acquisition")
                if self.kind == 1 and {behavior in ('stop_default', 'stop_bare')}:
                    raise Done("inner stop")
                return iter([self.kind])

        def main() -> str:
            gc_set_threshold(1)
            box: list[Iterator[int]] = []
            events: list[int] = []
            first = Values(0, box, events)
            second = Values(1, box, events)
            last = Values(2, box, events)
            cursor = {expression}
            box.append(cursor)
            result = ""
            try:
                result += str(next(cursor))
            except Done as error:
                result += "Done:" + str(error)
            except Exception as error:
                result += "Other:" + str(error)
            for index in range(5):
                gc_collect()
                result += "," + str(next(cursor, -1))
            for event in events:
                result += ":" + str(event)
            return result + ":calls=" + str(first.calls) + str(second.calls) + str(last.calls)
    '''), optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", ["chain(values, values)", "chain.from_iterable([values, values])"])
def test_chain_acquisition_failure_is_terminal_but_active_cursor_errors_retry(optimize, expression):
    LLVM().assert_matches_python(dedent(f'''
        from collections.abc import Iterator
        from itertools import chain
        from pyjs.native import gc_collect, gc_set_threshold

        class Values:
            def __init__(self):
                self.fail = True
                self.calls = 0
            def __iter__(self) -> Iterator[int]:
                self.calls += 1
                gc_collect()
                if self.fail:
                    self.fail = False
                    raise ValueError("acquire")
                return iter([1, 2])

        class Source:
            def __init__(self):
                self.calls = 0
            def pull(self) -> int:
                self.calls += 1
                gc_collect()
                if self.calls == 1:
                    raise ValueError("advance")
                return self.calls

        def main() -> str:
            gc_set_threshold(1)
            values = Values()
            cursor = {expression}
            try:
                next(cursor)
            except ValueError as error:
                assert str(error) == "acquire"
            gc_collect()
            assert next(cursor, -1) == -1
            assert next(cursor, -1) == -1
            assert values.calls == 1
            source = Source()
            active = chain(iter(source.pull, 4))
            try:
                next(active)
            except ValueError as error:
                assert str(error) == "advance"
            gc_collect()
            return str(next(active, -1)) + ":" + str(next(active, -1)) + ":" + str(next(active, -1))
    '''), optimize=optimize, sanitizers=("address", "undefined"))
