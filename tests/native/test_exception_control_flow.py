import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import (
    ASSERT_BOOLEAN_FLOW_CONTRACT,
    ASSERT_CAPTURE_CONTRACT,
    ASSERT_FAILURE_CONTRACT,
    ASSERT_NARROWING_CONTRACT,
    EXCEPTION_CLEANUP_CONTRACT,
    EXCEPTION_CONTROL_FLOW_CONTRACT,
    KEY_ERROR_CONTRACT,
    RUNTIME_EXCEPTION_CONTRACT,
    SCALAR_EXCEPTION_MESSAGE_CONTRACT,
)


@pytest.mark.parametrize("optimize", [0, 2])
def test_global_narrowing_without_exception_handlers(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        VALUE: str | None = "value"
        def main() -> int:
            if isinstance(VALUE, str):
                return 42
            return 0
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("contract", [ASSERT_NARROWING_CONTRACT, ASSERT_FAILURE_CONTRACT, ASSERT_CAPTURE_CONTRACT, ASSERT_BOOLEAN_FLOW_CONTRACT])
def test_shared_assert_narrowing_contract(tmp_path, optimize, contract):
    result = LLVM().assert_matches_python(
        contract.source, directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert result.native.returncode == 0
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_assert_narrows_generator_input_but_next_still_sends_none(tmp_path, optimize):
    result = LLVM().assert_matches_python('''
        from collections.abc import Generator
        from pyjs.native import gc_collect, gc_set_threshold
        class Box:
            def __init__(self, value: str): self.value = value
        def values() -> Generator[str, Box, None]:
            received = yield "ready"
            assert received is not None, "missing"
            gc_collect()
            yield received.value
        def main() -> str:
            gc_set_threshold(1)
            source = values()
            first = next(source)
            second = source.send(Box("kept"))
            invalid = values()
            next(invalid)
            try:
                next(invalid)
            except AssertionError as error:
                return first + second + str(error)
            return "assertion omitted"
    ''', directory=tmp_path, optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("contract", [EXCEPTION_CONTROL_FLOW_CONTRACT, EXCEPTION_CLEANUP_CONTRACT, RUNTIME_EXCEPTION_CONTRACT, KEY_ERROR_CONTRACT, SCALAR_EXCEPTION_MESSAGE_CONTRACT], ids=["handlers", "cleanup", "runtime", "key-error", "scalar-message"])
def test_shared_exception_control_flow_contract(tmp_path, optimize, contract):
    result = LLVM().assert_matches_python(
        contract.source, directory=tmp_path, optimize=optimize,
        sanitizers=("address", "undefined"),
    )
    assert result.native.returncode == 0


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize(("kind", "initial"), [("str", "'x'"), ("int", "3"), ("float", "1.5"), ("bool", "True")])
@pytest.mark.parametrize("region", ["finally", "else"])
def test_cleanup_reads_use_post_write_optional_state(kind, initial, region, optimize):
    suffix = "finally:" if region == "finally" else 'except ValueError:\n                return "error"\n            else:'
    LLVM().assert_matches_python(f'''
        def read(value: {kind} | None, clear: bool) -> str:
            if value is None:
                return "absent"
            result = ""
            try:
                if clear:
                    value = None
            {suffix}
                result = str(value is None)
            return result
        def main() -> str:
            return read({initial}, True) + read({initial}, False) + read(None, True)
    ''', optimize=optimize, sanitizers=("address", "undefined"))


@pytest.mark.parametrize("optimize", [0, 2])
def test_nested_handlers_and_callbacks_preserve_pending_exception(tmp_path, optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        def cleanup() -> None:
            try:
                raise KeyError("callback")
            except KeyError:
                gc_collect()

        def fail(events: list[str], explicit: bool, size: int) -> None:
            try:
                raise ValueError("original:" + "x" * size)
            except ValueError as outer:
                try:
                    raise TypeError("inner")
                except TypeError as inner:
                    events.append(str(inner))
                    events.append("observed:" + str(outer))
                    if explicit:
                        raise outer
                cleanup()
                gc_collect()
                events.append(str(outer))
                if size > 0:
                    raise

        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            for explicit in [False, True]:
                try:
                    fail(events, explicit, 30)
                except ValueError as error:
                    events.append("caught:" + str(error))
            return "|".join(events)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_abrupt_cleanup_uses_its_own_enclosing_handler(tmp_path, optimize):
    LLVM().assert_matches_python('''
        def fail(flag: bool, events: list[str]) -> int:
            try:
                try:
                    return 7
                except ValueError:
                    events.append("wrong inner handler")
            finally:
                events.append("cleanup")
                if flag:
                    raise ValueError("replacement")
            return 3

        def main() -> str:
            events: list[str] = []
            try:
                fail(True, events)
            except ValueError as error:
                events.append(str(error))
            return "|".join(events)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_lazy_assertion_messages_and_truthiness(tmp_path, optimize):
    LLVM().assert_matches_python('''
        def message(events: list[str]) -> str:
            events.append("message")
            return "failure"

        def main() -> str:
            events: list[str] = []
            assert "present", message(events)
            try:
                assert 0, message(events)
            except AssertionError as error:
                events.append(str(error))
            try:
                assert False, 42
            except AssertionError as error:
                events.append(str(error))
            return "|".join(events)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_conditional_assertion_messages_run_only_after_a_failed_test(tmp_path, optimize):
    LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
def condition(events: list[str], name: str, outcome: bool, fail: bool) -> bool:
    events.append(name)
    if fail:
        raise ValueError(name)
    return outcome
def message(events: list[str], name: str) -> str:
    gc_collect()
    events.append(name)
    return name
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    for attempt in range(6):
        try:
            assert condition(events, "test", attempt == 0 or attempt == 3, attempt == 5), (
                message(events, "yes")
                if condition(events, "message", attempt == 1, attempt >= 3)
                else message(events, "no")
            )
        except AssertionError as error:
            events.append("assert:" + str(error))
        except ValueError as error:
            events.append("value:" + str(error))
        finally:
            events.append("cleanup")
    return "|".join(events)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_list_assertions_preserve_truthiness_and_lazy_messages(tmp_path, optimize):
    LLVM().assert_matches_python('''
from pyjs.native import gc_collect, gc_set_threshold
def values(events: list[str], full: bool) -> list[int]:
    events.append("values:" + str(full))
    gc_collect()
    result: list[int] = []
    if full:
        result.append(1)
    return result
def message(events: list[str]) -> str:
    events.append("message")
    return "empty"
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    items = [1]
    assert items, message(events)
    items.clear()
    try:
        assert items, message(events) if len(events) == 0 else "unexpected"
    except AssertionError as error:
        events.append(str(error))
    assert values(events, True), message(events)
    try:
        assert values(events, False), message(events)
    except AssertionError as error:
        events.append(str(error))
    return "|".join(events)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_length_based_assertions_validate_the_length_before_the_message(tmp_path, optimize):
    LLVM().assert_matches_python('''
class Sized:
    def __init__(self, size: int, events: list[str]):
        self.size = size
        self.events = events
    def __len__(self) -> int:
        self.events.append("length:" + str(self.size))
        return self.size
def message(events: list[str]) -> str:
    events.append("message")
    return "empty"
def main() -> str:
    events: list[str] = []
    for size in [1, 0, -1]:
        try:
            assert Sized(size, events), message(events)
        except (AssertionError, ValueError) as error:
            events.append(str(error))
    return "|".join(events)
''', directory=tmp_path, optimize=optimize)


def test_length_based_assertions_reject_non_integer_lengths():
    with pytest.raises(LLVMUnsupported, match="__len__ must return an integer"):
        transpile_llvm('''
class Sized:
    def __len__(self) -> float:
        return 1.5
def main() -> int:
    assert Sized()
    return 0
''')


@pytest.mark.parametrize("annotation, result", [("int", "1"), ("float", "1.5")])
@pytest.mark.parametrize("condition", ["assert Condition()", "if Condition(): return 1"])
def test_truth_conditions_reject_non_boolean_bool_results(annotation, result, condition):
    with pytest.raises(LLVMUnsupported, match="__bool__ must return bool") as caught:
        transpile_llvm(f'''
class Condition:
    def __bool__(self) -> {annotation}:
        return {result}
def main() -> int:
    {condition}
    return 0
''', filename="invalid_bool.py")
    assert str(caught.value) == (
        "LLVM __bool__ must return bool at line 2"
    )


@pytest.mark.parametrize("optimize", [0, 2])
def test_boolean_protocol_conditions_evaluate_once_and_keep_messages_lazy(tmp_path, optimize):
    LLVM().assert_matches_python('''
class Condition:
    def __init__(self, value: bool, events: list[str]):
        self.value = value
        self.events = events
    def __bool__(self) -> bool:
        self.events.append("bool:" + str(self.value))
        return self.value
def message(events: list[str]) -> str:
    events.append("message")
    return "false"
def main() -> str:
    events: list[str] = []
    for value in [True, False]:
        condition = Condition(value, events)
        if condition:
            events.append("yes")
        else:
            events.append("no")
        try:
            assert condition, message(events)
        except AssertionError as error:
            events.append(str(error))
    return "|".join(events)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_base_exception_is_not_an_exception_and_bare_handler_catches_it(tmp_path, optimize):
    LLVM().assert_matches_python('''
        class Shutdown(BaseException):
            pass

        def main() -> str:
            events: list[str] = []
            try:
                raise Shutdown("stopped")
            except Exception:
                events.append("wrong")
            except BaseException as error:
                events.append(str(error))
            try:
                raise BaseException("bare")
            except:
                events.append("caught")
            return "|".join(events)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
def test_virtual_calls_and_partial_arguments_unwind_gc_frames(tmp_path, optimize):
    LLVM().assert_matches_python('''
        from pyjs.native import gc_collect, gc_set_threshold

        class Service:
            def read(self) -> str:
                return "base"

        class Broken(Service):
            def read(self) -> str:
                raise RuntimeError("service " + "failed")

        def combine(left: str, right: str) -> str:
            return left + right

        def render(service: Service) -> str:
            return combine("temporary " + "prefix", service.read())

        def main() -> str:
            gc_set_threshold(1)
            messages: list[str] = []
            for index in range(10):
                try:
                    render(Broken())
                except RuntimeError as error:
                    gc_collect()
                    messages.append(str(error))
            gc_collect()
            return "|".join(messages)
    ''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("method", ["__init__", "__str__", "__new__"])
def test_custom_exception_overrides_are_rejected_instead_of_skipped(method):
    definition = {
        "__init__": 'def __init__(self, message: str): self.message = message',
        "__str__": 'def __str__(self) -> str: return "custom"',
        "__new__": 'def __new__(cls, message: str): return ValueError(message)',
    }[method]
    with pytest.raises(LLVMUnsupported, match="cannot override"):
        transpile_llvm(f'''
class Error(ValueError):
    {definition}

def main() -> str:
    raise Error("message")
''')


def test_keyword_exception_messages_are_not_silently_discarded():
    with pytest.raises(CompilationError, match="positional message"):
        transpile_llvm('''
def main() -> int:
    raise ValueError(message="lost")
''')


def test_exception_binding_is_not_merged_into_surrounding_scope():
    with pytest.raises(CompilationError, match="Name 'error' is not defined"):
        transpile_llvm('''
def main() -> str:
    try:
        raise ValueError("message")
    except ValueError as error:
        pass
    return str(error)
''')


def test_handler_shadowing_is_rejected_until_unbound_local_tracking():
    with pytest.raises(CompilationError, match="cannot shadow"):
        transpile_llvm('''
def main() -> str:
    error = "before"
    try:
        raise ValueError("message")
    except ValueError as error:
        pass
    return error
''')


@pytest.mark.parametrize("explicit", [False, True])
def test_explicit_reraise_adds_its_site_but_bare_raise_preserves_trace(explicit):
    source = f'''
def fail() -> int:
    raise ValueError("original")

def main() -> int:
    try:
        fail()
    except ValueError as error:
        raise {"error" if explicit else ""}
    return 0
'''
    result = LLVM().run_source(source, filename="reraised.py")
    assert result.returncode < 0
    added = '  File "reraised.py", line 9, in main\n' if explicit else ""
    assert result.stderr == (
        "Traceback (native PyJS):\n" + added
        + '  File "reraised.py", line 7, in main\n'
        + '  File "reraised.py", line 3, in fail\n'
        + "ValueError: original\n"
    )


@pytest.mark.parametrize("optimize", [0, 2])
def test_void_returns_evaluate_before_finally_without_void_block_arguments(tmp_path, optimize):
    LLVM().assert_matches_python('''
        def action(events: list[str]) -> None:
            events.append("call")

        def returned(events: list[str], kind: int) -> None:
            try:
                if kind == 0:
                    return
                if kind == 1:
                    return None
                return action(events)
            finally:
                events.append("cleanup")

        def main() -> str:
            events: list[str] = []
            for kind in range(3):
                returned(events, kind)
            return "|".join(events)
    ''', directory=tmp_path, optimize=optimize)
