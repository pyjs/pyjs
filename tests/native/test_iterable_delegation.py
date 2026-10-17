import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.ir import build_program_ir, validate_program_ir
from pyjs.analysis.source import analyze_source
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("name", ["KeysView", "ValuesView", "ItemsView", "Generator", "ApplicationSource"])
@pytest.mark.parametrize("assignment", ["", "result = "])
def test_builtin_spelling_does_not_erase_application_delegate_protocols(name, assignment):
    with pytest.raises(CompilationError, match="native erased delegation requires a None send contract"):
        transpile_llvm(f'''
            from typing import Generator as Frame, Self
            class {name}:
                def __iter__(self) -> Self:
                    return self
                def __next__(self) -> int:
                    return 1
                def send(self, value: int) -> int:
                    return value
            def parent() -> Frame[int, int, None]:
                {assignment}yield from {name}()
            def main() -> int:
                source = parent()
                next(source)
                return source.send(7)
        ''')


def test_container_delegation_infers_item_width_and_object_completion():
    with analyze_source('''
        from pyjs import int8
        def values():
            result = yield from [int8(127)]
            return result
        def main() -> int:
            return int(next(values()))
    ''', wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        values = analysis.entry_point.container.search("values")
        assert values.return_type.generic_name == "Generator"
        assert {name: kind.generic_name for name, kind in values.return_type.generic_types.items()} == {
            "V": "int", "S": "NoneType", "R": "object",
        }
        item, sent, returned = values.return_representation.arguments
        assert item.numeric.bits == 8
        assert sent is returned is None


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("expression", [
    "[1, 2]", "(1, 2)", "{1: 3, 2: 4}", "{1, 2}", "frozenset([1, 2])",
    "range(1, 3)", "b'ab'", "{1: 3, 2: 4}.keys()", "{1: 3, 2: 4}.values()",
])
def test_builtin_delegates_preserve_missing_optional_protocols(tmp_path, optimize, expression):
    result = LLVM().assert_matches_python(f'''
        from typing import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        def parent(events: list[str]) -> Generator[int, int, None]:
            try:
                completion = yield from {expression}
                gc_collect()
                assert completion is None
                events.append("done")
            finally:
                events.append("finally")

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            observations: list[str] = []
            observations.append(repr(sorted(list(parent(events)))))
            source = parent(events)
            next(source)
            observations.append(str(source.send(None)))
            source.close()
            for mode in [0, 1]:
                source = parent(events)
                next(source)
                try:
                    if mode == 0:
                        source.send(9)
                    else:
                        source.throw(ValueError("injected"))
                except AttributeError as error:
                    observations.append(str(error))
                except ValueError as error:
                    observations.append(str(error))
                assert next(source, -1) == -1
            return repr((observations, events))
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_missing_send_names_ascii_and_large_range_iterators(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        def text(value: str) -> Generator[str, str, None]:
            yield from value

        def numbers(value: range) -> Generator[int, int, None]:
            yield from value

        def main() -> str:
            gc_set_threshold(1)
            messages: list[str] = []
            for value in ["ascii", "é", "🙂"]:
                source = text(value)
                next(source)
                gc_collect()
                try:
                    source.send("x")
                except AttributeError as error:
                    messages.append(str(error))
            for value in [range(3), range(-9223372036854775807, 9223372036854775807),
                          range(9223372036854775807, -9223372036854775807, -1),
                          range(-9223372036854775807, 9223372036854775807, 2),
                          range(9223372036854775807, -9223372036854775808, -2),
                          range(-9223372036854775806, 9223372036854775806, 2),
                          range(0, -9223372036854775808, -2), range(5, 0, -2)]:
                source2 = numbers(value)
                next(source2)
                gc_collect()
                try:
                    source2.send(1)
                except AttributeError as error:
                    messages.append(str(error))
            return repr(messages)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_container_delegation_preserves_recovery_and_exception_boundaries(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        def acquire(events: list[str]) -> list[int]:
            events.append("acquire")
            return [1, 2]

        def parent(events: list[str]) -> Generator[int, int, None]:
            try:
                yield from acquire(events)
            except AttributeError as error:
                events.append(str(error))
                gc_collect()
                yield 9
            finally:
                events.append("finally")

        def mutate(values: dict[int, int]) -> Generator[int, None, None]:
            yield from values

        def fail_acquisition() -> list[int]:
            raise StopIteration("acquisition")

        def failed() -> Generator[int, None, None]:
            yield from fail_acquisition()

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            for mode in [0, 1, 2, 3]:
                source = parent(events)
                assert events.count("acquire") == mode
                assert next(source) == 1
                assert events.count("acquire") == mode + 1
                try:
                    if mode == 0:
                        events.append(str(source.send(4)))
                        assert next(source, -1) == -1
                    elif mode == 1:
                        source.throw(StopIteration("injected"))
                    elif mode == 2:
                        source.throw(BaseException("exit"))
                    else:
                        source.throw(GeneratorExit("close"))
                except RuntimeError as error:
                    events.append(str(error))
                except GeneratorExit as error:
                    events.append(str(error))
                except BaseException as error:
                    events.append(str(error))
                assert next(source, -1) == -1
            values = {1: 2, 3: 4}
            source2 = mutate(values)
            next(source2)
            values[5] = 6
            gc_collect()
            try:
                next(source2)
            except RuntimeError as error:
                events.append(str(error))
            try:
                next(failed())
            except RuntimeError as error:
                events.append(str(error))
            return repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_text_items_empty_sources_and_mutation(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Generator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def text() -> Generator[str, str, None]:
            result = yield from "aé🙂"
            assert result is None

        def items() -> Generator[tuple[str, int8], None, None]:
            yield from {"a": int8(127), "b": int8(-128)}.items()

        def mutable(values: list[int8]) -> Generator[int8, None, None]:
            yield from values

        def empty() -> Generator[int, None, None]:
            values: list[int] = []
            result = yield from values
            gc_collect()
            assert result is None
            yield 9

        def main() -> str:
            gc_set_threshold(1)
            observations = [repr(list(text())), repr(list(items())), repr(list(empty()))]
            source = text()
            next(source)
            try:
                source.send("x")
            except AttributeError as error:
                observations.append(str(error))
            values = [int8(127)]
            small = mutable(values)
            observations.append(str(int(next(small) + 1)))
            values.append(int8(-128))
            gc_collect()
            observations.append(repr(list(small)))
            return repr(observations)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_injected_stop_iteration_supplies_builtin_completion(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Generator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def parent() -> Generator[int, None, object]:
            result = yield from [1, 2]
            gc_collect()
            return result

        def main() -> str:
            gc_set_threshold(1)
            results: list[object] = []
            payloads: list[object] = [None, 127, "text", [int8(9)]]
            for payload in payloads:
                source = parent()
                assert next(source) == 1
                try:
                    source.throw(StopIteration(payload))
                except StopIteration as error:
                    gc_collect()
                    results.append(error.value)
            return repr(results)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_temporary_container_keeps_unyielded_objects_alive(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from typing import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, value: str):
                self.value = value

        def parent() -> Generator[Box, None, None]:
            yield from [Box("first"), Box("last")]

        def main() -> str:
            gc_set_threshold(1)
            source = parent()
            first = next(source)
            gc_collect()
            last = next(source)
            source.close()
            gc_collect()
            return first.value + last.value
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""
