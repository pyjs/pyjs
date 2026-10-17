import pytest

from pyjs.analysis.analyzer import _ACTIVE_ENVIRONMENT
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case
from tests.native.iterator_view_support import generator_view

STRUCTURAL_SEND = '''
from collections.abc import Generator, Iterable, Iterator
from pyjs.native import gc_collect, gc_set_threshold

class Cursor:
    def __init__(self):
        self.n = 0
    def __iter__(self) -> "Cursor":
        gc_collect()
        return self
    def __next__(self) -> int:
        self.n += 1
        if self.n > 3:
            raise StopIteration()
        return self.n

def original(events: list[int]) -> Generator[int, Iterable[int], None]:
    value = yield 10
    gc_collect()
    if value is None:
        raise ValueError("missing")
    events[0] += 1
    yield sum(value)

def middle(source: Generator[int, Iterable[int], None]) -> Generator[int, Iterator[int], None]:
    return source

def outer(source: Generator[int, Iterator[int], None]) -> Generator[int, Cursor, None]:
    return source
'''


@pytest.mark.parametrize('optimize', [0, 2])
def test_structural_send_views_use_native_type_relations(optimize):
    environment = _ACTIVE_ENVIRONMENT.get()
    result = LLVM().assert_matches_python(STRUCTURAL_SEND + '''
def main() -> str:
    gc_set_threshold(1)
    events = [0]
    raw = original(events)
    view = outer(middle(raw))
    result = [next(view), view.send(Cursor())]
    assert view is raw
    view.close()
    assert events == [1]
    return str(result)
''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr
    assert _ACTIVE_ENVIRONMENT.get() is environment


@pytest.mark.parametrize('optimize', [0, 2])
def test_structural_send_allocation_failure_does_not_resume_source(tmp_path, optimize):
    source = transpile_llvm(STRUCTURAL_SEND + '''
from tests.native.allocation_support import arm
def main() -> int:
    events = [0]
    # Cursor -> Iterator and Iterator -> Iterable each allocate a descriptor.
    # Neither failure may publish input or resume the original generator.
    for denied in (1, 2):
        raw = original(events)
        view = outer(middle(raw))
        item = Cursor()
        assert next(view) == 10
        before = events[0]
        caught = False
        arm(denied)
        try:
            view.send(item)
        except MemoryError:
            caught = True
        arm(0)
        gc_collect()
        if not caught or events[0] != before or item.n != 0:
            return 1
        if view.send(item) != 6 or events[0] != before + 1:
            return 2
        assert view is raw
        view.close()
    return 0
''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stdout and not result.stderr


@pytest.mark.parametrize(('actual', 'expected', 'value'), [
    ('int', 'float', '7'), ('int', 'float | None', '7'),
    ('bool', 'int', 'True'), ('bool', 'int | None', 'True'),
    ('bool', 'float', 'True'), ('bool', 'float | None', 'True'),
    ('int | None', 'float | None', '7'),
    ('bool | None', 'int | None', 'True'), ('bool | None', 'float | None', 'True'),
    ('int | float', 'float', '7'), ('float | int', 'float | None', '7'),
    ('int | float | None', 'float | None', 'None'),
    ('int | bool', 'float', 'True'), ('bool | int', 'int', 'True'),
    ('bool | int', 'int | None', 'True'), ('bool | int | None', 'int | None', 'None'),
    ('bool | float', 'float', 'True'), ('bool | float', 'float | None', 'True'),
])
@pytest.mark.parametrize('slot', ['yield', 'send', 'completion'])
def test_generator_views_require_explicit_numeric_conversion(actual, expected, value, slot):
    source = generator_view(actual, expected, slot=slot)
    environment = _ACTIVE_ENVIRONMENT.get()
    with pytest.raises(LLVMUnsupported, match='iterator views require an explicit numeric conversion'):
        transpile_llvm(source + f'''
def main() -> int:
    next(view(values({value})))
    return 0
''')
    assert _ACTIVE_ENVIRONMENT.get() is environment


@pytest.mark.parametrize('optimize', [0, 2])
@pytest.mark.parametrize(('actual', 'expected', 'value'), [
    ('int', 'int | None', '7'), ('int', 'int | float', '7'),
    ('int', 'int | float | None', '7'), ('int', 'object', '7'),
    ('bool', 'bool | None', 'True'), ('bool', 'bool | float', 'True'),
    ('None', 'float | None', 'None'), ('None', 'bool | None', 'None'),
    ('int | float', 'float | int | None', '7'),
    ('int | float', 'float | int | None', '2.5'),
    ('bool | int', 'int | float', 'True'), ('bool | float', 'object', 'True'),
    ('int | float | None', 'object', 'None'),
])
def test_completion_views_preserve_original_numeric_kind(optimize, actual, expected, value):
    source = generator_view(actual, expected, slot='completion')
    result = LLVM().assert_matches_python(source + f'''
def delegate(source: Generator[int, None, {expected}]) -> Generator[int, None, str]:
    value = yield from source
    return repr(value)
def main() -> str:
    closed = view(values({value}))
    assert next(closed) == 1
    completion = closed.close()
    result = delegate(view(values({value})))
    assert next(result) == 1
    try:
        next(result)
    except StopIteration as error:
        return repr((completion, error.value))
    return "not completed"
''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
@pytest.mark.parametrize('slot', ['yield', 'send'])
def test_optional_union_view_transport_preserves_values(optimize, slot):
    source = generator_view('bool | None', 'int | float | None', slot=slot)
    operation = ('    return repr(next(value))\n' if slot == 'yield' else '''
    next(value)
    try:
        value.send(payload)
    except StopIteration as error:
        return str(error.value)
    return "not completed"
''')
    source += ('def run(payload: bool | None) -> str:\n'
               '    value = view(values(payload))\n' + operation + '''
def main() -> str:
    return run(True) + "|" + run(None)
''')
    result = LLVM().assert_matches_python(source, optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_chained_generator_views_share_state_and_convert_both_directions(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator, Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def values(events: list[int]) -> Generator[int, object, None]:
            value = yield 1
            while True:
                gc_collect()
                if isinstance(value, int):
                    events.append(int(value))
                    if value < 0:
                        raise ValueError("negative")
                    value = yield int(value) + 1
                else:
                    events.append(0)
                    value = yield 0

        def union(value: Generator[int, object, None]) -> Generator[int | str, int | str, None]:
            return value

        def boxed(value: Generator[int | str, int | str, None]) -> Generator[object, int, None]:
            return value

        def consume(value: Iterator[object]) -> object:
            return next(value)

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            source = values(events)
            middle = union(source)
            value = boxed(middle)
            assert value is source and id(middle) == id(source)
            try:
                value.send(7)
                assert False
            except TypeError:
                assert events == []
            first = consume(value)
            second = value.send(7)
            third = next(source)
            fourth = middle.send("text")
            fifth = value.send(9)
            try:
                value.send(-1)
                assert False
            except ValueError as error:
                assert str(error) == "negative"
            assert next(value, None) is None and next(source, None) is None
            value.close()
            return repr((first, second, third, fourth, fifth, events))
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_generator_view_close_throw_completion_and_reentry(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        def adapt(source: Generator[str, object, str]) -> Generator[object, int, object]:
            return source

        def values(events: list[str], holders: list[Generator[object, int, object]]) -> Generator[str, object, str]:
            try:
                try:
                    holders[0].send(1)
                    assert False
                except ValueError:
                    events.append("busy")
                yield "started"
                return "normal"
            except ValueError as error:
                gc_collect()
                yield str(error)
                return "thrown"
            except GeneratorExit:
                gc_collect()
                return "closed"
            finally:
                events.append("finally")

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            holders: list[Generator[object, int, object]] = []
            original = values(events, holders)
            view = adapt(original)
            holders.append(view)
            assert next(view) == "started"
            assert view.throw(ValueError("injected")) == "injected"
            try:
                next(view)
                assert False
            except StopIteration as error:
                assert error.value == "thrown"
            assert original.close() is None
            assert id(view) == id(original)
            other = adapt(values(events, holders))
            holders[0] = other
            assert next(other) == "started"
            assert other.close() == "closed"
            assert other.close() is None
            fresh = adapt(values(events, holders))
            try:
                fresh.throw(ValueError("fresh"))
                assert False
            except ValueError as error:
                assert str(error) == "fresh"
            assert next(fresh, None) is None
            fresh.close()
            untouched = adapt(values(events, holders))
            untouched.close()
            assert next(untouched, None) is None
            return repr(events)
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_builtin_iterator_covariance_nullable_storage_and_narrowed_locals(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator, Iterable
        from pyjs.native import gc_collect, gc_set_threshold

        def wide(source: Iterator[int] | None) -> Iterator[object] | None:
            return source

        def reusable(source: Iterator[object]) -> Iterable[object]:
            return source

        def consume(source: Iterator[object]) -> object:
            gc_collect()
            return next(source)

        def main() -> str:
            gc_set_threshold(1)
            original = iter([1, 2, 3, 4])
            view = wide(original)
            if view is None:
                return "missing"
            assert wide(None) is None
            assert id(view) == id(original)
            assert iter(view) is view
            first = consume(view)
            local: Iterator[object] = original
            assert next(local) == 2
            for i in range(5):
                local = original
                gc_collect()
                assert id(local) == id(original)
            iterable = reusable(view)
            assert iterable is original
            return repr((first, list(iterable), next(original, None)))
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_generator_view_portable_yields_and_iterable_send(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator, Iterable, Iterator
        from pyjs import int8, int64
        from pyjs.native import gc_collect, gc_set_threshold

        class Rows:
            def __iter__(self) -> Iterator[int]:
                gc_collect()
                return iter([3, 4])

        def rows() -> Generator[int8, Iterable[int], None]:
            value = yield int8(130)
            gc_collect()
            if value is None:
                raise TypeError("expected rows")
            yield int8(sum(value))

        def narrow(source: Generator[int8, Iterable[int], None]) -> Generator[int8, Rows, None]:
            return source

        def wide() -> Generator[int64, object, None]:
            value = yield int64(2**60 + 1)
            yield int64(7) if value is None else int64(9)

        def empty(source: Generator[int64, object, None]) -> Generator[int64, None, None]:
            return source

        def main() -> str:
            gc_set_threshold(1)
            first = narrow(rows())
            second = empty(wide())
            return repr((int(next(first)), int(first.send(Rows())),
                         int(next(second)), int(second.send(None))))
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_covariant_application_iterator_reacquires_its_real_protocol(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Cursor:
            def __init__(self, events: list[int], value: int):
                self.events = events
                self.value = value

            def __iter__(self) -> Iterator[int]:
                self.events.append(self.value)
                gc_collect()
                return iter([self.value, self.value + 1])

            def __next__(self) -> int:
                self.value += 10
                return self.value

        def handle(source: Cursor) -> Iterator[int]:
            return source

        def widen(source: Iterator[int]) -> Iterator[object]:
            return source

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            original = Cursor(events, 1)
            source = handle(original)
            value = widen(source)
            assert value is original
            assert next(value) == 11
            assert list(value) == [11, 12]
            assert list(value) == [11, 12]
            assert next(source) == 21
            assert list(iter(value)) == [21, 22]
            return repr(events)
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_nested_callable_and_iterator_views_discover_each_others_helpers(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable, Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def rows() -> Iterator[int]:
            yield 7
            yield 9

        def functions() -> Iterator[Callable[[], Iterator[int]]]:
            yield rows

        def wide(source: Iterator[Callable[[], Iterator[int]]]) -> Iterator[Callable[[], Iterator[object]]]:
            return source

        def main() -> str:
            gc_set_threshold(1)
            source = functions()
            view = wide(source)
            callback = next(view)
            gc_collect()
            return repr(list(callback()))
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_nested_partial_conversion_retains_omitted_arity(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Callable, Iterator
        from functools import partial
        def original(value: int = 7) -> int:
            return value
        def callbacks() -> Iterator[Callable[[], object]]:
            yield partial(original)
        def main() -> str:
            direct: Callable[[int], int] = original
            callback = next(callbacks())
            return repr((direct(3), callback()))
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_view_and_send_allocation_failure_preserves_binding_and_suspension(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Generator
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def values(events: list[int]) -> Generator[int, object, None]:
            value = yield 1
            gc_collect()
            events.append(1)
            yield int(value) if isinstance(value, int) else 0

        def narrow(value: Generator[int, object, None]) -> Generator[int, int, None]:
            return value

        def main() -> int:
            events: list[int] = []
            previous = values(events)
            current = narrow(previous)
            source = values(events)
            caught = False
            arm(1)
            try:
                current = narrow(source)
            except MemoryError:
                caught = True
            arm(0)
            gc_collect()
            if not caught or current is not previous:
                return 1
            current = narrow(source)
            if next(current) != 1:
                return 2
            result = -1
            caught = False
            arm(1)
            try:
                result = current.send(7)
            except MemoryError:
                caught = True
            arm(0)
            gc_collect()
            if not caught or result != -1 or events:
                return 3
            if current.send(7) != 7 or events != [1]:
                return 4
            current.close()
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stdout and not result.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_failed_yield_conversion_consumes_one_item_and_close_skips_view_conversion(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Generator, Iterator
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def values(events: list[int]) -> Generator[int | str, None, None]:
            try:
                yield 1
                yield "two"
            except GeneratorExit:
                yield 3
            finally:
                events.append(7)

        def view(source: Generator[int | str, None, None]) -> Generator[object, None, None]:
            return source

        def iterator(source: Generator[int | str, None, None]) -> Iterator[object]:
            return source

        def main() -> int:
            events: list[int] = []
            original = values(events)
            widened = view(original)
            caught = False
            arm(1)
            try:
                next(widened)
            except MemoryError:
                caught = True
            arm(0)
            gc_collect()
            if not caught or next(original) != "two":
                return 1
            caught = False
            # No view boxing should run for the yielded-but-discarded 3.
            arm(1)
            try:
                widened.close()
            except RuntimeError as error:
                caught = str(error) == "generator ignored GeneratorExit"
            arm(0)
            if not caught or next(widened, None) is not None:
                return 2
            other = iterator(values(events))
            if next(other) != 1 or next(other) != "two":
                return 3
            if next(other, None) is not None or events != [7, 7]:
                return 4
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stdout and not result.stderr


def test_aliased_mutable_storage_cannot_reinterpret_its_iterator_items():
    with pytest.raises(LLVMUnsupported, match='stored iterator views require matching'):
        transpile_llvm('''
            from collections.abc import Iterator
            def unsafe(values: list[Iterator[int]]) -> list[Iterator[object]]:
                return values
            def main() -> int:
                unsafe([iter([1])])
                return 0
        ''')


def test_generator_completion_does_not_reinterpret_enclosed_tuple_storage():
    source = generator_view('tuple[int]', 'tuple[object]', slot='completion')
    with pytest.raises(LLVMUnsupported, match='tuple|storage'):
        transpile_llvm(source + '''
def main() -> int:
    view(values((7,)))
    return 0
''')


@pytest.mark.parametrize('optimize', [0, 2])
def test_anonymous_iterator_conversion_reserves_checked_advancement(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from typing import cast
        def main() -> int:
            value = next(cast(Iterator[object], iter([7])))
            return int(value) if isinstance(value, int) else 1
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_generator_application_types_retain_virtual_results_and_completion_identity(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def __init__(self, value: int):
                self.value = value
            def read(self) -> int:
                return self.value

        class Child(Base):
            def read(self) -> int:
                gc_collect()
                return self.value + 1

        def values(result: Child) -> Generator[Child, Base, Child]:
            try:
                value = yield Child(1)
                gc_collect()
                if value is None:
                    raise TypeError("expected a value")
                yield Child(value.read())
            except GeneratorExit:
                return result
            return result

        def adapt(source: Generator[Child, Base, Child]) -> Generator[Base, Child, Base]:
            return source

        def main() -> str:
            gc_set_threshold(1)
            result = Child(9)
            original = values(result)
            view = adapt(original)
            first = next(view).read()
            second = view.send(Child(7)).read()
            completed = view.close()
            assert completed is result
            assert original.close() is None
            return repr((first, second, result.read()))
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_close_result_survives_chained_views_and_ephemeral_source(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        class Result:
            def __init__(self, value: int):
                self.value = value
            def __str__(self) -> str:
                gc_collect()
                return "result:" + str(self.value)

        def child() -> Generator[list[int8], None, Result]:
            result = Result(3)
            try:
                yield [int8(130)]
            finally:
                gc_collect()
                result.value += 1
                return result
        def adapt(source: Generator[list[int8], None, Result]) -> Generator[object, None, Result]:
            return source
        def erase(source: Generator[object, None, Result]) -> Generator[object, None, object]:
            return source
        def started() -> Generator[list[int8], None, Result]:
            source = child()
            next(source)
            return source
        def main() -> str:
            gc_set_threshold(1)
            original = child()
            source = adapt(original)
            next(source)
            value = source.close()
            gc_collect()
            assert value is not None
            result = str(value.value)
            assert original.close() is None
            erased = erase(adapt(child()))
            next(erased)
            other = erased.close()
            gc_collect()
            ephemeral = started().close()
            gc_collect()
            assert ephemeral is not None
            return result + str(other) + str(erased.close()) + str(ephemeral)
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_yield_from_forwards_through_representation_views(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        def original(events: list[int]) -> Generator[int, object, str]:
            try:
                value = yield 1
                gc_collect()
                yield int(value) if isinstance(value, int) else 2
                return "finished"
            except ValueError:
                yield 99
                return "handled"
            finally:
                events.append(7)

        def view(source: Generator[int, object, str]) -> Generator[object, int, object]:
            return source

        def delegate(source: Generator[object, int, object]) -> Generator[object, int, object]:
            result = yield from source
            return result

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            first = delegate(view(original(events)))
            assert next(first) == 1 and first.send(8) == 8
            try:
                next(first)
                assert False
            except StopIteration as error:
                assert error.value == "finished"
            second = delegate(view(original(events)))
            assert next(second) == 1
            assert second.throw(ValueError("injected")) == 99
            try:
                next(second)
                assert False
            except StopIteration as error:
                assert error.value == "handled"
            source = original(events)
            third = delegate(view(source))
            assert next(third) == 1
            third.close()
            assert next(source, None) is None
            return repr(events)
    ''', optimize=optimize, sanitizers=('address', 'undefined'))
    assert not result.native.stderr
