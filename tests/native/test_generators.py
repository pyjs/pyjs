import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError
from tests.backend_semantics import GENERATOR_CONTRACT


def test_shared_generator_contract():
    result = LLVM().assert_matches_python(GENERATOR_CONTRACT.source)
    assert result.native.returncode == 0, GENERATOR_CONTRACT.failure(result.native.returncode)


@pytest.mark.parametrize("optimize", [0, 2])
def test_inferred_object_yields_box_concrete_payloads_without_losing_identity(optimize):
    comparison = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __repr__(self) -> str:
                gc_collect()
                return "Box()"

        def erased(value: str) -> object:
            return value

        def values():
            yield "discard"
            yield b"bytes"
            yield [1, 2]
            yield (3, 4)
            yield {"key": 5}
            yield {6}
            yield 7
            yield 1.5
            yield True
            yield None
            yield Box()
            yield erased("ready")

        def main() -> str:
            gc_set_threshold(1)
            result: list[object] = []
            types: list[str] = []
            source = values()
            for item in source:
                gc_collect()
                types.append(str(isinstance(item, str)) + str(isinstance(item, int)))
                result.append(item)
            source.close()
            gc_collect()
            return repr(result) + repr(types)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_declared_yields_retain_boxed_values_iterable_views_and_explicit_numbers(tmp_path, optimize):
    # Preserve the old declared-yield scenario, with explicit float conversion:
    # a declared result domain does not implicitly cast a yielded Python int.
    # A float sum start also makes the empty iterator result honor that domain.
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Generator, Iterable, Iterator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: int):
                self.value = value

        def objects() -> Generator[object, None, None]:
            yield 1
            yield "café"
            yield int(int8(130))
            yield [2, 3]
            yield Box(4)

        def rows() -> Generator[Iterable[int], None, None]:
            yield [1, 2]
            gc_collect()
            yield range(3, 5)

        def floats() -> Generator[float, None, None]:
            yield float(1)
            yield 2.5

        def consume(value: Iterator[float]) -> float:
            return sum(value, 0.0)

        def main() -> str:
            gc_set_threshold(1)
            source = objects()
            assert next(source) == 1
            gc_collect()
            assert next(source) == "café"
            assert next(source) == -126
            assert next(source) == [2, 3]
            item = next(source)
            gc_collect()
            assert isinstance(item, Box)
            assert item.value == 4
            assert next(source, None) is None
            result: list[int] = []
            for row in rows():
                gc_collect()
                result.extend(row)
            assert result == [1, 2, 3, 4]
            assert list(floats()) == [1.0, 2.5]
            assert consume(floats()) == 3.5
            empty: list[float] = []
            assert consume(iter(empty)) == 0.0
            return repr(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_functions_suspend_loops_and_keep_independent_frames(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def sequence(events: list[int], start: int) -> Iterator[int]:
            events.append(start)
            value = start
            while value < start + 3:
                yield value
                value += 1
            for value in range(3):
                if value == 1:
                    continue
                yield value + start + 10
            events.append(100)

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            first = sequence(events, 1)
            second = sequence(events, 4)
            assert events == []
            assert next(first) == 1 and next(second) == 4
            gc_collect()
            assert next(first) == 2
            assert list(second) == [5, 6, 14, 16]
            assert list(first) == [3, 11, 13]
            assert next(first, -1) == -1
            assert events == [1, 4, 100, 100]
            return "passed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_expressions_are_lazy_with_nested_loops_and_filters(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        def record(events: list[int], value: int) -> int:
            events.append(value)
            gc_collect()
            return value

        def main() -> str:
            events: list[int] = []
            values = [1, 2, 3]
            cursor = (record(events, a * 10 + b) for a in values if a > 1
                      for b in range(a) if b != 1)
            assert events == []
            assert next(cursor) == 20
            values.append(4)
            gc_collect()
            assert list(cursor) == [30, 32, 40, 42, 43]
            assert events == [20, 30, 32, 40, 42, 43]
            return ":".join(str(value) for value in events)
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_cells_outlive_frames_and_keep_numeric_representations(optimize, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    LLVM().assert_matches_python('''
        from collections.abc import Iterator, Callable
        from pyjs import int8, float32
        from pyjs.native import gc_collect, gc_set_threshold

        def callbacks(offset: int8) -> Iterator[Callable[[int8], int8]]:
            for value in [int8(1), int8(2), int8(3)]:
                yield lambda extra: value + offset + extra

        def expressions() -> Iterator[Callable[[int8], int8]]:
            return (lambda value: value + offset for offset in [int8(1), int8(2)])

        def floats(value: float32) -> Iterator[float32]:
            yield value
            yield value + float32(1.0)

        def main() -> int:
            gc_set_threshold(1)
            first = callbacks(int8(1))
            a = next(first)
            assert a(int8(0)) == int8(2)
            b = next(first)
            gc_collect()
            assert a(int8(0)) == int8(3) and b(int8(0)) == int8(3)
            rest = list(first)
            gc_collect()
            assert a(int8(127)) == int8(-125)
            assert rest[0](int8(0)) == int8(4)
            values = list(expressions())
            assert values[0](int8(127)) == int8(-127)
            assert list(floats(float32(16777216.0))) == [float32(16777216.0), float32(16777216.0)]
            return int(a(int8(1)))
    ''', optimize=optimize, sanitizers=("address",))


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_errors_close_frames_and_translate_escaped_stopiteration(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect

        class End(StopIteration):
            pass

        def failure(value: int) -> Iterator[int]:
            yield 1
            if value == 0:
                raise ValueError("ordinary failure")
            raise End("not normal exhaustion")

        def checked(value: int) -> int:
            if value == 2:
                raise StopIteration("callback")
            return value

        def main() -> str:
            cursor = failure(0)
            assert next(cursor) == 1
            try:
                next(cursor)
            except ValueError as error:
                assert str(error) == "ordinary failure"
            else:
                assert False
            gc_collect()
            assert next(cursor, -1) == -1
            second = failure(1)
            assert next(second) == 1
            try:
                next(second)
            except RuntimeError as error:
                assert str(error) == "generator raised StopIteration"
            else:
                assert False
            assert next(second, -1) == -1
            third = (checked(value) for value in [1, 2, 3])
            assert next(third) == 1
            try:
                next(third)
            except RuntimeError as error:
                assert str(error) == "generator raised StopIteration"
            else:
                assert False
            assert next(third, -1) == -1
            return "closed"
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_reentrancy_is_rejected_without_closing_the_active_frame(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def probe(cursors: list[Iterator[int]], catch: bool) -> int:
            gc_collect()
            if catch:
                try:
                    return next(cursors[0])
                except ValueError as error:
                    assert str(error) == "generator already executing"
                    return 7
            return next(cursors[0])

        def produce(cursors: list[Iterator[int]], catch: bool) -> Iterator[int]:
            yield probe(cursors, catch)
            yield 9

        def main() -> int:
            gc_set_threshold(1)
            cursors: list[Iterator[int]] = []
            current = produce(cursors, True)
            cursors.append(current)
            assert list(current) == [7, 9]
            failed = produce(cursors, False)
            cursors[0] = failed
            try:
                next(failed)
            except ValueError:
                pass
            else:
                assert False
            assert next(failed, -1) == -1
            return 0
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_expression_creates_only_the_outer_iterator_immediately(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator

        def delayed(values: dict[int, int]) -> Iterator[int]:
            for value in values:
                yield value

        def record(events: list[int], value: int) -> list[int]:
            events.append(value)
            return [value, value + 1]

        def main() -> int:
            values = {1: 1}
            immediate = (value for value in values)
            later = delayed(values)
            values[2] = 2
            try:
                next(immediate)
            except RuntimeError:
                pass
            else:
                assert False
            assert next(immediate, -1) == -1
            assert list(later) == [1, 2]
            events: list[int] = []
            current = (a + b for a in record(events, 1) for b in record(events, a + 10))
            assert events == [1]
            assert next(current) == 12 and events == [1, 11]
            assert list(current) == [13, 14, 15]
            assert events == [1, 11, 12]
            return 0
    ''', optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_method_calls_defaults_and_argument_expansion(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator, Callable

        class Values:
            def __init__(self, offset: int):
                self.offset = offset

            def produce(self, start: int = 1, *, stop: int = 3) -> Iterator[int]:
                for value in range(start, stop):
                    yield value + self.offset

        class Other(Values):
            def produce(self, start: int = 1, *, stop: int = 3) -> Iterator[int]:
                yield self.offset
                for value in super().produce(start, stop=stop):
                    yield value

        def packed(*values: int, scale: int = 2, **extra: int) -> Iterator[int]:
            for value in values:
                yield value * scale
            for value in extra.values():
                yield value

        def constant(value: int) -> Iterator[int]:
            yield value

        def main() -> int:
            value: Values = Other(10)
            assert list(value.produce(stop=4)) == [10, 11, 12, 13]
            assert list(packed(*[1, 2], **{"scale": 3, "other": 9})) == [3, 6, 9]
            callback: Callable[[int], Iterator[int]] = constant
            return next(callback(7))
    ''', optimize=optimize)


def test_generator_untyped_receive_unpacking_has_a_diagnostic():
    with pytest.raises((CompilationError, LLVMUnsupported),
                       match="native unpacking requires a statically typed tuple or list"):
        transpile_llvm("from collections.abc import Iterator\n"
                       "def values() -> Iterator[int]:\n    left, right = yield 1\n"
                       "def main() -> int:\n    values()\n    return 0\n")


@pytest.mark.parametrize("optimize", [0, 2])
def test_builtin_iterator_delegation_resumes_and_stays_exhausted(optimize):
    # This used to be a negative test before iterator delegation was ported.
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect
        def values() -> Iterator[int]:
            yield from iter([1])
            gc_collect()
            yield 2
        def main() -> str:
            cursor = values()
            first = next(cursor)
            gc_collect()
            return repr((first, list(cursor), next(cursor, -1), next(cursor, -2)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_loops_branches_early_return_and_empty_body(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect

        def values(limit: int) -> Iterator[int]:
            for index, (left, right) in enumerate([(1, 2), (3, 4)]):
                if index >= limit:
                    break
                yield left if index == 0 else right
            else:
                yield 10
            value = 0
            while value < limit:
                yield value
                value += 1
                if value == 2:
                    return
            else:
                yield 20

        def empty(enabled: bool) -> Iterator[int]:
            if enabled:
                yield 1

        def frameless() -> Iterator[int]:
            yield 2
            yield 3

        def main() -> int:
            assert list(values(0)) == [20]
            assert list(values(1)) == [1, 0, 20]
            assert list(values(2)) == [1, 4, 10, 0, 1]
            cursor = empty(False)
            gc_collect()
            assert next(cursor, -1) == -1
            assert next(cursor, -1) == -1
            assert list(frameless()) == [2, 3]
            return sum(values(2))
    ''', optimize=optimize)


def test_generator_unbound_locals_and_forward_cells_are_checked():
    LLVM().assert_matches_python('''
        from collections.abc import Iterator

        def values(enabled: bool) -> Iterator[int]:
            if enabled:
                value = 5
            yield 1
            yield value

        def main() -> int:
            cursor = values(False)
            assert next(cursor) == 1
            try:
                next(cursor)
            except UnboundLocalError:
                pass
            else:
                assert False
            assert next(cursor, -1) == -1
            later = 100
            forward = (left for left in [1] if later for later in [2])
            try:
                next(forward)
            except UnboundLocalError:
                pass
            else:
                assert False
            assert next(forward, -1) == -1
            return sum(values(True))
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_temporary_collection_sources_remain_traced_between_yields(optimize, monkeypatch):
    monkeypatch.setenv("ASAN_OPTIONS", "symbolize=0:detect_leaks=0")
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def sources() -> Iterator[str]:
            for value in ["a" + str(1), "b" + str(2)]:
                yield value
            for key, value in {"c" + str(3): "d" + str(4)}.items():
                yield key + value
            for value in ("e" + str(5), "f" + str(6)):
                yield value
            for value in "é" + str(7):
                yield value

        def main() -> str:
            gc_set_threshold(1)
            cursor = sources()
            result = ""
            for value in cursor:
                gc_collect()
                result += value
            return result
    ''', optimize=optimize, sanitizers=("address",))


def test_lazy_rows_render_the_same_dom_without_an_intermediate_list():
    LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from pyjs.web.dom import Element
        from pyjs.web.domx import div, span
        from pyjs.web.ssr import render_html
        from pyjs.native import gc_collect, gc_set_threshold

        class Setting:
            def __init__(self, name: str, value: str):
                self.name = name
                self.value = value

        def rows(settings: list[Setting]) -> Iterator[Element]:
            for setting in settings:
                gc_collect()
                yield div({"class": "setting"}, span(setting.name), span(setting.value))

        def main() -> str:
            gc_set_threshold(1)
            settings = [Setting("work_mem", "4MB"), Setting("<private>", 'a&"b')]
            return render_html(div({"id": "settings"}, *rows(settings)))
    ''')


def test_generator_library_tracebacks_preserve_yield_locations_and_recover(tmp_path):
    source = '''
from collections.abc import Iterator
from pyjs.native import gc_collect

def values(divisor: int) -> Iterator[str]:
    yield "first"
    gc_collect()
    yield str(10 // divisor)

def render(divisor: int) -> str:
    return ":".join(values(divisor))
'''
    library = LLVM().compile_library(source, tmp_path, entry_point="render", filename="generator.py")
    try:
        for _ in range(3):
            with pytest.raises(LLVMRuntimeError) as caught:
                library.render(0)
            assert caught.value.native_traceback == (
                'Traceback (native PyJS):\n'
                '  File "generator.py", line 11, in render\n'
                '  File "generator.py", line 8, in values\n'
                'ZeroDivisionError: division by zero\n'
            )
            assert library.render(2) == "first:5"
    finally:
        library.close()


def test_unmanaged_runtime_helpers_cannot_bypass_generator_frame_validation():
    with pytest.raises(LLVMUnsupported, match="without defaults or captured state"):
        transpile_llvm('''
            from collections.abc import Iterator
            from pyjs.native.runtime.algorithms import _runtime

            @_runtime
            def invalid() -> Iterator[int]:
                yield 1

            def main() -> int:
                return next(invalid())
        ''')
