import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM, LLVMRuntimeError
from tests.native.allocation_support import run_allocation_case


@pytest.mark.parametrize("optimize", [0, 2])
def test_throw_preserves_represented_yields_send_and_nested_cleanup(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs import int8
        from pyjs.native import gc_collect, gc_set_threshold

        def values(events: list[str]) -> Generator[int8, int8, None]:
            try:
                try:
                    yield int8(1)
                except ValueError as error:
                    gc_collect()
                    events.append(str(error))
                    received: int8 = yield int8(130)
                    yield received
                finally:
                    events.append("inner")
            finally:
                events.append("outer")

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            source = values(events)
            assert next(source) == int8(1)
            assert source.throw(ValueError("x" * 40)) == int8(-126)
            assert source.send(int8(9)) == int8(9)
            source.close()
            assert events == ["x" * 40, "inner", "outer"]
            return repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_throw_phase_handling_for_functions_and_expressions(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        class Done(StopIteration):
            pass

        def values(events: list[str]):
            events.append("started")
            try:
                yield 1
            finally:
                events.append("cleanup")

        def main() -> str:
            events: list[str] = []
            for expression in [False, True]:
                for state in [0, 1, 2, 3]:
                    for stop in [False, True]:
                        source = (value for value in [1]) if expression else values(events)
                        if state == 1 or state == 3:
                            next(source)
                        if state == 2:
                            source.close()
                        if state == 3:
                            assert next(source, None) is None
                        gc_collect()
                        try:
                            if stop:
                                source.throw(Done("stop"))
                            else:
                                source.throw(ValueError("error"))
                        except RuntimeError as error:
                            events.append("runtime:" + str(error))
                        except StopIteration as error:
                            events.append("stop:" + str(error))
                        except ValueError as error:
                            events.append("value:" + str(error))
                        assert next(source, None) is None
                        source.close()
            return repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_throw_classes_and_caught_exceptions_copy_the_callers_snapshot(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Shutdown(BaseException):
            pass

        def values(events: list[str]):
            try:
                yield 1
            except ValueError as error:
                events.append("class:" + str(error))
                yield 2
            except Shutdown as error:
                gc_collect()
                events.append(str(error))
                try:
                    raise ValueError("nested")
                except ValueError:
                    pass
                events.append(str(error))

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            source = values(events)
            next(source)
            assert source.throw(ValueError) == 2
            source.close()
            source = values(events)
            next(source)
            try:
                raise Shutdown("saved")
            except Shutdown as error:
                try:
                    source.throw(error)
                except StopIteration:
                    events.append("exhausted")
                gc_collect()
                events.append(str(error))
            assert events == ["class:", "saved", "saved", "exhausted", "saved"]
            return repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_throw_reentry_and_argument_failure_leave_generator_usable(optimize):
    LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect

        def message(events: list[str]) -> str:
            gc_collect()
            events.append("argument")
            raise TypeError("argument")

        def values(holders: list[Generator[int, None, None]], events: list[str]):
            try:
                holders[0].throw(ValueError("injected"))
            except ValueError as error:
                assert str(error) == "generator already executing"
                events.append(str(error))
            yield 1
            yield 2

        def main() -> str:
            events: list[str] = []
            holders: list[Generator[int, None, None]] = []
            source = values(holders, events)
            holders.append(source)
            for expected in [1, 2]:
                try:
                    source.throw(ValueError(message(events)))
                except TypeError as error:
                    assert str(error) == "argument"
                assert next(source) == expected
            source.close()
            assert events == ["argument", "generator already executing", "argument"]
            return repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_throw_message_allocation_failure_does_not_advance(tmp_path, optimize):
    source = transpile_llvm('''
        from tests.native.allocation_support import arm
        from pyjs.native import gc_collect

        def values():
            yield 1
            yield 2

        def main() -> int:
            source = values()
            assert next(source) == 1
            arm(1)
            try:
                source.throw(ValueError("x" * 4096))
                assert False
            except MemoryError:
                pass
            arm(0)
            gc_collect()
            assert next(source) == 2
            source.close()
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_throw_trace_allocation_failure_preserves_original_error_and_cleanup(tmp_path, optimize):
    source = transpile_llvm('''
        from tests.native.allocation_support import arm

        def values(events: list[int]):
            try:
                yield 1
            finally:
                events.append(2)

        def main() -> int:
            events: list[int] = []
            source = values(events)
            next(source)
            arm(1)
            try:
                source.throw(ValueError("original"))
                assert False
            except ValueError as error:
                assert str(error) == "original"
            arm(0)
            assert events == [2]
            assert next(source, None) is None
            return 0
    ''')
    run_allocation_case(source, tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_throw_context_manager_suppression_and_keyerror_formatting(optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect

        class Resource:
            def __init__(self, events: list[str]):
                self.events = events
            def __enter__(self) -> int:
                return 1
            def __exit__(self, kind: type[BaseException] | None,
                         error: BaseException | None, trace: object) -> bool:
                gc_collect()
                if error is not None:
                    self.events.append(str(error))
                return kind is KeyError

        def values(events: list[str]):
            with Resource(events) as value:
                yield value
            yield 2

        def main() -> str:
            events: list[str] = []
            source = values(events)
            assert next(source) == 1
            assert source.throw(KeyError("missing")) == 2
            assert events == ["'missing'"]
            source.close()
            return repr(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("argument", ["Problem", "Problem()"])
def test_throw_rejects_custom_exception_initializers(argument):
    with pytest.raises(LLVMUnsupported, match="cannot override construction"):
        transpile_llvm(f'''
            class Problem(ValueError):
                def __init__(self):
                    super().__init__("custom")
            def values():
                yield 1
            def main() -> int:
                return values().throw({argument})
        ''')


@pytest.mark.parametrize("decoration", ["", '@llvm.inline("")'])
def test_caught_exception_cannot_escape_through_an_unrelated_throw_method(decoration):
    with pytest.raises(CompilationError, match="only be passed to generator throw"):
        transpile_llvm(f'''
            from pyjs import llvm
            class Holder:
                {decoration}
                def throw(self, value: BaseException) -> None:
                    pass
            def main() -> int:
                try:
                    raise ValueError("caught")
                except ValueError as error:
                    Holder().throw(error)
                return 0
        ''')


@pytest.mark.parametrize("arguments, message", [
    ("", "missing required argument"),
    ('ValueError, "legacy"', "too many positional arguments"),
    ("exception=ValueError()", "positional-only"),
    ("1", "expects BaseException"),
])
def test_throw_call_shape_has_located_diagnostics(arguments, message):
    with pytest.raises(CompilationError, match=message) as caught:
        transpile_llvm(f"def values():\n    yield 1\ndef main() -> int:\n"
                       f"    return values().throw({arguments})\n")
    assert caught.value.lineno == 4


@pytest.mark.parametrize("borrowed", [False, True])
def test_thrown_traceback_keeps_caller_and_suspended_yield(tmp_path, borrowed):
    source = '''
def values():
    yield "first"

def render() -> str:
    source = values()
    next(source)
    return source.throw(ValueError("injected"))
'''
    if borrowed:
        source = source.replace('    return source.throw(ValueError("injected"))', '''    try:
        raise ValueError("injected")
    except ValueError as error:
        return source.throw(error)''')
    library = LLVM().compile_library(source, tmp_path, entry_point="render", filename="throwing.py")
    try:
        for _ in range(2):
            with pytest.raises(LLVMRuntimeError) as caught:
                library.render()
            assert caught.value.native_traceback == (
                'Traceback (native PyJS):\n'
                f'  File "throwing.py", line {11 if borrowed else 8}, in render\n'
                '  File "throwing.py", line 3, in values\n' +
                ('  File "throwing.py", line 9, in render\n' if borrowed else '') +
                'ValueError: injected\n'
            )
    finally:
        library.close()
