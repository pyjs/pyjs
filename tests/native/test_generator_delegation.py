import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.ir import build_program_ir, validate_program_ir
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case


def test_delegation_completion_metadata_distinguishes_fresh_and_reusable_frames():
    with analyze_source('''
        from typing import Generator
        from pyjs import int8

        def child() -> Generator[int8, int8, int8]:
            yield int8(1)
            return int8(2)

        def fresh():
            return (yield from child())

        def reused(source: Generator[int8, int8, int8]):
            return (yield from source)

        def main() -> int:
            next(fresh())
            return int(next(reused(child())))
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        fresh = analysis.entry_point.container.search("fresh")
        reused = analysis.entry_point.container.search("reused")
        assert fresh.return_type.generic_name == reused.return_type.generic_name == "Generator"
        assert fresh.return_type.generic_types["R"].generic_name == "int"
        assert {member.generic_name for member in reused.return_type.generic_types["R"].types} == {"int", "NoneType"}
        small = fresh.return_representation.arguments[0]
        assert small.numeric.bits == 8
        assert fresh.return_representation.arguments == (small, small, small)
        assert reused.return_representation.arguments[:2] == (small, small)
        assert reused.return_representation.arguments[2].arguments == (small, None)
        # Full forwarding CFGs are large; retain the two distinct projection
        # contracts and ensure the generated exception aliases are printable.
        assert "project_result[int](" in analysis.types
        assert "project_result[int | None](" in analysis.types


@pytest.mark.parametrize("annotation, body, message", [
    ("Generator[int, int, None]", "first = yield 0\nyield from source", "input type must be known before"),
])
def test_delegation_rejects_missing_protocol_or_late_input_contract(annotation, body, message):
    source = f'''
from typing import Generator, Iterator
def parent(source: {annotation}):
    {body.replace(chr(10), chr(10) + '    ')}
def child() -> Generator[int, int, None]:
    yield 1
def main() -> int:
    return next(parent(child()))
'''
    with pytest.raises(CompilationError, match=message) as caught:
        transpile_llvm(source)
    assert caught.value.diagnostic.primary.span.start_position.line >= 2


@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_generator_factory_may_return_an_exhausted_frame(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        class Factory:
            def create(self) -> Generator[int, None, int]:
                yield 1
                return 2

        class Reused(Factory):
            def __init__(self, source: Generator[int, None, int]):
                self.source = source

            def create(self) -> Generator[int, None, int]:
                return self.source

        def parent(factory: Factory) -> Generator[int, None, str]:
            result = yield from factory.create()
            gc_collect()
            return str(result)

        def main() -> str:
            gc_set_threshold(1)
            source = Factory().create()
            list(source)
            frames = [parent(Factory()), parent(Reused(source))]
            results: list[object] = []
            for frame in frames:
                try:
                    while True:
                        next(frame)
                except StopIteration as error:
                    results.append(error.value)
            return repr(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_delegation_requires_a_compatible_forwarded_send_domain():
    with pytest.raises(CompilationError, match="Generator.send expects NoneType, got int"):
        transpile_llvm('''
            from typing import Generator
            def child() -> Generator[int, None, None]:
                yield 1
            def parent() -> Generator[int, int, None]:
                yield from child()
            def main() -> int:
                return next(parent())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_delegation_keeps_application_results_and_private_bindings(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: str):
                self.value = value

        def leaf() -> Generator[str, None, Box]:
            yield "leaf"
            return Box("kept")

        def middle() -> Generator[str, None, Box]:
            return (yield from leaf())

        def parent():
            next = 10
            object = 20
            StopIteration = 30
            __delegate_source = 40
            result = yield from middle()
            gc_collect()
            yield result.value
            yield str(next + object + StopIteration + __delegate_source)

        def main() -> str:
            gc_set_threshold(1)
            return repr(list(parent()))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_delegation_allocation_failure_recovers(tmp_path, optimize):
    source = '''
        from typing import Generator, Iterator
        from pyjs.native import gc_collect, gc_set_threshold
        from tests.native.allocation_support import arm

        def child() -> Generator[str, None, list[str]]:
            yield "first"
            gc_collect()
            return ["last"]

        def parent() -> Iterator[str]:
            result = yield from child()
            gc_collect()
            yield result[0]

        def main() -> int:
            gc_set_threshold(1)
            failures = 0
            for attempt in range(1, 100):
                complete = False
                try:
                    arm(attempt)
                    result = list(parent())
                    arm(0)
                    assert result == ["first", "last"]
                    complete = True
                except MemoryError:
                    arm(0)
                    failures += 1
                finally:
                    arm(0)
                gc_collect()
                assert list(parent()) == ["first", "last"]
                if complete:
                    return 0 if failures else 1
            return 2
    '''
    result = run_allocation_case(transpile_llvm(source), tmp_path, managed=True, optimize=optimize)
    assert result.stderr == b""


@pytest.mark.parametrize("optimize", [0, 2])
def test_inferred_delegation_keeps_portable_send_and_return_types(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Generator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def child() -> Generator[int8, int8, int8]:
            value = yield int8(1)
            gc_collect()
            return int8(-1) if value is None else value + 1

        def parent():
            return (yield from child())

        def main() -> str:
            gc_set_threshold(1)
            source = parent()
            first = next(source)
            try:
                source.send(int8(127))
            except StopIteration as error:
                return str((int(first), str(error)))
            return "missing completion"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_delegated_reference_views_preserve_send_aliases_and_repeated_throw_recovery(tmp_path, optimize):
    # Scalar int8 -> object erasure in the historical send/throw fixtures is
    # intentionally no longer implicit. References can keep represented items
    # through the same view/delegation graph without changing their arithmetic.
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def child(events: list[str]) -> Generator[list[int8], list[int8], None]:
            try:
                received = yield [int8(1)]
                gc_collect()
                assert received is not None
                try:
                    yield received
                except ValueError as error:
                    gc_collect()
                    events.append(str(error))
                    try:
                        yield [int8(130)]
                    except KeyError:
                        gc_collect()
                        events.append('second caught')
                        yield [int8(3)]
                events.append('child complete')
            finally:
                events.append('child cleanup')

        def widen(source: Generator[list[int8], list[int8], None]) -> Generator[object, list[int8], None]:
            return source

        def middle(source: Generator[object, list[int8], None], events: list[str]):
            yield from source
            events.append('middle complete')

        def parent(source: Generator[object, list[int8], None], events: list[str]):
            try:
                yield from middle(source, events)
                yield 'after'
            finally:
                events.append('parent cleanup')

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            original = child(events)
            view = widen(original)
            assert view is original
            source = parent(view, events)
            first = next(source)
            sent = [int8(127)]
            assert source.send(sent) is sent
            assert sent[0] + 1 == -128
            recovered = source.throw(ValueError('first' + str(1)))
            second = source.throw(KeyError('second'))
            assert next(source) == 'after'
            source.close()
            source.close()
            assert next(original, None) is None
            gc_collect()
            return repr((first, recovered, second, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_delegation_completion_and_failure_edges(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        def child(mode: int, events: list[str]) -> Generator[int, None, str]:
            if mode == 0:
                return "empty"
            try:
                try:
                    yield 1
                except ValueError:
                    return "recovered"
                except GeneratorExit:
                    if mode == 2:
                        yield 9
                    else:
                        raise
                if mode == 3:
                    raise StopIteration("body")
                return "done"
            finally:
                gc_collect()
                events.append("child")

        def parent(source: Generator[int, None, str], events: list[str]):
            try:
                result = yield from source
                events.append(str(result))
            finally:
                events.append("parent")

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            assert list(parent(child(0, events), events)) == []
            normal = parent(child(1, events), events)
            assert next(normal) == 1
            try:
                normal.throw(ValueError("recover"))
            except StopIteration:
                pass
            else:
                assert False
            stubborn = child(2, events)
            closing = parent(stubborn, events)
            next(closing)
            try:
                closing.close()
            except RuntimeError as error:
                events.append(str(error))
            else:
                assert False
            assert next(closing, -1) == -1
            stubborn.close()
            failing = parent(child(3, events), events)
            next(failing)
            try:
                next(failing)
            except RuntimeError as error:
                events.append(str(error))
            else:
                assert False
            unentered = child(1, events)
            untouched = parent(unentered, events)
            untouched.close()
            assert next(unentered) == 1
            unentered.close()
            return str(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_delegation_of_reused_generator_preserves_none_completion(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Generator, Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def child() -> Generator[str, None, int]:
            yield "item"
            return 7

        def parent(source: Generator[str, None, int]) -> Iterator[str]:
            result = yield from source
            gc_collect()
            if result is None:
                yield "empty"
            else:
                yield str(result)

        def main() -> str:
            gc_set_threshold(1)
            source = child()
            first = list(parent(source))
            second = list(parent(source))
            return str((first, second))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_delegation_union_items_and_nullable_represented_completion(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Generator, Iterator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def child(flag: bool) -> Generator[int | str, None, list[int8] | None]:
            yield 1
            yield "two"
            if flag:
                return [int8(127)]
            return None

        def parent(flag: bool) -> Iterator[int | str]:
            values = yield from child(flag)
            gc_collect()
            if values is not None:
                yield int(values[0] + 1)
            else:
                yield "none"

        def main() -> str:
            gc_set_threshold(1)
            return str((list(parent(True)), list(parent(False))))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_delegated_completion_in_expressions_preserves_representation_and_order(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Generator, Iterator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def mark(events: list[str], label: str) -> str:
            events.append(label)
            gc_collect()
            return label

        def child(events: list[str]) -> Generator[str, None, int8]:
            events.append("child")
            yield "start"
            gc_collect()
            return int8(127)

        def rows() -> Generator[str, None, list[str]]:
            yield "rows"
            return ["one", "two"]

        def parent(events: list[str]) -> Iterator[str]:
            value = yield from child(events)
            yield str(int(value + 1))
            yield mark(events, "left") + str((yield from child(events)))
            values = yield from rows()
            gc_collect()
            yield ":".join(values)
            yield str((yield from child(events))) if False else "skipped"

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            values = list(parent(events))
            return str((values, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", [" -> Generator[int, int, None]", ""])
def test_generator_delegation_forwards_resume_and_cleanup(tmp_path, optimize, annotation):
    result = LLVM().assert_matches_python(f'''
        from typing import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        def child(events: list[str]) -> Generator[int, int, str]:
            try:
                received = yield 1
                gc_collect()
                try:
                    yield received if received is not None else 2
                except ValueError as error:
                    events.append(str(error))
                    yield 3
                return "complete"
            finally:
                gc_collect()
                events.append("child closed")

        def parent(events: list[str]){annotation}:
            try:
                yield from child(events)
                events.append("parent done")
            finally:
                events.append("parent closed")

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            cursor = parent(events)
            first = next(cursor)
            second = cursor.send(7)
            third = cursor.throw(ValueError("recover"))
            last = next(cursor, -1)
            closing = parent(events)
            next(closing)
            closing.close()
            return str((first, second, third, last, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
