import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.errors import LLVMUnsupported
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("name", ["list", "Generator"])
def test_application_names_do_not_select_builtin_delegation(tmp_path, optimize, name):
    result = LLVM().assert_matches_python(f'''
        from builtins import list as builtin_list
        class {name}:
            def __init__(self, events: builtin_list[str]):
                self.events = events
            def __iter__(self) -> "{name}":
                return self
            def __next__(self) -> int:
                return 1
            def close(self) -> None:
                self.events.append("closed")
        def parent(source: {name}):
            yield from source
        def main() -> str:
            events: builtin_list[str] = []
            value = parent({name}(events))
            assert next(value) == 1
            value.close()
            return repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_delegation_does_not_reach_unrelated_cursor_control(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        class Unrelated:
            def __iter__(self) -> "Unrelated":
                return self
            def __next__(self) -> int:
                raise StopIteration()
            def close(self) -> None:
                missing_close()
            def throw(self, error: BaseException) -> int:
                return missing_throw()
        def child(events: list[str]):
            try:
                yield 1
            except ValueError:
                yield 2
            finally:
                events.append("closed")
        def parent(source: Iterator[int]):
            yield from source
        def main() -> str:
            assert list(Unrelated()) == []
            events: list[str] = []
            iterator = parent(child(events))
            assert next(iterator) == 1
            assert iterator.throw(ValueError()) == 2
            iterator.close()
            return repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_delegate_forwards_thrown_exception_and_completion(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        def child():
            try:
                yield 1
            except ValueError:
                yield 2
                return 9
        def parent(source: Iterator[int]):
            result = yield from source
            yield result
        def main() -> str:
            value = parent(child())
            result = [next(value)]
            result.append(value.throw(ValueError("forwarded")))
            result.append(next(value))
            return str(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_close_survives_iterator_and_iterable_erasure(tmp_path, optimize):
    # These views erase the yielded type as well as the generator controls.
    # Portable scalars need explicit conversion before that ordinary domain.
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable, Iterator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def child(events: list[str]):
            try:
                yield int(int8(130))
                yield int(int8(2))
            finally:
                gc_collect()
                events.append("child")

        def cursor(value: Iterator[int]) -> Iterator[object]:
            return value

        def iterable(value: Iterator[object]) -> Iterable[object]:
            return value

        def parent(value: Iterable[object], events: list[str]):
            try:
                yield from value
            finally:
                events.append("parent")

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            source = child(events)
            retained = cursor(source)
            value = parent(iterable(retained), events)
            assert next(value) == -126
            value.close()
            assert iter(retained) is source
            assert next(retained, None) is None
            value.close()
            assert list(parent(iterable(cursor(child(events))), events)) == [-126, 2]
            expression = (int(int8(item)) for item in [1, 2])
            value = parent(iterable(cursor(expression)), events)
            assert next(value) == 1
            value.close()
            assert next(expression, None) is None
            return repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_delegated_close_discards_child_result_and_preserves_parent_result(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold
        def child(events: list[str]):
            try:
                yield 1
            except GeneratorExit:
                events.append("child")
                return [int8(130)]
            return [int8(2)]
        def parent(events: list[str]):
            try:
                result = yield from child(events)
                events.append(str(result))
            except GeneratorExit:
                gc_collect()
                events.append("parent")
                return [int8(7)]
            return [int8(8)]
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            source = parent(events)
            next(source)
            result = source.close()
            gc_collect()
            assert result is not None
            assert result[0] + int8(1) == int8(8)
            assert source.close() is None
            return repr(result) + repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_delegation_closes_actual_custom_iterator_and_ignores_close_result(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable, Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        class Cursor:
            def __init__(self, events: list[str]):
                self.events = events
                self.index = 0

            def __iter__(self) -> "Cursor":
                self.events.append("cursor iter")
                return self

            def __next__(self) -> int:
                self.index += 1
                if self.index > 2:
                    raise StopIteration()
                return self.index

            def close(self, flush: bool = True) -> int:
                gc_collect()
                self.events.append("flush" if flush else "close")
                return 42

        class Special(Cursor):
            def __iter__(self) -> Cursor:
                self.events.append("special iter")
                return self

            def close(self, flush: bool = False) -> int:
                gc_collect()
                self.events.append("special flush" if flush else "special close")
                return 7

        class Source:
            def __init__(self, events: list[str]):
                self.events = events

            def __iter__(self) -> Cursor:
                self.events.append("source iter")
                return Special(self.events)

            def close(self):
                self.events.append("WRONG source close")

        def erased(value: Iterator[int]) -> Iterator[object]:
            return value

        def parent(value: Iterable[object]):
            yield from value

        def concrete(value: Source):
            yield from value

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            one = parent(Source(events))
            assert next(one) == 1
            one.close()
            two = concrete(Source(events))
            assert next(two) == 1
            two.close()
            cursor = Special(events)
            three = parent(erased(cursor))
            assert next(three) == 1
            three.close()
            assert next(cursor) == 2
            assert list(parent(Source(events))) == [1, 2]
            return repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_optional_close_and_custom_cleanup_failure(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterable, Iterator
        from pyjs.native import gc_collect

        class Cursor:
            def __iter__(self) -> "Cursor":
                return self

            def __next__(self) -> int:
                return 3

        class Failing(Cursor):
            def close(self):
                gc_collect()
                raise ValueError("custom cleanup")

        class BrokenSource:
            def __iter__(self) -> Iterator[int]:
                raise GeneratorExit("iterator setup")

            def close(self):
                raise AssertionError("factory must not be closed")

        def parent(value: Iterable[int], events: list[str]):
            try:
                yield from value
            finally:
                events.append("outer")

        def main() -> str:
            events: list[str] = []
            cursor = iter([1, 2])
            first = parent(cursor, events)
            assert next(first) == 1
            first.close()
            assert next(cursor) == 2
            second = parent(range(2), events)
            assert next(second) == 0
            second.close()
            third = parent(Cursor(), events)
            assert next(third) == 3
            third.close()
            last = parent(Failing(), events)
            assert next(last) == 3
            try:
                last.close()
            except ValueError as error:
                events.append(str(error))
            assert next(last, None) is None
            broken = parent(BrokenSource(), events)
            try:
                next(broken)
            except GeneratorExit as error:
                events.append(str(error))
            broken.close()
            return repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_close_reaches_nested_delegates_before_outer_cleanup(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def child(events: list[str]) -> Generator[int, None, None]:
            events.append("started")
            try:
                yield int(int8(130))
                yield int(int8(2))
            finally:
                gc_collect()
                events.append("child")

        def middle(value: Generator[int, None, None], events: list[str]):
            try:
                yield from value
            finally:
                gc_collect()
                events.append("middle")

        def adapt(value: Generator[int, None, None]) -> Generator[object, None, None]:
            return value

        def select(value: Generator[object, None, None], events: list[str]) -> Generator[object, None, None]:
            events.append("selected")
            return value

        def parent(value: Generator[object, None, None], events: list[str]):
            try:
                yield from select(value, events)
            finally:
                gc_collect()
                events.append("parent")

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            source = child(events)
            delegate = middle(source, events)
            value = parent(adapt(delegate), events)
            assert next(value) == -126
            value.close()
            assert next(source, None) is None
            assert next(delegate, None) is None
            value.close()
            untouched = parent(adapt(middle(child(events), events)), events)
            untouched.close()
            return repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_delegate_close_failures_replace_exit_and_exhaust_only_finished_frames(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        class Finished(GeneratorExit):
            pass

        def child(mode: int, events: list[str]):
            try:
                try:
                    yield 1
                except GeneratorExit:
                    if mode == 1:
                        yield 2
            finally:
                gc_collect()
                events.append("child")
                if mode == 0:
                    raise ValueError("cleanup")
                if mode == 2:
                    raise Finished("done")

        def parent(value: Generator[int, None, None], events: list[str]):
            try:
                yield from value
            finally:
                events.append("parent")

        def main() -> str:
            events: list[str] = []
            for mode in [0, 1, 2]:
                source = child(mode, events)
                value = parent(source, events)
                next(value)
                try:
                    value.close()
                except ValueError as error:
                    events.append(str(error))
                except RuntimeError as error:
                    events.append(str(error))
                assert next(value, None) is None
                source.close()
                assert next(source, None) is None
            return repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_thrown_generator_exit_closes_delegate_and_ignores_shadowed_builtin_name(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator

        class Finished(GeneratorExit):
            pass

        def child(events: list[str]):
            try:
                yield 1
            finally:
                events.append("child")

        def parent(value: Generator[int, None, None], events: list[str], GeneratorExit: int):
            try:
                yield from value
            finally:
                events.append(str(GeneratorExit))

        def main() -> str:
            events: list[str] = []
            source = child(events)
            value = parent(source, events, 42)
            next(value)
            try:
                value.throw(Finished("injected"))
            except Finished as error:
                events.append(str(error))
            assert next(value, None) is None
            assert next(source, None) is None
            return repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_erased_none_items_forward_throw(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        def child():
            try:
                yield None
            except ValueError:
                yield None
        def parent(source: Iterator[None]):
            yield from source
        def main() -> str:
            value = parent(child())
            first = next(value)
            second = value.throw(ValueError("forwarded"))
            return str((first, second, list(value)))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_erased_non_none_send_requires_a_concrete_generator_contract():
    with pytest.raises(CompilationError, match="erased delegation requires a None send contract"):
        transpile_llvm('''
            from collections.abc import Generator, Iterator
            def parent(source: Iterator[int]) -> Generator[int, int, None]:
                yield from source
            def main() -> int:
                return next(parent(iter([1, 2])))
        ''')


def test_application_throw_is_not_silently_skipped():
    with pytest.raises(LLVMUnsupported, match="application delegate throw methods require first-class exceptions"):
        transpile_llvm('''
            class Cursor:
                def __iter__(self) -> "Cursor":
                    return self
                def __next__(self) -> int:
                    return 1
                def throw(self, error: BaseException) -> int:
                    return 2
            def parent(source: Cursor):
                yield from source
            def main() -> int:
                return next(parent(Cursor()))
        ''')
