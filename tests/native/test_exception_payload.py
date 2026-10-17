import subprocess
from contextlib import closing

import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError
from tests.native.allocation_support import _fail_allocations, run_allocation_case
from tests.semantics.helpers import run_python


@pytest.mark.parametrize("exception, method, unused", [
    ("ValueError", "__str__", "__repr__"), ("KeyError", "__repr__", "__str__"),
])
@pytest.mark.parametrize("other_payload", ["1", "[1]"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_exception_formatting_does_not_reach_the_unused_protocol(exception, method, unused, other_payload, optimize):
    other = "KeyError" if exception == "ValueError" else "ValueError"
    result = LLVM().assert_matches_python(f'''
        class Message:
            def {method}(self) -> str:
                return "message"
            def {unused}(self) -> str:
                return not_defined
        def main() -> str:
            output: list[str] = []
            try:
                raise {exception}(Message())
            except {exception} as error:
                output.append(str(error))
            try:
                raise {other}({other_payload})
            except {other} as error:
                output.append(str(error))
            return repr(output)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_generator_completion_does_not_reach_other_key_payload_str(optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator
        class Message:
            def __repr__(self) -> str:
                return "key"
            def __str__(self) -> str:
                return not_defined
        def source() -> Generator[int, None, list[int]]:
            yield 0
            return [1]
        def main() -> str:
            output: list[str] = []
            stream = source()
            next(stream)
            try:
                next(stream)
            except StopIteration as done:
                output.append(str(done))
            try:
                raise KeyError(Message())
            except KeyError as error:
                output.append(str(error))
            return repr(output)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("payload", [
    "lambda: 1", "Owner().method", "function", "(i for i in [1])", "iter([1])",
    "function if flag else None", "iter([1]) if flag else None",
    "iterable()", "iterable() if flag else None",
])
@pytest.mark.parametrize("statement", [
    "raise ValueError({payload})", "raise StopIteration({payload})",
    "assert False, {payload}", "stream.throw(KeyError({payload}))",
    "boxed: object = {payload}",
])
def test_exception_payloads_use_the_normal_object_erasure_boundary(payload, statement):
    # Annotated assignments can reject callables during layout validation,
    # before reaching the common boxing guard used by exception payloads.
    diagnostic = ("callable (erasure to object|values require matching parameter and result types)"
                  "|(iterator handles|Iterable views) cannot yet be erased")
    with pytest.raises(LLVMUnsupported, match=diagnostic) as caught:
        transpile_llvm(f'''
            from collections.abc import Generator, Iterable
            class Owner:
                def method(self) -> int:
                    return 1
            def function() -> int:
                return 1
            def iterable() -> Iterable[int]:
                return [1, 2]
            def source() -> Generator[int, None, None]:
                yield 1
            def main() -> int:
                flag = True
                stream = source()
                next(stream)
                {statement.format(payload=payload)}
                return 0
        ''')
    assert caught.value.node.lineno is not None


@pytest.mark.parametrize("optimize", [0, 2])
def test_assertion_payload_evaluation_is_lazy_and_keeps_original_failures(optimize, tmp_path):
    result = LLVM().assert_matches_python('''
        from pyjs.native import gc_collect
        class Message:
            def __str__(self) -> str:
                gc_collect()
                return "message"
        def message(events: list[int], fail: bool) -> Message:
            events.append(1)
            if fail:
                raise ValueError("evaluation")
            return Message()
        def main() -> str:
            events: list[int] = []
            assert True, message(events, True)
            assert events == []
            output: list[str] = []
            for fail in [False, True]:
                try:
                    assert False, message(events, fail)
                except AssertionError as error:
                    gc_collect()
                    output.append(str(error))
                except ValueError as error:
                    output.append(str(error))
            return repr(events) + repr(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("statement", [
    "raise ValueError(message)", "raise KeyError(message)",
    "raise SyntaxError(message)", "raise Failure(message)",
    "assert False, message",
])
@pytest.mark.parametrize("optimize", [0, 2])
def test_exception_messages_are_lazy_mutable_and_repeatable(statement, optimize, tmp_path):
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold

        class Failure(RuntimeError):
            pass

        class Message:
            def __init__(self, events: list[str]):
                self.events = events
                self.value = 1
            def render(self, kind: str) -> str:
                self.events.append(kind)
                gc_collect()
                if self.value == 3:
                    raise ValueError("format failed")
                return kind + ":" + str(self.value)
            def __str__(self) -> str:
                return self.render("str")
            def __repr__(self) -> str:
                return self.render("repr")

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            message = Message(events)
            output: list[str] = []
            try:
                {statement}
            except Exception as error:
                assert events == []
                gc_collect()
                output.append(str(error))
                message.value = 2
                output.append(str(error))
                message.value = 3
                try:
                    str(error)
                except ValueError as formatting:
                    output.append(str(formatting))
                else:
                    raise AssertionError("missing formatting failure")
                message.value = 4
                gc_collect()
                try:
                    raise error
                except Exception as reraised:
                    output.append(str(reraised))
                output.append(str(error))
            values = [1]
            try:
                raise TypeError(values)
            except TypeError as error:
                values.append(2)
                gc_collect()
                output.append(str(error))
            return repr(output) + repr(events)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_message_payloads_survive_unwinding_and_generator_injection(optimize, tmp_path):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        class Message:
            def __str__(self) -> str:
                gc_collect()
                return "str"
            def __repr__(self) -> str:
                gc_collect()
                return "repr"

        class Child(Message):
            def __str__(self) -> str:
                gc_collect()
                return "child"

        def fail(message: object) -> None:
            raise RuntimeError(message)

        def source() -> Generator[str, None, None]:
            try:
                yield "ready"
            except KeyError as error:
                gc_collect()
                yield str(error)

        def main() -> str:
            gc_set_threshold(1)
            output: list[str] = []
            messages: list[object] = [b"bytes", [1, 2], {"key": [3]}, Message(), Child(), None, 7]
            for message in messages:
                try:
                    fail(message)
                except RuntimeError as error:
                    gc_collect()
                    output.append(str(error))
            stream = source()
            output.append(next(stream))
            output.append(stream.throw(KeyError(Message())))
            try:
                raise ValueError([Child()])
            except ValueError as error:
                gc_collect()
                output.append(str(error))
            return repr(output)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_stop_iteration_subclass_union_keeps_payload_identity(optimize):
    result = LLVM().assert_matches_python('''
        from typing import cast
        from pyjs.native import gc_collect, gc_set_threshold

        class First(StopIteration):
            pass

        class Second(StopIteration):
            pass

        def read(flag: bool, values: list[int]) -> str:
            try:
                if flag:
                    raise First(values)
                raise Second(values)
            except (First, Second) as error:
                gc_collect()
                payload = cast(list[int], error.value)
                if payload is not values:
                    return "lost identity"
                values.append(9)
                gc_collect()
                return repr(error.value)

        def main() -> str:
            gc_set_threshold(1)
            return read(True, [5]) + read(False, [7])
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


def test_exception_union_properties_have_a_focused_unsupported_boundary():
    with pytest.raises(LLVMUnsupported, match="property access requires a concrete or tagged receiver"):
        transpile_llvm('''
            class First(Exception):
                @property
                def value(self) -> int:
                    return 5

            class Second(Exception):
                @property
                def value(self) -> int:
                    return 7

            def pick(flag: bool) -> First | Second:
                if flag:
                    return First()
                return Second()

            def main() -> int:
                return pick(True).value
        ''')


def test_exception_value_override_is_rejected_before_assuming_the_builtin_layout():
    with pytest.raises(LLVMUnsupported, match="cannot override the value property"):
        transpile_llvm('''
            class Finished(StopIteration):
                @property
                def value(self) -> int:
                    return 99
            def main() -> int:
                try:
                    raise Finished(7)
                except Finished as error:
                    return error.value
        ''')


@pytest.mark.parametrize("value", ["7", "None", "[1, 2]", "0.5", "b'bytes'"])
def test_unobserved_payload_still_prepares_boxing_and_reporter_dependencies(value):
    LLVM().assert_matches_python(f'''
        def main() -> int:
            try:
                raise StopIteration({value})
            except StopIteration:
                return 1
    ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_numeric_payloads_preserve_values_and_nested_container_layouts(optimize):
    LLVM().assert_matches_python('''
        from pyjs import StaticArray, float32, int8
        from pyjs.native import gc_collect, gc_set_threshold

        def scalar(value: float32 | None) -> str:
            try:
                # Scalar object reads require an explicit arithmetic-domain
                # conversion; nested represented container layouts stay intact.
                raise StopIteration(float(value) if value is not None else None)
            except StopIteration as error:
                gc_collect()
                return str(error) + repr(error.value)

        def main() -> str:
            gc_set_threshold(1)
            values: StaticArray[float32, 2] = [float32(1.1), float32(-0.0)]
            small = [int8(127), int8(-128)]
            result = scalar(float32(1.1)) + scalar(None)
            try:
                raise StopIteration((values, small))
            except StopIteration as error:
                gc_collect()
                result += str(error) + repr(error.value)
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_payload_text_is_lazy_repeatable_and_formatter_failure_preserves_the_value(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Label:
            def __init__(self, events: list[int]):
                self.events = events
                self.value = 1

            def __str__(self) -> str:
                self.events.append(self.value)
                gc_collect()
                if self.value == 3:
                    raise ValueError("format failed")
                return "label:" + str(self.value)

        def main() -> str:
            gc_set_threshold(1)
            events: list[int] = []
            label = Label(events)
            result: list[str] = []
            try:
                raise StopIteration(label)
            except StopIteration as error:
                assert events == []
                result.append(str(error))
                label.value = 2
                result.append(str(error))
                label.value = 3
                try:
                    str(error)
                except ValueError as formatting:
                    result.append(str(formatting))
                gc_collect()
                assert error.value is label
                label.value = 4
                result.append(str(error))
            items = [1]
            try:
                raise StopIteration(items)
            except StopIteration as error:
                items.append(2)
                result.append(str(error))
                items.clear()
                result.append(str(error))
            for explicit in [False, True]:
                try:
                    if explicit:
                        raise StopIteration(None)
                    raise StopIteration()
                except StopIteration as error:
                    result.append(str(error))
            return repr(result) + repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("exception", ["StopIteration", "RuntimeError", "KeyError"])
@pytest.mark.parametrize("failing, expected", [(False, "label:7"), (True, "<exception str() failed>")])
def test_uncaught_payload_reporting_keeps_the_original_exception(exception, failing, expected):
    result = LLVM().run_source(f'''
        from pyjs.native import gc_collect
        class Label:
            def __str__(self) -> str:
                gc_collect()
                if {failing}:
                    raise ValueError("formatter")
                return "label:7"
            def __repr__(self) -> str:
                return self.__str__()
        def main() -> int:
            raise {exception}(Label())
    ''')
    assert result.returncode != 0
    assert result.stderr.endswith(exception + ": " + expected + "\n")


@pytest.mark.parametrize("exception", ["StopIteration", "RuntimeError"])
def test_library_payload_reporting_can_fail_and_then_recover(tmp_path, exception):
    source = f'''
        from pyjs.native import gc_collect
        class Label:
            def __init__(self, broken: bool): self.broken = broken
            def __str__(self) -> str:
                gc_collect()
                if self.broken:
                    raise ValueError("formatter")
                return "payload"
        def main(mode: int) -> str:
            if mode != 0:
                raise {exception}(Label(mode == 2))
            return "ready"
    '''
    with closing(LLVM().compile_library(source, directory=tmp_path)) as library:
        for mode, expected in [(1, "payload"), (2, "<exception str() failed>"), (1, "payload")]:
            with pytest.raises(LLVMRuntimeError) as caught:
                library.render(mode)
            assert caught.value.exception_type == exception
            assert caught.value.native_traceback.endswith(exception + ": " + expected + "\n")
            assert library.render(0) == "ready"


@pytest.mark.parametrize("exception", ["StopIteration", "ValueError", "KeyError"])
@pytest.mark.parametrize("optimize", [0, 2])
def test_lazy_formatting_allocation_failure_keeps_the_caught_payload(tmp_path, optimize, exception):
    source = transpile_llvm(f'''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining
        def main() -> int:
            text = "payload" * 100
            payload = {"text" if exception == "StopIteration" else "[text]"}
            expected = str(payload)
            try:
                raise {exception}(payload)
            except {exception} as error:
                stages = 1
                failure = 0
                while failure <= stages:
                    caught = False
                    result = "unchanged"
                    arm(1000 if failure == 0 else failure)
                    try:
                        result = str(error)
                    except MemoryError:
                        caught = True
                    if failure == 0:
                        stages = 1000 - remaining()
                    arm(0)
                    gc_collect()
                    assert stages > 0
                    assert caught == (failure != 0)
                    {"assert error.value is payload" if exception == "StopIteration" else "assert payload == [text]"}
                    assert result == ("unchanged" if caught else expected)
                    assert str(error) == expected
                    failure += 1
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_stop_iteration_preserves_payload_through_unwinding_and_collection(tmp_path, optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold
        from pyjs import int8

        def fail(value: object) -> None:
            raise StopIteration(value)

        def recover(value: object) -> object:
            try:
                fail(value)
            except StopIteration as error:
                gc_collect()
                try:
                    raise ValueError("another error")
                except ValueError:
                    gc_collect()
                return error.value

        def main() -> str:
            gc_set_threshold(1)
            result: list[object] = []
            inputs: list[object] = [None, 7, "hello", [1, 2], False,
                                    -0.0, b"bytes", (3, "four"), {"five": 5}]
            for value in inputs:
                result.append(recover(value))
            try:
                raise StopIteration(int(int8(130)))
            except StopIteration as represented:
                value = represented.value
                assert isinstance(value, int)
                assert value == -126
            try:
                raise StopIteration()
            except StopIteration as empty:
                assert empty.value is None
                assert str(empty) == ""
            try:
                iterator = iter([1])
                next(iterator)
                next(iterator)
            except StopIteration as exhausted:
                assert exhausted.value is None
            gc_collect()
            return repr(result)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("origin", ["raised", "generator"])
def test_stop_iteration_value_repeated_attribute_reads_preserve_narrowed_layout(tmp_path, optimize, origin):
    statement = "raise StopIteration(value)" if origin == "raised" else "next(stream)"
    result = LLVM().assert_matches_python(f'''
        from collections.abc import Generator
        from pyjs.native import gc_collect, gc_set_threshold

        class Box:
            def __init__(self, text: str):
                self.text = text

        def source(value: object) -> Generator[object, object, object]:
            yield None
            return value

        def read(value: object) -> str:
            stream = source(value)
            next(stream)
            try:
                {statement}
            except StopIteration as error:
                gc_collect()
                if isinstance(error.value, str):
                    return error.value
                if isinstance(error.value, bytes):
                    return error.value.decode()
                if isinstance(error.value, bool):
                    return str(not error.value)
                if isinstance(error.value, int):
                    return str(int(error.value) + 1)
                if isinstance(error.value, float):
                    return str(error.value + 0.5)
                if isinstance(error.value, Box):
                    return error.value.text
                if error.value is None:
                    return 'none'
            return 'wrong payload'

        def main() -> str:
            gc_set_threshold(1)
            values: list[object] = ['done', b'bytes', True, 7, 1.5, Box('box'), None]
            return '|'.join(read(value) for value in values)
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("scalar", ["int8", "float32", "int64"])
@pytest.mark.parametrize("injected", [False, True])
def test_explicit_stop_iteration_payload_cannot_erase_scalar_width(scalar, injected):
    statement = (f"stream.throw(StopIteration({scalar}(127)))" if injected else
                 f"raise StopIteration({scalar}(127))")
    with pytest.raises(LLVMUnsupported, match="explicit int\\(\\) or float\\(\\) conversion") as caught:
        transpile_llvm(f'''
            from pyjs import {scalar}
            def values():
                yield 1
            def main() -> str:
                stream = values()
                try:
                    {statement}
                except StopIteration as error:
                    return str(error)
                return "missing"
        ''')
    assert caught.value.node.lineno is not None


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("scalar, ordinary", [("int8", "float"), ("float32", "int")])
@pytest.mark.parametrize("local", [False, True])
def test_erased_completion_reads_check_actual_scalar_arm_and_recover(tmp_path, optimize, scalar, ordinary, local):
    source = '''
from collections.abc import Generator, Iterator
from typing import cast
from pyjs import int8, float32
from pyjs.native import gc_collect, gc_set_threshold
def child(mode: int) -> Generator[int, None, SCALAR | str | list[int8] | None | ORDINARY]:
    yield 1
    if mode == 0:
        return SCALAR(127)
    if mode == 1:
        return "safe"
    if mode == 2:
        return [int8(127)]
    if mode == 4:
        return ORDINARY(4)
    return None
def identity(value: int) -> int:
    return value
def wrap(mode: int, wrapped: bool) -> Iterator[int]:
    stream = child(mode)
    if wrapped:
        return map(identity, stream)
    return stream
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    for wrapped in [False, True]:
        for mode in range(5):
            stream = wrap(mode, wrapped)
            assert next(stream) == 1
            for exhausted in [False, True]:
                try:
                    next(stream)
                except StopIteration as error:
                    gc_collect()
                    events.append(str(error))
                    try:
                        # Read the actual payload, not the active exception.
                        LOCAL
                        if mode == 2 and not exhausted:
                            events.append(str(cast(list[int8], READ)[0] + 1))
                        elif isinstance(READ, int):
                            events.append(str(READ + 1))
                        elif isinstance(READ, float):
                            events.append(str(READ + 1.0))
                        else:
                            events.append(str(READ))
                    except TypeError as rejected:
                        events.append(str(rejected))
                    gc_collect()
            assert next(stream, None) is None
    return str(events)
'''.replace("SCALAR", scalar).replace("ORDINARY", ordinary)
    source = source.replace("LOCAL", "value = error.value" if local else "pass")
    source = source.replace("READ", "value" if local else "error.value")
    message = ("StopIteration.value cannot erase represented scalar arithmetic; "
               "convert the completion explicitly or use typed delegation")
    # CPython keeps numeric subclasses in object payloads. Model the native
    # checked boundary explicitly, comparing every other effect and recovery.
    oracle = source.replace("                        # Read", f'''                        if isinstance(error.value, {scalar}):
                            raise TypeError({message!r})
                        # Read''', 1)
    expected = run_python(oracle + "\nprint(main(), end='')\n")
    actual = LLVM().run_source(source, directory=tmp_path, optimize=optimize,
                               sanitizers=("address", "undefined"))
    assert expected.returncode == actual.returncode == 0, (expected.stderr, actual.stderr)
    assert actual.stdout == expected.stdout
    assert not actual.stderr and not expected.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_payload_is_not_replaced_by_its_string_and_survives_a_suspended_handler(tmp_path, optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Done(StopIteration):
            pass

        class Box:
            def __init__(self, value: int):
                self.value = value

            def __str__(self) -> str:
                gc_collect()
                return "box:" + str(self.value)

        def fail() -> None:
            raise Done(Box(42))

        def values():
            try:
                fail()
            except StopIteration as error:
                yield str(error)
                gc_collect()
                try:
                    raise ValueError("nested")
                except ValueError:
                    gc_collect()
                payload = error.value
                assert isinstance(payload, Box)
                yield str(payload.value)

        def reraised() -> None:
            try:
                raise StopIteration([3, 4])
            except StopIteration:
                gc_collect()
                raise

        def main() -> str:
            gc_set_threshold(1)
            source = values()
            result = [next(source)]
            gc_collect()
            result.append(next(source))
            assert next(source, None) is None
            try:
                reraised()
            except StopIteration as error:
                gc_collect()
                result.append(repr(error.value))
            return repr(result)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_throw_preserves_original_value_for_new_and_closed_generators(tmp_path, optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        def values():
            yield 1

        def main() -> str:
            result: list[object] = []
            for closed in [False, True]:
                source = values()
                if closed:
                    source.close()
                try:
                    source.throw(StopIteration(7))
                except StopIteration as error:
                    gc_collect()
                    result.append(error.value)
            return repr(result)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_unobserved_throw_payload_still_prepares_its_boxing_runtime(tmp_path, optimize):
    LLVM().assert_matches_python('''
        def values():
            yield 1

        def main() -> str:
            source = values()
            try:
                source.throw(StopIteration(7))
            except StopIteration as error:
                return str(error)
            return "missing"
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_payload_preparation_failures_do_not_publish_a_partial_exception(tmp_path, optimize):
    source = transpile_llvm('''
        from pyjs.native import gc_collect
        from tests.native.allocation_support import arm, remaining

        def values():
            yield 1

        def main() -> int:
            for injected in [False, True]:
                stages = 0
                failure = 0
                while failure <= stages:
                    source = values()
                    caught = False
                    arm(1000 if failure == 0 else failure)
                    try:
                        if injected:
                            source.throw(StopIteration(7))
                        else:
                            raise StopIteration(7)
                    except StopIteration as error:
                        if failure == 0:
                            stages = 1000 - remaining()
                        arm(0)
                        value = error.value
                        assert isinstance(value, int)
                        assert value == 7
                    except MemoryError:
                        caught = True
                    if failure == 0:
                        assert stages > 0
                    arm(0)
                    gc_collect()
                    # Trace extension is best-effort after throw() has
                    # prepared the payload. Its failure preserves StopIteration.
                    if failure == 0:
                        assert not caught
                    elif failure == 1:
                        assert caught
                    if injected and caught:
                        assert next(source) == 1
                    failure += 1
            return 0
    ''')
    executable = LLVM().compile(_fail_allocations(source, True), tmp_path, optimize=optimize)
    result = subprocess.run([executable], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, (result.stdout, result.stderr)
