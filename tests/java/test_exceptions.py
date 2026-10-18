import builtins
import subprocess
from textwrap import dedent

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.java import JVMUnsupported, transpile_jvm
from pyjs.java.classfile import Bytecode, ClassFile, ExceptionHandler, Method
from tests.backend_semantics import (
    EXCEPTION_CLEANUP_CONTRACT,
    EXCEPTION_CONTROL_FLOW_CONTRACT,
    EXCEPTION_HIERARCHIES,
)
from tests.java.test_android import android_sdk
from tests.java.test_jvm import java
from tests.semantics.helpers import run_python


def run_jvm(source, directory):
    compilation = transpile_jvm(dedent(source), filename="exceptions.py")
    compilation.write(directory)
    return subprocess.run(
        [java(), "-Xmx128m", "-Xverify:all", "-cp", str(directory), "PyjsProgram"],
        capture_output=True, text=True, timeout=30,
    )


def assert_matches_python(source, directory):
    source = dedent(source)
    expected = run_python(source + "\nprint(main())\n")
    assert expected.returncode == 0, expected.stderr
    actual = run_jvm(source, directory)
    assert actual.stderr == "", actual.stderr
    assert actual.returncode == int(expected.stdout.strip())


@pytest.mark.parametrize("contract", [EXCEPTION_CONTROL_FLOW_CONTRACT, EXCEPTION_CLEANUP_CONTRACT], ids=["handlers", "cleanup"])
def test_shared_exception_contract(tmp_path, contract):
    assert_matches_python(contract.source, tmp_path)


@pytest.mark.parametrize("caught", ["ValueError", "(TypeError, ValueError)", "Exception", "BaseException"])
def test_propagation_and_handler_order(tmp_path, caught):
    assert_matches_python(f'''
        def fail() -> None:
            raise ValueError("failed")

        def bridge() -> None:
            fail()

        def main() -> int:
            try:
                bridge()
            except RuntimeError:
                return 1
            except {caught} as error:
                return 42 if str(error) == "failed" else 2
            except ValueError:
                return 3
            return 4
    ''', tmp_path)


def test_reraise_preserves_outer_snapshot(tmp_path):
    assert_matches_python('''
        def main() -> int:
            try:
                try:
                    raise ValueError("outer")
                except ValueError as error:
                    try:
                        raise ValueError("inner")
                    except ValueError as other:
                        if str(other) != "inner":
                            return 1
                        error = other
                    raise
            except ValueError as saved:
                return 42 if str(saved) == "outer" else 2
            return 3
    ''', tmp_path)


def test_explicit_reraise_and_empty_message(tmp_path):
    assert_matches_python('''
        def main() -> int:
            try:
                try:
                    raise TypeError()
                except TypeError as error:
                    raise error
            except TypeError as saved:
                return 42 if str(saved) == "" else 1
            return 2
    ''', tmp_path)


def test_else_errors_skip_own_handlers(tmp_path):
    assert_matches_python('''
        def main() -> int:
            score = 0
            try:
                try:
                    score = 1
                except ValueError:
                    return 2
                else:
                    raise ValueError("else")
                finally:
                    score += 10
            except ValueError:
                return score
            return 3
    ''', tmp_path)


def test_finally_preserves_return_and_loop_exits(tmp_path):
    assert_matches_python('''
        def saved(events: list[int]) -> int:
            value = 7
            try:
                return value
            finally:
                value = 20
                events.append(1)

        def replaced(events: list[int]) -> int:
            try:
                return 2
            finally:
                events.append(2)
                return 9

        def main() -> int:
            events: list[int] = []
            score = saved(events) + replaced(events)
            for value in range(4):
                try:
                    if value == 1:
                        continue
                    if value == 3:
                        break
                    score += value
                finally:
                    events.append(value)
            for event in events:
                score += event
            return score
    ''', tmp_path)


def test_finally_replaces_error_and_unwinds_outer_cleanup(tmp_path):
    assert_matches_python('''
        def fail(events: list[int]) -> None:
            try:
                try:
                    raise ValueError("original")
                finally:
                    events.append(5)
                    raise TypeError("replacement")
            finally:
                events.append(7)

        def main() -> int:
            events: list[int] = []
            try:
                fail(events)
            except ValueError:
                return 1
            except TypeError as error:
                if str(error) == "replacement":
                    events.append(11)
            total = 0
            for event in events:
                total += event
            return total
    ''', tmp_path)


