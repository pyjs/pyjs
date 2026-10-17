import pytest

from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.errors import LLVMUnsupported
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("entry", ["Factory()", "make()"])
def test_cursor_reacquisition_dependency_closure(tmp_path, optimize, entry):
    source = f'''
        from typing import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Other:
            def __iter__(self) -> "Factory":
                gc_collect()
                return Factory()

            def __next__(self) -> int:
                raise StopIteration()

        class Cursor:
            def __init__(self):
                self.done = False

            def __iter__(self) -> Other:
                gc_collect()
                return Other()

            def __next__(self) -> int:
                gc_collect()
                if self.done:
                    raise StopIteration()
                self.done = True
                return 7

        class Factory:
            def __iter__(self) -> Cursor:
                gc_collect()
                return Cursor()

            def __next__(self) -> int:
                return -1

        def make() -> Iterator[int]:
            return Factory()

        def main() -> str:
            gc_set_threshold(1)
            return str(list({entry}))
    '''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        for name in ("Factory", "Cursor", "Other"):
            cursor = analysis.entry_point.container.search(name)
            for method in ("__iter__", "__next__"):
                assert cursor.find_attrs(method) in analysis.entry_point.compilation_objects
    result = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                         sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("item", ["int", "object"])
@pytest.mark.parametrize("annotation, literal", [
    ("list[Iterator[int]]", "[Cursor(), Cursor()]"),
    ("tuple[Iterator[int], Iterator[int]]", "(Cursor(), Cursor())"),
    ("list[list[Iterator[int]]]", "[[Cursor(), Cursor()], [Cursor()]]"),
])
def test_cursor_literal_conversions_survive_later_sibling_gc(tmp_path, optimize, item, annotation, literal):
    annotation = annotation.replace("Iterator[int]", f"Iterator[{item}]")
    consume = "views[0]" if annotation.startswith("list[list") else "views"
    result = LLVM().assert_matches_python(f'''
        from typing import Iterator, Self
        from pyjs.native import gc_collect, gc_set_threshold

        class Cursor:
            def __init__(self):
                gc_collect()
                self.index = 0

            def __iter__(self) -> Self:
                gc_collect()
                return self

            def __next__(self) -> int:
                gc_collect()
                self.index += 1
                if self.index > 2:
                    raise StopIteration()
                return self.index

        def main() -> str:
            gc_set_threshold(1)
            views: {annotation} = {literal}
            gc_collect()
            return str((next({consume}[0]), list({consume}[1])))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_expression_acquires_only_outer_source_at_creation(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Self
        from pyjs.native import gc_collect, gc_set_threshold

        class Once:
            def __init__(self, events: list[int], label: int):
                self.events = events
                self.label = label
                self.acquired = False
                self.index = 0

            def __iter__(self) -> Self:
                if self.acquired:
                    raise RuntimeError("acquired twice")
                self.acquired = True
                self.events.append(self.label)
                gc_collect()
                return self

            def __next__(self) -> int:
                self.index += 1
                gc_collect()
                if self.index > 2:
                    raise StopIteration()
                return self.index

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            values = (x * y for x in Once(events, 10) for y in Once(events, x))
            assert events == [10]
            first = next(values)
            assert events == [10, 1]
            rest = list(values)
            assert events == [10, 1, 2]
            short = any(x > 0 for x in Once(events, 20))
            total = sum(x * 2 for x in Once(events, 30))
            return str((first, rest, short, total, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_application_cursor_protocol_and_recovery(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Self
        from pyjs.native import gc_collect, gc_set_threshold

        class Done(StopIteration):
            pass

        class Cursor:
            def __init__(self, events: list[int]):
                self.index = 0
                self.events = events

            def __iter__(self) -> Self:
                self.events.append(10)
                gc_collect()
                return self

            def __next__(self) -> int:
                self.index += 1
                self.events.append(self.index)
                gc_collect()
                if self.index == 2:
                    raise ValueError("retry")
                if self.index > 4:
                    raise Done("finished")
                return self.index

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            cursor = Cursor(events)
            values = [next(cursor)]
            same = iter(cursor) is cursor
            try:
                next(cursor)
            except ValueError:
                values.append(-2)
            values.extend(list(cursor))
            values.append(next(cursor, -1))
            try:
                next(cursor)
            except Done as error:
                events.append(20)
                if str(error) != "finished":
                    return "wrong error"
            return str((same, values, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["Self", "Iterator[int]"])
def test_application_cursor_aliases_and_virtual_dispatch(tmp_path, optimize, annotation):
    result = LLVM().assert_matches_python(f'''
        from typing import Self
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Cursor:
            def __init__(self, events: list[int]):
                self.index = 0
                self.events = events

            def __iter__(self) -> {annotation}:
                self.events.append(10)
                gc_collect()
                return self

            def __next__(self) -> int:
                self.index += 1
                gc_collect()
                if self.index > 3:
                    raise StopIteration("done")
                return self.index

        class Doubled(Cursor):
            def __next__(self) -> int:
                return super().__next__() * 2

        class Values:
            def __init__(self, events: list[int]):
                self.events = events

            def __iter__(self) -> Cursor:
                gc_collect()
                return Doubled(self.events)

        def forward(value: Cursor) -> Iterator[int]:
            return value

        def collect(value: Iterator[int]) -> list[int]:
            return list(value)

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            cursor = Doubled(events)
            alias = forward(cursor)
            first = next(alias)
            second = next(cursor)
            same = iter(alias) is cursor and alias is cursor
            rest = collect(alias)
            values = list(Values(events))
            return str((first, second, same, rest, values, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_represented_cursor_in_nested_interface_storage(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Self
        from collections.abc import Iterator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        class Cursor:
            def __init__(self):
                self.index = 0

            def __iter__(self) -> Self:
                gc_collect()
                return self

            def __next__(self) -> int8:
                self.index += 1
                gc_collect()
                if self.index > 3:
                    raise StopIteration()
                return int8(self.index + 126)

        def boxed() -> list[Iterator[int8]]:
            return [Cursor()]

        def main() -> str:
            gc_set_threshold(1)
            values = boxed()
            gc_collect()
            cursor = values.pop()
            first = next(cursor)
            rest = list(cursor)
            return str((int(first), rest, int(next(cursor, int8(-1)))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_cursor_roots_receiver_during_default_and_preserves_iter_errors(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Self
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int):
                self.value = value

        class Cursor:
            def __init__(self, events: list[int]):
                self.events = events
                self.index = 0

            def __iter__(self) -> Self:
                self.events.append(10)
                gc_collect()
                raise ValueError("iter")

            def __next__(self) -> Box:
                self.index += 1
                self.events.append(3)
                gc_collect()
                if self.index > 2:
                    raise StopIteration()
                return Box(self.index)

        def make(events: list[int]) -> Cursor:
            events.append(1)
            return Cursor(events)

        def fallback(events: list[int]) -> Box:
            events.append(2)
            gc_collect()
            return Box(-1)

        def as_iterator(cursor: Cursor) -> Iterator[Box]:
            return cursor

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            first = next(make(events), fallback(events))
            cursor = make(events)
            alias = as_iterator(cursor)
            caught = False
            try:
                iter(alias)
            except ValueError:
                caught = True
            values = [next(alias).value, next(cursor).value]
            values.append(next(alias, fallback(events)).value)
            gc_collect()
            return str((first.value, caught, values, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_cursor_consumers_acquire_once_and_can_resume_after_stop(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Self
        from collections.abc import Iterator
        from itertools import groupby
        from pyjs.native import gc_collect, gc_set_threshold

        class Cursor:
            def __init__(self, events: list[int]):
                self.events = events
                self.index = 0

            def __iter__(self) -> Self:
                self.events.append(10)
                gc_collect()
                return self

            def __next__(self) -> int:
                self.index += 1
                gc_collect()
                if self.index == 3 or self.index > 5:
                    raise StopIteration()
                return self.index

        def consume(cursor: Iterator[int]) -> list[int]:
            return list(cursor)

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            cursor = Cursor(events)
            first = consume(cursor)
            second = list(cursor)
            third = next(cursor, -1)
            reduced = sum(Cursor(events))
            member = 1 in Cursor(events)
            overlap = {1, 2}.intersection(Cursor(events))
            disjoint = {0}.isdisjoint(Cursor(events))
            superset = {1, 2}.issuperset(Cursor(events))
            pairs = list(zip(Cursor(events), [7, 8, 9]))
            direct = [value for value in Cursor(events)]
            groups = groupby([1, 1, 2])
            key, group = next(groups)
            alias = iter(group)
            return str((first, second, third, reduced, member, overlap, disjoint,
                        superset, pairs, direct, key, alias is group, list(alias), events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_acquisition_replaces_interface_cursor_and_roots_sibling_results(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Self
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Cursor:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events
                self.done = False

            def __iter__(self) -> Self:
                self.events.append(self.value)
                gc_collect()
                return self

            def __next__(self) -> int:
                gc_collect()
                if self.done:
                    raise StopIteration()
                self.done = True
                return self.value

        class Factory:
            def __init__(self, value: int, events: list[int]):
                self.value = value
                self.events = events

            def __iter__(self) -> Cursor:
                self.events.append(-self.value)
                gc_collect()
                return Cursor(self.value, self.events)

            def __next__(self) -> int:
                return -1

        def make(value: int, events: list[int]) -> Iterator[int]:
            return Factory(value, events)

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            first = make(1, events)
            second = make(2, events)
            pairs = list(zip(first, second))
            cursor = iter(Factory(3, events))
            values = list(cursor)
            return str((pairs, values, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_cursor_interface_keeps_storage_and_identity(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Self
        from collections.abc import Iterator

        class Cursor:
            def __iter__(self) -> Self:
                return self

            def __next__(self) -> int:
                return 7

        def forward(cursor: Cursor | None) -> Iterator[int] | None:
            return cursor

        def main() -> str:
            raw = Cursor()
            alias = forward(raw)
            same = alias is raw
            if alias is not None:
                return str((same, next(alias), forward(None) is None))
            return "missing"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("annotation, expression, message", [
    ("object", "iter(Cursor())", "iterator handles cannot yet be erased to object"),
    ("Iterator[int] | str", "Cursor()", "union member Iterator.*no concrete runtime tag"),
    ("list[Iterator[int]]", "rows", "collection views require matching concrete item storage"),
])
def test_cursor_storage_boundaries_are_explicit(annotation, expression, message):
    with pytest.raises(LLVMUnsupported, match=message):
        transpile_llvm(f'''
            from collections.abc import Iterator
            from typing import Self

            class Cursor:
                def __iter__(self) -> Self:
                    return self

                def __next__(self) -> int:
                    return 1

            def main() -> {annotation}:
                rows = [Cursor()]
                return {expression}
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterable_item_type_comes_from_acquired_cursor_not_own_next(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator

        class Values:
            def __iter__(self) -> Iterator[str]:
                return iter(["a", "b"])

            def __next__(self) -> int:
                return 7

        def main() -> str:
            return str(list(Values()))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("next_type, iter_type, value", [
    ("int", "str", '"a"'),
    ("int8", "int16", "int16(1)"),
])
def test_cursor_reacquisition_cannot_change_item_layout(next_type, iter_type, value):
    with pytest.raises(LLVMUnsupported, match="matching __iter__ and __next__ item layouts"):
        transpile_llvm(f'''
            from collections.abc import Iterator
            from pyjs import int8, int16

            class Cursor:
                def __iter__(self) -> Iterator[{iter_type}]:
                    return iter([{value}])

                def __next__(self) -> {next_type}:
                    return {next_type}(7)

            def main() -> int:
                return int(next(Cursor()))
        ''')


def test_next_only_returned_cursor_is_diagnosed_before_null_callback():
    with pytest.raises(LLVMUnsupported, match="cursors require a reached __iter__ method"):
        transpile_llvm('''
            class Cursor:
                def __next__(self) -> int:
                    return 1

            class Values:
                def __iter__(self) -> Cursor:
                    return Cursor()

            def main() -> int:
                return next(iter(Values()))
        ''')


def test_invalid_reacquisition_result_is_diagnosed_before_adapter_emission():
    with pytest.raises(LLVMUnsupported, match="__iter__ returning an iterator"):
        transpile_llvm('''
            class Cursor:
                def __iter__(self) -> int:
                    return 1
                def __next__(self) -> int:
                    return 7

            def main() -> int:
                return next(Cursor())
        ''')


def test_union_returned_cursor_has_explicit_adapter_boundary():
    with pytest.raises(LLVMUnsupported, match="application cursors require a reached __iter__ method"):
        transpile_llvm('''
            from typing import Self

            class First:
                def __iter__(self) -> Self:
                    return self
                def __next__(self) -> int:
                    return 1

            class Second:
                def __iter__(self) -> Self:
                    return self
                def __next__(self) -> int:
                    return 2

            class Values:
                def __init__(self, flag: bool):
                    self.flag = flag
                def __iter__(self) -> First | Second:
                    return First() if self.flag else Second()

            def main() -> int:
                return next(iter(Values(True)))
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_explicit_next_method_does_not_require_iteration_protocol(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        class Value:
            def __next__(self) -> int:
                return 7

        def main() -> int:
            return Value().__next__()
    ''', directory=tmp_path, optimize=optimize)
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_cursor_interface_fields_and_mutations_share_represented_state(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Self
        from collections.abc import Iterator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        class Cursor:
            def __init__(self):
                self.index = 0

            def __iter__(self) -> Self:
                return self

            def __next__(self) -> int8:
                self.index += 1
                gc_collect()
                return int8(125 + self.index)

        class Key:
            def __hash__(self) -> int:
                gc_collect()
                return 1

            def __eq__(self, other: "Key") -> bool:
                gc_collect()
                return True

        class Holder:
            def __init__(self, cursor: Cursor):
                self.value: Iterator[int8] = cursor
                self.values: list[Iterator[int8]] = []
                self.values.append(cursor)
                self.mapping: dict[Key, Iterator[int8]] = {}
                self.mapping[Key()] = cursor
                self.pair: tuple[Iterator[int8], int] = (cursor, 0)

        def main() -> str:
            gc_set_threshold(1)
            cursor = Cursor()
            holder = Holder(cursor)
            gc_collect()
            first = next(holder.value)
            second = next(holder.values.pop())
            third = next(holder.mapping[Key()])
            fourth = next(holder.pair[0])
            return str((int(first), int(second), int(third), int(fourth), holder.value is cursor))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", ["iter(Cursor(values))", "list(Cursor(values))"])
def test_cursor_allocation_failure_recovers(tmp_path, optimize, expression):
    source = f'''
        from typing import Self
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm

        class Cursor:
            def __init__(self, values: list[int]):
                self.values = values
                self.index = 0

            def __iter__(self) -> Self:
                gc_collect()
                return self

            def __next__(self) -> int:
                gc_collect()
                if self.index == len(self.values):
                    raise StopIteration()
                value = self.values[self.index]
                self.index += 1
                return value

        def main() -> int:
            gc_set_threshold(1)
            values = [1, 2, 3]
            failures = 0
            for attempt in range(1, 100):
                complete = False
                try:
                    arm(attempt)
                    result = {expression}
                    arm(0)
                    assert list(result) == values
                    complete = True
                except MemoryError:
                    arm(0)
                    failures += 1
                finally:
                    arm(0)
                gc_collect()
                assert values == [1, 2, 3]
                assert list({expression}) == values
                if complete:
                    return 0 if failures else 1
            return 2
    '''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=True, optimize=optimize)
