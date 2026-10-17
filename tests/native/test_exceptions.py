import pytest

from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("expression", ["Error()", "Error('message')"])
def test_stored_application_exception_has_allocation_diagnostic(expression):
    with pytest.raises(LLVMUnsupported, match="LLVM cannot allocate class Error at line"):
        transpile_llvm(f'''
            from pyjs import int8

            class Error(Exception):
                pass
            def main() -> str:
                error = {expression}
                # Tuple comparison keeps this allocation local in a GC-using
                # function, reaching the formerly crashing preparation path.
                return str(((error,) == (int8(3),), (error,) != (int8(3),)))
        ''')


def test_llvm_traps_on_reached_value_errors():
    execution = LLVM().run_source(
        """
        def require_positive(value: int) -> int:
            if value <= 0:
                raise ValueError("value must be positive")
            return value

        def main() -> int:
            return require_positive(0)
        """,
        filename="native_failure.py",
    )

    assert execution.returncode < 0
    assert execution.stderr == (
        "Traceback (native PyJS):\n"
        '  File "native_failure.py", line 8, in main\n'
        '  File "native_failure.py", line 4, in require_positive\n'
        "ValueError: value must be positive\n"
    )


def test_llvm_reports_dynamic_exception_messages_from_string_programs():
    execution = LLVM().run_source(
        """
        def main() -> str:
            code = 503
            raise RuntimeError("service unavailable: " + str(code))
        """,
        filename="service.py",
    )

    assert execution.returncode < 0
    assert execution.stderr == (
        "Traceback (native PyJS):\n"
        '  File "service.py", line 4, in main\n'
        "RuntimeError: service unavailable: 503\n"
    )


def test_llvm_catches_typed_exceptions_across_generated_calls():
    comparison = LLVM().assert_matches_python(
        """
        def fail(kind: int) -> int:
            if kind == 1:
                raise ValueError("value")
            raise RuntimeError("runtime")

        def main() -> int:
            total = 0
            try:
                fail(1)
            except (TypeError, ValueError):
                total = total + 10
            try:
                try:
                    fail(2)
                except ValueError:
                    total = total + 1
            except Exception:
                total = total + 32
            return total
        """
    )

    assert comparison.native.returncode == 42


def test_llvm_exception_else_and_bare_reraise_match_python():
    comparison = LLVM().assert_matches_python(
        """
        def fail() -> int:
            raise ValueError("value")

        def main() -> int:
            value = 0
            try:
                value = 40
            except ValueError:
                return 1
            else:
                value = value + 2
            try:
                try:
                    fail()
                except ValueError:
                    raise
            except Exception:
                return value
            return 2
        """
    )

    assert comparison.native.returncode == 42


def test_llvm_bound_exception_values_expose_message_and_can_reraise():
    comparison = LLVM().assert_matches_python(
        """
        def fail() -> int:
            raise TypeError("wrong value")

        def main() -> int:
            try:
                try:
                    fail()
                except (TypeError, ValueError) as error:
                    if str(error) == "wrong value":
                        raise error
            except Exception as outer:
                if str(outer) == "wrong value":
                    return 43
            return 1
        """
    )

    assert comparison.native.returncode == 43


def test_llvm_reraised_dynamic_message_survives_gc_unwind():
    execution = LLVM().run_source(
        """
        from pyjs.native import gc_collect, gc_set_threshold

        def fail(code: int) -> int:
            raise ValueError("invalid value: " + str(code))

        def main() -> int:
            gc_set_threshold(1)
            try:
                fail(503)
            except ValueError:
                gc_collect()
                raise
            return 1
        """,
        filename="gc_exception.py",
    )

    assert execution.returncode < 0
    assert execution.stderr == (
        "Traceback (native PyJS):\n"
        '  File "gc_exception.py", line 10, in main\n'
        '  File "gc_exception.py", line 5, in fail\n'
        "ValueError: invalid value: 503\n"
    )


def test_llvm_assertions_raise_catchable_typed_exceptions():
    comparison = LLVM().assert_matches_python(
        """
        def check(value: int) -> int:
            assert value > 0, "positive value required"
            return value

        def main() -> int:
            total = 0
            try:
                check(-1)
            except AssertionError:
                total = total + 40
            assert total == 40
            return total + 2
        """
    )

    assert comparison.native.returncode == 42