def test_finally_return_suppresses_exception(tmp_path):
    assert_matches_python('''
        def main() -> int:
            try:
                raise ValueError("suppressed")
            finally:
                return 42
    ''', tmp_path)


def test_assertion_message_is_lazy_and_catchable(tmp_path):
    assert_matches_python('''
        def message(events: list[int]) -> str:
            events.append(1)
            return "failed assertion"

        def main() -> int:
            events: list[int] = []
            assert True, message(events)
            try:
                assert False, message(events)
            except Exception as error:
                if str(error) == "failed assertion":
                    return len(events)
            return 2
    ''', tmp_path)


def test_native_java_exception_crosses_cleanup_and_is_reraised(tmp_path):
    result = run_jvm('''
        from pyjs import jvm
        from pyjs.java import i32

        @jvm.native("java/lang/Integer", name="parseInt")
        def parse(value: str) -> i32: ...

        def main() -> int:
            score = 0
            try:
                try:
                    parse("not an integer")
                except Exception as error:
                    if len(str(error)) > 0:
                        score = 10
                    raise
                finally:
                    score += 5
            except Exception:
                return score
            return 1
    ''', tmp_path)
    assert result.returncode == 15, result.stderr


def test_native_interface_subclass_constructed_inside_try(tmp_path):
    assert_matches_python('''
        from pyjs import jvm

        @jvm.native("java/lang/Runnable", interface=True)
        class Runnable:
            def run(self) -> None: ...

        class Callback(Runnable):
            def run(self) -> None:
                raise ValueError("callback")

        def main() -> int:
            try:
                Callback().run()
            except ValueError as error:
                return 42 if str(error) == "callback" else 1
            return 2
    ''', tmp_path)


def test_exception_runtime_does_not_collide_with_application_classes(tmp_path):
    assert_matches_python('''
        class PythonValueError:
            def __init__(self, value: int):
                self.value = value

        def main() -> int:
            item = PythonValueError(42)
            try:
                raise ValueError("failed")
            except ValueError:
                return item.value
            return 1
    ''', tmp_path)


@pytest.mark.parametrize("name", [
    "ArithmeticError", "ZeroDivisionError", "OverflowError", "LookupError",
    "IndexError", "StopIteration", "MemoryError", "UnicodeError",
    "AttributeError", "RecursionError", "NotImplementedError", "OSError",
    "FileNotFoundError",
])
def test_builtin_exception_hierarchy(tmp_path, name):
    assert_matches_python(f'''
        def main() -> int:
            try:
                raise {name}("message")
            except Exception as error:
                return 42 if str(error) == "message" else 1
            return 2
    ''', tmp_path)


def test_base_exception_is_not_exception(tmp_path):
    assert_matches_python('''
        def main() -> int:
            try:
                raise BaseException("base")
            except Exception:
                return 1
            except:
                return 42
    ''', tmp_path)


@pytest.mark.parametrize(("name", "parent", "sibling"), EXCEPTION_HIERARCHIES)
@pytest.mark.parametrize("arguments", [(), ("",), ("message",)],
                         ids=["omitted", "empty", "message"])
def test_extended_builtin_hierarchy_and_messages(tmp_path, name, parent, sibling, arguments):
    expected = str(getattr(builtins, name)(*arguments))
    argument = repr(arguments[0]) if arguments else ""
    assert_matches_python(f'''
        def main() -> int:
            try:
                try:
                    raise {name}({argument})
                except {sibling}:
                    return 1
                except {parent} as error:
                    if str(error) != {expected!r}:
                        return 2
                    raise
            except {name} as saved:
                return 0 if str(saved) == {expected!r} else 3
            return 4
    ''', tmp_path)


def test_exception_identity_and_hierarchy_checks(tmp_path):
    assert_matches_python('''
        def main() -> int:
            try:
                raise ZeroDivisionError("zero")
            except Exception as error:
                if not isinstance(error, ArithmeticError):
                    return 1
                if isinstance(error, ValueError):
                    return 2
                try:
                    raise error
                except Exception as saved:
                    return 42 if saved is error else 3
            return 4
    ''', tmp_path)


