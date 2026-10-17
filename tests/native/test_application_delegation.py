import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.ir import build_program_ir, validate_program_ir
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


def test_application_acquisition_keeps_representations_and_nullable_completion():
    with analyze_source('''
        from pyjs import int8
        class Source:
            def __iter__(self):
                received: int8 = yield int8(1)
                return received + 1
        def parent(value: Source):
            return (yield from value)
        def main() -> int:
            return int(next(parent(Source())))
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        parent = analysis.entry_point.container.search("parent")
        assert {kind.generic_name for kind in parent.return_type.generic_types["R"].types} == {"int", "NoneType"}
        item, sent, returned = parent.return_representation.arguments
        assert item.numeric.bits == sent.numeric.bits == 8
        assert returned.arguments == (item, None)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("body", ["return iter([1])", "yield 1"])
def test_application_delegation_accepts_erased_iterator_results(optimize, body):
    # Erased delegation now supports None-send cursors, including generators.
    result = LLVM().assert_matches_python(f'''
        from typing import Generator, Iterator
        class Source:
            def __iter__(self) -> Iterator[int]:
                {body}
        def parent() -> Generator[int, None, None]:
            yield from Source()
        def main() -> int:
            assert list(parent()) == [1]
            return 0
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_application_delegation_rejects_noniterator_acquisition():
    with pytest.raises(CompilationError, match="Type 'Source' is not iterable"):
        transpile_llvm('''
            from typing import Generator, Iterator
            class Source:
                def __iter__(self) -> list[int]:
                    return [1]
            def parent() -> Generator[int, None, None]:
                yield from Source()
            def main() -> int:
                return next(parent())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("name", ["KeysView", "Generator", "Iterator"])
def test_application_iterable_preserves_acquired_generator_protocols(tmp_path, optimize, name):
    source = '''
        from typing import Generator as Frame
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        class KeysView:
            def __init__(self, events: list[str]):
                self.events = events
                events.append("constructed")

            def __iter__(self) -> Frame[int8, int8, str]:
                self.events.append("started")
                try:
                    received = yield int8(127)
                    try:
                        yield received + 1 if received is not None else int8(0)
                    except ValueError as error:
                        self.events.append(str(error))
                        yield int8(9)
                    return "completed"
                finally:
                    self.events.append("child closed")

            def close(self) -> None:
                raise AssertionError("do not close the iterable instead of its iterator")

        def statement(events: list[str]) -> Frame[int8, int8, None]:
            yield from KeysView(events)

        def stamp(events: list[str], label: str) -> str:
            events.append(label)
            gc_collect()
            return label

        def expression(value: KeysView) -> Frame[int8, int8, str]:
            return repr((stamp(value.events, "before"), (yield from value), stamp(value.events, "after")))

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            source = statement(events)
            assert not events
            values = [int(next(source)), int(source.send(int8(127)))]
            gc_collect()
            values.append(int(source.throw(ValueError("handled"))))
            source.close()
            other = expression(KeysView(events))
            values.append(int(next(other)))
            values.append(int(other.send(int8(1))))
            completion: object = None
            try:
                next(other)
            except StopIteration as error:
                gc_collect()
                completion = error.value
            return repr((values, completion, events))
    '''.replace("KeysView", name)
    result = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                          sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("name", ["Generator", "Iterator"])
def test_application_iterator_names_use_ordinary_method_calls(tmp_path, optimize, name):
    source = '''
        from typing import Generator as Frame
        from pyjs.native import gc_collect, gc_set_threshold

        class Cursor:
            def __iter__(self) -> Frame[int, None, None]:
                yield 7

            def __next__(self) -> int:
                return 11

            def send(self, value: int) -> int:
                return value + 1

            def throw(self, message: str) -> str:
                return message

            def close(self) -> int:
                return 19

        def main() -> str:
            gc_set_threshold(1)
            value = Cursor()
            frame = value.__iter__()
            gc_collect()
            return repr((next(frame), value.__next__(), value.send(5),
                         value.throw("handled"), value.close()))
    '''.replace("Cursor", name)
    result = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                          sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_acquisition_reuses_completion_and_propagates_errors(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        def child() -> Generator[int, None, str]:
            yield 1
            return "done"

        class Source:
            def __init__(self, events: list[str], frame: Generator[int, None, str]):
                self.events = events
                self.frame = frame

            def __iter__(self) -> Generator[int, None, str]:
                self.events.append("base")
                return child()

        class Reused(Source):
            def __iter__(self) -> Generator[int, None, str]:
                self.events.append("derived")
                gc_collect()
                return self.frame

        class Broken(Source):
            def __iter__(self) -> Generator[int, None, str]:
                self.events.append("broken")
                raise StopIteration("acquisition")

        def parent(source: Source) -> Generator[int, None, str | None]:
            return (yield from source)

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            saved = child()
            sources: list[Source] = [Source(events, child()), Reused(events, saved), Reused(events, saved)]
            observations: list[object] = []
            for value in sources:
                source = parent(value)
                try:
                    while True:
                        observations.append(next(source))
                        gc_collect()
                except StopIteration as error:
                    observations.append(error.value)
            failed = parent(Broken(events, child()))
            try:
                next(failed)
            except RuntimeError as error:
                observations.append(str(error))
            return repr((observations, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