def test_llvm_unhandled_assertion_formats_non_string_message():
    execution = LLVM().run_source(
        """
        def main() -> int:
            value = -42
            assert value > 0, value
            return value
        """,
        filename="assertion.py",
    )

    assert execution.returncode < 0
    assert execution.stderr == (
        "Traceback (native PyJS):\n"
        '  File "assertion.py", line 4, in main\n'
        "AssertionError: -42\n"
    )


def test_llvm_unhandled_exception_reports_each_generated_call_frame():
    execution = LLVM().run_source(
        """
        def parse() -> int:
            return 1 // 0

        def service() -> int:
            return parse()

        def main() -> int:
            return service()
        """,
        filename="nested_failure.py",
    )

    assert execution.returncode < 0
    assert execution.stderr == (
        "Traceback (native PyJS):\n"
        '  File "nested_failure.py", line 9, in main\n'
        '  File "nested_failure.py", line 6, in service\n'
        '  File "nested_failure.py", line 3, in parse\n'
        "ZeroDivisionError: division by zero\n"
    )


def test_llvm_finally_runs_for_normal_handled_and_propagating_paths():
    comparison = LLVM().assert_matches_python(
        """
        def propagate(events: list[int]) -> None:
            try:
                events.append(4)
                raise ValueError("failure")
            finally:
                events.append(5)

        def main() -> int:
            normal = 1
            try:
                normal = normal + 2
            finally:
                normal = normal + 3

            handled = 0
            try:
                raise TypeError("handled")
            except TypeError:
                handled = 10
            finally:
                handled = handled + 10

            events: list[int] = []
            try:
                propagate(events)
            except ValueError as error:
                if str(error) == "failure":
                    events.append(6)
            total = 0
            for event in events:
                total += event
            return normal + handled + total + 1
        """
    )

    assert comparison.native.returncode == 42


def test_llvm_finally_preserves_abrupt_exit_semantics():
    comparison = LLVM().assert_matches_python(
        """
        def returned(events: list[int]) -> int:
            value = 7
            try:
                return value
            finally:
                value = 20
                events.append(1)

        def overridden(events: list[int]) -> int:
            try:
                return 2
            finally:
                events.append(2)
                return 9

        def main() -> int:
            events: list[int] = []
            score = returned(events) + overridden(events)
            for value in range(4):
                try:
                    if value == 1:
                        continue
                    if value == 3:
                        break
                    score = score + value
                finally:
                    events.append(value)
            try:
                for value in range(2):
                    break
                score = score + 3
            finally:
                events.append(5)
            total = 0
            for event in events:
                total += event
            return score + total + 7
        """
    )

    assert comparison.native.returncode == 42


def test_llvm_nested_finally_preserves_exceptions_and_rooted_returns():
    comparison = LLVM().assert_matches_python(
        """
        from pyjs.native import gc_collect, gc_set_threshold

        def nested(events: list[int]) -> str:
            try:
                try:
                    return "ship" + "master"
                finally:
                    events.append(2)
                    temporary = "discarded" + " value"
                    gc_collect()
            finally:
                events.append(3)

        def replace_exception(events: list[int]) -> None:
            try:
                try:
                    raise ValueError("original")
                finally:
                    events.append(5)
                    raise TypeError("replacement")
            finally:
                events.append(7)

        def main() -> int:
            gc_set_threshold(1)
            events: list[int] = []
            value = nested(events)
            try:
                replace_exception(events)
            except TypeError as error:
                if str(error) == "replacement":
                    events.append(11)
            total = 0
            for event in events:
                total += event
            return len(value) + total + 4
        """
    )

    assert comparison.native.returncode == 42


def test_llvm_user_exception_subclasses_preserve_type_and_message():
    comparison = LLVM().assert_matches_python(
        """
        class RenderError(ValueError):
            pass

        class CriticalRenderError(RenderError):
            pass

        def fail(critical: bool) -> None:
            if critical:
                raise CriticalRenderError("critical")
            raise RenderError("render")

        def main() -> int:
            caught = 0
            try:
                fail(False)
            except RenderError as error:
                if str(error) == "render":
                    caught = caught + 20
            try:
                fail(True)
            except CriticalRenderError as error:
                if str(error) == "critical":
                    caught = caught + 22
            except RenderError:
                return 1
            return caught
        """
    )

    assert comparison.native.returncode == 42