@pytest.mark.parametrize(("native_type", "expected"), [
    ("java/lang/NullPointerException", 12),
    ("java/io/IOException", 12),
    ("java/lang/AssertionError", 13),
])
def test_native_exception_and_error_boundaries(tmp_path, native_type, expected):
    helper = ClassFile("NativeFailure")
    code = Bytecode()
    code.throw_new(helper, native_type)
    helper.add_method(Method(0x0009, "fail", "()V", code.render(), 2, 0))
    (tmp_path / "NativeFailure.class").write_bytes(helper.render())
    result = run_jvm('''
        from pyjs import jvm

        @jvm.native("NativeFailure")
        def fail() -> None: ...

        def main() -> int:
            score = 0
            try:
                try:
                    fail()
                finally:
                    score = 10
            except Exception as error:
                return score + 2 if str(error) == "" else 1
            except BaseException:
                return score + 3
            return 4
    ''', tmp_path)
    assert result.returncode == expected, result.stderr


def test_classfile_typed_exception_table(tmp_path):
    helper = ClassFile("NativeCatch")
    code = Bytecode()
    code.throw_new(helper, "java/lang/NullPointerException")
    end = len(code.code)
    code.emit(0x57)
    code.emit(0x10, bytes((42,)))
    code.emit(0x85)
    code.emit(0xAD)
    helper.add_method(Method(
        0x0009, "value", "()J", code.render(), 2, 0,
        exception_handlers=(ExceptionHandler(0, end, end, "java/lang/Exception"),),
    ))
    (tmp_path / "NativeCatch.class").write_bytes(helper.render())
    result = run_jvm('''
        from pyjs import jvm
        @jvm.native("NativeCatch")
        def value() -> int: ...
        def main() -> int:
            return value()
    ''', tmp_path)
    assert result.returncode == 42, result.stderr


@pytest.mark.parametrize("handler", [
    ExceptionHandler(0, 0, 0), ExceptionHandler(-1, 1, 0),
    ExceptionHandler(0, 2, 0), ExceptionHandler(0, 1, 1),
])
def test_classfile_rejects_invalid_exception_ranges(handler):
    helper = ClassFile("Invalid")
    helper.add_method(Method(0x0009, "value", "()V", b"\xb1", 0, 0,
                             exception_handlers=(handler,)))
    with pytest.raises(ValueError, match="invalid JVM exception handler range"):
        helper.render()


def test_exception_regions_compile_to_android_dex(tmp_path):
    android_jar, d8 = android_sdk()
    classes = tmp_path / "classes"
    transpile_jvm(EXCEPTION_CLEANUP_CONTRACT.source).write(classes)
    dex = tmp_path / "dex"
    dex.mkdir()
    result = subprocess.run(
        [str(d8), "-JXmx256m", "--lib", str(android_jar), "--min-api", "21",
         "--output", str(dex), *(str(path) for path in classes.glob("*.class"))],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert (dex / "classes.dex").is_file()


@pytest.mark.parametrize("name", ["KeyError", "UnicodeDecodeError"])
def test_unsupported_exception_payloads_have_diagnostics(name):
    with pytest.raises(JVMUnsupported, match=f"{name} construction and matching"):
        transpile_jvm(f'def main() -> int:\n    raise {name}("error")\n')


def test_custom_exception_has_focused_diagnostic():
    with pytest.raises(JVMUnsupported, match="exceptions require a supported builtin type"):
        transpile_jvm('''
            class InvalidNote(ValueError):
                pass
            def main() -> int:
                raise InvalidNote("invalid")
        ''')


def test_non_string_payload_has_focused_diagnostic():
    with pytest.raises(JVMUnsupported, match="exception messages must be strings"):
        transpile_jvm('''
            def main() -> int:
                raise ValueError(42)
        ''')


def test_context_managers_have_focused_diagnostic():
    with pytest.raises(CompilationError, match="JVM context-manager regions are not implemented"):
        transpile_jvm('''
            def main() -> int:
                with missing():
                    return 1
        ''')
