import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.native.allocation_support import run_allocation_case
from tests.semantics.helpers import run_python


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_return_is_observed_once_and_loops_and_defaults_discard_it(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Generator, Iterator
        from pyjs.native import gc_collect, gc_set_threshold

        def values() -> Generator[int, None, list[int]]:
            yield 1
            return [2, 3]

        def erased() -> Iterator[int]:
            return values()

        def main() -> str:
            gc_set_threshold(1)
            result: list[object] = []
            source = erased()
            result.append(next(source))
            for _ in range(2):
                try:
                    next(source)
                except StopIteration as error:
                    gc_collect()
                    result.append(error.value)
            source = erased()
            result.append(list(source))
            try:
                next(source)
            except StopIteration as error:
                result.append(error.value)
            source = erased()
            next(source)
            fallback = -1
            result.append(next(source, fallback))
            try:
                next(source)
            except StopIteration as error:
                result.append(error.value)
            return repr(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_completion_through_send_throw_and_finally(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        class Result:
            def __init__(self, value: int):
                self.value = value

            def __str__(self) -> str:
                gc_collect()
                return "result:" + str(self.value)

        def values(events: list[int]) -> Generator[int, int, Result]:
            result = Result(1)
            try:
                try:
                    received: int | None = yield 0
                    if received is not None:
                        result.value = received
                except ValueError:
                    result.value = 9
                return result
            finally:
                gc_collect()
                result.value += 1
                events.append(result.value)

        def replaced() -> Generator[int, None, str]:
            try:
                yield 1
                return "original"
            finally:
                gc_collect()
                return "replacement"

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            result: list[str] = []
            for fail in [False, True]:
                source = values(events)
                next(source)
                try:
                    if fail:
                        source.throw(ValueError("stop"))
                    else:
                        source.send(4)
                except StopIteration as error:
                    gc_collect()
                    result.append(str(error))
                    result.append(str(error.value))
                assert next(source, None) is None
            other = replaced()
            next(other)
            try:
                next(other)
            except StopIteration as error:
                result.append(str(error))
            return repr(result) + repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_returned_numeric_representations_and_implicit_none(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs import int8, float32
        from pyjs.native import gc_collect

        def small() -> Generator[int, None, int8]:
            yield 1
            return int8(130)

        def floating():
            yield 1
            return float32(1.1)

        def ordinary_small():
            value = yield from small()
            assert value - 3 == 127
            return int(value)

        def ordinary_floating():
            value = yield from floating()
            return float(value)

        def optional(flag: bool):
            yield 1
            if flag:
                return 7

        def empty():
            if False:
                yield 1
            return "empty"

        def bare():
            yield 1
            return

        def objects(flag: bool) -> Generator[int, None, object]:
            yield 1
            if flag:
                return 7
            return "text"

        def main() -> str:
            result: list[object] = []
            # Typed delegation keeps arithmetic width; erased payload reads
            # require conversion before publishing the completion as object.
            first = ordinary_small()
            next(first)
            try:
                next(first)
            except StopIteration as error:
                result.append(error.value)
            second = ordinary_floating()
            next(second)
            try:
                next(second)
            except StopIteration as error:
                result.append(error.value)
            for flag in [False, True]:
                third = optional(flag)
                next(third)
                try:
                    next(third)
                except StopIteration as error:
                    gc_collect()
                    result.append(error.value)
            fourth = empty()
            try:
                next(fourth)
            except StopIteration as error:
                result.append(error.value)
            fifth = bare()
            next(fifth)
            try:
                next(fifth)
            except StopIteration as error:
                result.append(str(error))
            for flag in [False, True]:
                sixth = objects(flag)
                next(sixth)
                try:
                    next(sixth)
                except StopIteration as error:
                    gc_collect()
                    result.append(error.value)
            return repr(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation,value", [
    ("int", "7"), ("float", "1.5"), ("bool", "False"),
    ("int8", "int8(130)"), ("float32", "float32(1.1)"),
    ("float32 | None", "float32(1.1)"), ("float32 | None", "None"),
    ("tuple[str, int]", "('done', 7)"),
    ("list[int8]", "[int8(3)]"), ("Box", "Box()"),
    ("str | int", "'ready'"), ("str | int", "7"), ("object", "[2, 3]"),
])
def test_close_returns_completion_once_and_preserves_its_type(tmp_path, optimize, annotation, value):
    arithmetic = ("text += ':' + str(result - 3)" if annotation == "int8" else
                  "text += ':' + str(result + 1.0)" if annotation.startswith("float32") else
                  "text += ':' + result[0] + str(result[1])" if annotation == "tuple[str, int]" else "pass")
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Generator
        from pyjs import int8, float32
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __str__(self) -> str:
                gc_collect()
                return "box"

        def values(events: list[int]) -> Generator[int, None, {annotation}]:
            try:
                yield 1
            except GeneratorExit:
                gc_collect()
                events.append(2)
                return {value}
            return {value}

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            fresh = values(events)
            assert fresh.close() is None
            assert events == []
            source = values(events)
            assert next(source) == 1
            result = source.close()
            gc_collect()
            text = str(result)
            if result is not None:
                {arithmetic}
            assert source.close() is None
            assert next(source, None) is None
            assert events == [2]
            finished = values(events)
            assert list(finished) == [1]
            assert finished.close() is None
            return text
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


def test_close_result_cannot_promise_a_nonnullable_return():
    with pytest.raises(CompilationError, match=r"Function returns int \| NoneType, not int \[PYJS1105\]"):
        transpile_llvm('''
            from collections.abc import Generator
            def child() -> Generator[int, None, int]:
                yield 1
                return 2
            def main() -> int:
                return child().close()
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_completion_none_has_empty_message_and_real_stopiteration_still_raises(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        def none() -> None:
            return None

        def values(fail: bool):
            yield 1
            if fail:
                raise StopIteration("body error")
            return none()

        def main() -> str:
            result: list[str] = []
            for fail in [False, True]:
                source = values(fail)
                next(source)
                try:
                    next(source)
                except StopIteration as error:
                    assert error.value is None
                    result.append(str(error))
                except RuntimeError as error:
                    result.append(str(error))
                try:
                    next(source)
                except StopIteration as error:
                    assert error.value is None
                    result.append(str(error))
            return repr(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_implicit_completion_formatting_retains_virtual_methods_through_cleanup(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        class Base:
            def __str__(self) -> str:
                return "base"

        class Result(Base):
            def __init__(self):
                self.calls = 0
            def __str__(self) -> str:
                gc_collect()
                self.calls += 1
                return "result:" + str(self.calls)

        def values(events: list[int]) -> Generator[int, None, Base]:
            try:
                yield 1
                return Result()
            finally:
                gc_collect()
                events.append(2)

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            source = values(events)
            next(source)
            try:
                next(source)
            except StopIteration as error:
                gc_collect()
                assert events == [2]
                # No direct str(Result) or value access may retain these methods
                # accidentally. The implicit completion boundary must do it.
                return str(error) + ":" + str(error)
            return "missing completion"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_return_boxing_failure_is_catchable_inside_generator(tmp_path, optimize):
    source = transpile_llvm('''
        from collections.abc import Generator
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def values(events: list[int]) -> Generator[int, None, int]:
            try:
                yield 1
                return 7
            except MemoryError:
                arm(0)
                gc_collect()
                events.append(1)
                yield 2
                return 9

        def main() -> int:
            events: list[int] = []
            source = values(events)
            assert next(source) == 1
            arm(1)
            assert next(source) == 2
            assert events == [1]
            try:
                next(source)
            except StopIteration as error:
                gc_collect()
                value = error.value
                assert isinstance(value, int)
                assert int(value) == 9
            else:
                return 1
            assert events == [1]
            assert next(source, None) is None
            return 0
    ''')
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_iterator_consumers_forward_completion_but_generator_expressions_do_not(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Iterator
        from itertools import filterfalse, starmap
        from pyjs.native import gc_collect, gc_set_threshold

        class Source:
            def __iter__(self) -> Source:
                return self

            def __next__(self) -> int:
                raise StopIteration([2, 3])

        def adapt() -> Iterator[object]:
            return Source()

        def values():
            yield 1
            return "source completion"

        def pairs():
            yield (1, 2)
            return "pair completion"

        def keep(value: int) -> bool:
            return value > 0

        def add(left: int, right: int) -> int:
            return left + right

        def positive(value: int) -> int:
            return abs(value)

        def completion(source: Iterator[int]) -> object:
            while True:
                try:
                    next(source)
                except StopIteration as error:
                    return error.value

        def main() -> str:
            gc_set_threshold(1)
            result: list[object] = []
            direct = Source()
            try:
                next(direct)
            except StopIteration as error:
                result.append(error.value)
            adapted = adapt()
            try:
                next(adapted)
            except StopIteration as error:
                gc_collect()
                result.append(error.value)
            expression = (item for item in values())
            assert next(expression) == 1
            try:
                next(expression)
            except StopIteration as error:
                result.append(error.value)
            paired = enumerate(values())
            next(paired)
            try:
                next(paired)
            except StopIteration as error:
                result.append(error.value)
            result.append(completion(filter(keep, values())))
            result.append(completion(filterfalse(keep, values())))
            result.append(completion(map(positive, values())))
            result.append(completion(map(add, [1, 2], values())))
            result.append(completion(starmap(add, pairs())))
            gc_collect()
            return repr(result)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("body", ["return 'bad'", "pass"])
def test_declared_generator_return_contract_is_checked(body):
    with pytest.raises(CompilationError, match="Generator produces"):
        transpile_llvm(f'''
            from collections.abc import Generator

            def values() -> Generator[int, None, int]:
                yield 1
                {body}

            def main() -> int:
                return next(values())
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation", ["int", "str", "int8", "float32", "float64", "list[int8]", "Box"])
def test_close_projection_without_any_valued_generator_return(tmp_path, optimize, annotation):
    comparison = LLVM().assert_matches_python(f'''
        from collections.abc import Generator
        from pyjs import int8, float32, float64

        class Box:
            pass

        def values() -> Generator[int, None, {annotation} | None]:
            yield 1

        def main() -> str:
            fresh = values()
            assert fresh.close() is None
            source = values()
            assert next(source) == 1
            assert source.close() is None
            assert source.close() is None
            return "closed"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_declared_completion_accepts_generators_without_normal_return(tmp_path, optimize):
    comparison = LLVM().assert_matches_python('''
        from collections.abc import Generator

        def endless() -> Generator[int, None, int]:
            while True:
                yield 1

        def failed() -> Generator[int, None, str]:
            yield 2
            raise ValueError("failed")

        def main() -> str:
            source = endless()
            assert next(source) == 1
            assert next(source) == 1
            assert source.close() is None
            other = failed()
            assert next(other) == 2
            try:
                next(other)
            except ValueError as error:
                assert other.close() is None
                return str(error)
            return "missing error"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not comparison.native.stderr


def test_suppressed_generator_return_checks_the_completion_contract(tmp_path):
    source = '''
from collections.abc import Generator

class Swallow:
    def __enter__(self) -> None: pass
    def __exit__(self, kind: object, error: object, trace: object) -> bool:
        return True

def failed() -> int:
    raise ValueError("suppressed")

def values() -> Generator[int, None, int]:
    yield 1
    with Swallow():
        return failed()

def main() -> str:
    source = values()
    next(source)
    result = "missing failure"
    try:
        next(source)
    except TypeError as error:
        result = str(error)
    assert next(source, None) is None
    return result
'''
    # The native result contract is stronger than CPython's unchecked annotation.
    # Insert the corresponding check only into the oracle, after suppression.
    oracle = source.replace("        return failed()\n", "        return failed()\n"
        '    raise TypeError("values returned None through a non-optional completion contract")\n')
    expected = run_python(oracle + '\nprint(main(), end="")\n')
    actual = LLVM().run_source(source, directory=tmp_path, sanitizers=("address", "undefined"))
    assert actual.returncode == expected.returncode == 0
    assert actual.stdout == expected.stdout
    assert actual.stderr == expected.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("annotation,value,other,checked_type,message", [
    ("int", "True", "7", "bool",
     "narrowed int may be bool; convert with int() before integer-only storage"),
    ("bool | int", "True", "7", None, None),
    ("float", "1", "0.5", "int", "object value changed after narrowing"),
    ("int | float", "1", "0.5", None, None),
])
def test_close_preserves_numeric_identity_or_checks_declared_storage(
    tmp_path, optimize, annotation, value, other, checked_type, message,
):
    source = f'''
from collections.abc import Generator
from pyjs.native import gc_collect, gc_set_threshold

def values(flag: bool) -> Generator[int, None, {annotation}]:
    try:
        yield 1
    except GeneratorExit:
        if flag:
            return {value}
        return {other}
    if flag:
        return {value}
    return {other}

def main() -> str:
    gc_set_threshold(1)
    result: list[str] = []
    for flag in [False, True]:
        normal = values(flag)
        next(normal)
        try:
            next(normal)
        except StopIteration as error:
            result.append(str(error.value))
        source = values(flag)
        next(source)
        try:
            value = source.close()
            gc_collect()
            result.append(str(value))
        except TypeError as error:
            result.append(str(error))
        assert source.close() is None
        assert next(source, None) is None
    return repr(result)
'''
    oracle = source
    if checked_type is not None:
        # This native ABI boundary is intentionally stricter than CPython's
        # unchecked annotation, but must never silently change the numeric kind.
        oracle = source.replace("            value = source.close()\n",
            "            value = source.close()\n"
            f"            if isinstance(value, {checked_type}):\n"
            f"                raise TypeError({message!r})\n")
    expected = run_python(oracle + '\nprint(main(), end="")\n')
    actual = LLVM().run_source(source, directory=tmp_path, optimize=optimize,
                               sanitizers=("address", "undefined"))
    assert actual.returncode == expected.returncode == 0
    assert actual.stdout == expected.stdout
    assert actual.stderr == expected.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("completion", ["next(source)", "source.close()"])
def test_completion_boxing_failure_after_finally_exhausts_the_frame(tmp_path, optimize, completion):
    source = transpile_llvm('''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm

        def values(events: list[int]):
            try:
                yield 1
                return 7
            except GeneratorExit:
                return 7
            finally:
                events.append(2)
                arm(1)

        def main() -> int:
            events: list[int] = []
            source = values(events)
            assert next(source) == 1
            try:
                COMPLETION
            except MemoryError:
                arm(0)
                gc_collect()
            else:
                return 1
            assert events == [2]
            assert source.close() is None
            assert next(source, None) is None
            assert events == [2]
            return 0
    '''.replace("COMPLETION", completion))
    result = run_allocation_case(source, tmp_path, managed=True, optimize=optimize)
    assert not result.stderr
