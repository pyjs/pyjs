import subprocess
import sys

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import LLVMUnsupported, transpile_llvm
from pyjs.tooling.llvm import LLVM
from tests.backend_semantics import CONTEXT_MANAGER_CONTRACT
from tests.native.allocation_support import run_allocation_case

MANAGER = '''
from pyjs.native import gc_collect, gc_set_threshold

class Scope:
    def __init__(self, events: list[str], name: str, suppress: bool = False,
                 fail_enter: bool = False, fail_exit: bool = False):
        self.events = events
        self.name = name
        self.suppress = suppress
        self.fail_enter = fail_enter
        self.fail_exit = fail_exit

    def __enter__(self) -> str:
        self.events.append("enter:" + self.name)
        if self.fail_enter:
            raise ValueError("enter failed")
        return self.name

    def __exit__(self, kind: type[BaseException] | None,
                 value: BaseException | None, traceback: object) -> bool:
        gc_collect()
        state = "normal"
        if value is not None:
            assert kind is not None and traceback is not None
            state = str(value)
        else:
            assert kind is None and traceback is None
        self.events.append("exit:" + self.name + ":" + state)
        if self.fail_exit:
            raise RuntimeError("exit failed")
        return self.suppress
'''


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("typed", [False, True])
def test_exit_type_token_and_value_identity_is_not_snapshot_identity(optimize, typed):
    kind_type = "type[BaseException] | None" if typed else "object | None"
    value_type = "BaseException | None" if typed else "object | None"
    result = LLVM().assert_matches_python(f'''
        from pyjs.native import gc_collect, gc_set_threshold
        class Scope:
            def __init__(self, events: list[str], suppress: bool):
                self.events = events
                self.suppress = suppress
            def __enter__(self) -> None: pass
            def __exit__(self, kind: {kind_type}, value: {value_type}, trace: object) -> bool:
                gc_collect()
                self.events.append(repr((kind is value, value is kind,
                    kind is not value, value is not kind,
                    kind is value is None, value is kind is None,
                    None is not value is not kind, kind is not value is not None)))
                return self.suppress
        def main() -> str:
            gc_set_threshold(1)
            events: list[str] = []
            with Scope(events, False): pass
            try:
                with Scope(events, False): raise ValueError("body")
            except ValueError:
                events.append("caught")
            with Scope(events, True): raise KeyError("suppressed")
            return "|".join(events)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("optimize", [0, 2])
def test_direct_exit_calls_keep_ordinary_object_identity(optimize):
    result = LLVM().assert_matches_python('''
        class Scope:
            def __enter__(self) -> None: pass
            def __exit__(self, kind: object, value: object, trace: object) -> bool:
                return kind is value
        def main() -> str:
            value = "shared" + str(7)
            items = [1]
            scope = Scope()
            return repr((scope.__exit__(None, None, None),
                scope.__exit__(value, value, None), scope.__exit__(items, items, None),
                scope.__exit__(items, [1], None), scope.__exit__(value, items, None)))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize("comparison", [
    "kind is not value is not trace", "value is trace", "value is value",
    "value is ValueError", "kind is value is self",
])
def test_exit_token_comparison_does_not_enable_other_snapshot_identity(comparison):
    with pytest.raises(CompilationError, match="exception identity comparisons"):
        transpile_llvm(f'''
            class Scope:
                def __enter__(self) -> None: pass
                def __exit__(self, kind: object, value: object, trace: object) -> bool:
                    return {comparison}
            def main() -> int:
                with Scope(): raise ValueError("body")
                return 0
        ''')


def test_caught_exception_cannot_use_an_unrelated_variable_as_a_type_token():
    with pytest.raises(CompilationError, match="exception identity comparisons"):
        transpile_llvm('''
            def main() -> bool:
                kind: object = ValueError
                try: raise ValueError("body")
                except ValueError as value:
                    return kind is value
                return False
        ''')


@pytest.mark.parametrize("expression", [
    "kind is ValueError", "ValueError is kind",
    "kind is not KeyError", "KeyError is not kind",
])
def test_erased_exception_token_identity_compiles_in_a_fresh_process(expression):
    source = f'''
class Scope:
    def __enter__(self) -> None: pass
    def __exit__(self, kind: object, value: object, traceback: object) -> bool:
        return {expression}
def main() -> int:
    with Scope():
        raise ValueError("suppressed")
    return 0
'''
    # Each operand order must be the first compilation in its interpreter.
    # Combining them with `or` can short-circuit the layout-discovery scan.
    script = f'''
from pyjs.tooling.llvm import LLVM
for optimize in (0, 2):
    result = LLVM().assert_matches_python({source!r}, optimize=optimize,
                                         sanitizers=("address", "undefined"))
    assert not result.native.stderr, result.native.stderr
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


@pytest.mark.parametrize('optimize', [0, 2])
def test_shared_context_manager_contract(tmp_path, optimize):
    LLVM().assert_matches_python(CONTEXT_MANAGER_CONTRACT.source, directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize("optimize", [0, 2])
@pytest.mark.parametrize("typed_details", [False, True])
def test_nullable_exit_result_does_not_type_its_borrowed_arguments(tmp_path, optimize, typed_details):
    kind_type = "type[BaseException] | None" if typed_details else "object"
    value_type = "BaseException | None" if typed_details else "object"
    # Opaque borrowed details support presence checks, not object formatting.
    detail = "str(value)" if typed_details else '"exception"'
    source = f'''
from pyjs.native import gc_collect, gc_set_threshold

class Scope:
    def __init__(self, events: list[str], decision: bool | None):
        self.events = events
        self.decision = decision
    def __enter__(self) -> None: pass
    def __exit__(self, kind: {kind_type}, value: {value_type}, trace: object) -> bool | None:
        gc_collect()
        if value is None:
            assert kind is None and trace is None
            self.events.append("normal")
        else:
            assert kind is not None and trace is not None
            self.events.append({detail})
        return self.decision

def use(scope: Scope, fail: bool) -> int:
    with scope:
        if fail:
            raise ValueError("body")
        return 7
    return 9

def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    decisions: list[bool | None] = [None, False, True]
    for decision in decisions:
        for fail in [False, True]:
            try:
                events.append(str(use(Scope(events, decision), fail)))
            except ValueError:
                events.append("caught")
    return "|".join(events)
'''
    result = LLVM().assert_matches_python(source, directory=tmp_path, optimize=optimize,
                                          sanitizers=("address", "undefined"))
    assert not result.native.stderr


@pytest.mark.parametrize('optimize', [0, 2])
def test_concrete_exception_tokens_and_virtual_cleanup(tmp_path, optimize):
    LLVM().assert_matches_python('''
class Scope:
    def __init__(self, events: list[str]):
        self.events = events
    def __enter__(self) -> None:
        self.events.append("base")
    def __exit__(self, kind: object, value: object, traceback: object) -> int:
        self.events.append("base-exit")
        return 0
class Suppressor(Scope):
    def __enter__(self) -> None:
        self.events.append("child")
    def __exit__(self, kind: object, value: object, traceback: object) -> int:
        if kind is ValueError:
            self.events.append("value")
        return 1
def use(scope: Scope) -> None:
    with scope:
        raise ValueError("body")
def main() -> str:
    events: list[str] = []
    use(Suppressor(events))
    try:
        use(Scope(events))
    except ValueError:
        events.append("caught")
    return "|".join(events)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize('optimize', [0, 2])
def test_exit_returning_none_and_ordinary_exit_truth_is_not_used(tmp_path, optimize):
    LLVM().assert_matches_python('''
class Scope:
    def __init__(self, events: list[str]):
        self.events = events
    def __enter__(self) -> None:
        pass
    def __exit__(self, kind: object, value: object, traceback: object) -> None:
        self.events.append("exit")
def main() -> str:
    events: list[str] = []
    with Scope(events) as entered:
        assert entered is None
        events.append("body")
    try:
        with Scope(events):
            raise ValueError("body")
    except ValueError:
        events.append("caught")
    return "|".join(events)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize('optimize', [0, 2])
@pytest.mark.parametrize('result_type, value', [
    ('int', '42'), ('float', '1.25'), ('bool', 'True'), ('str', '"saved"'),
])
def test_return_through_non_suppressing_exit(tmp_path, optimize, result_type, value):
    LLVM().assert_matches_python(f'''
class Scope:
    def __init__(self, events: list[str]):
        self.events = events
    def __enter__(self) -> None:
        pass
    def __exit__(self, kind: object, value: object, traceback: object) -> None:
        self.events.append("exit")
def early(events: list[str]) -> {result_type}:
    with Scope(events), Scope(events):
        return {value}
def main() -> str:
    events: list[str] = []
    result = early(events)
    return str(result) + ":" + "|".join(events)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize('optimize', [0, 2])
def test_nested_context_cleanup_suppression_and_failure_order(tmp_path, optimize):
    LLVM().assert_matches_python(MANAGER + '''
def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    with Scope(events, "a") as value:
        events.append(value)
    with Scope(events, "outer", True), Scope(events, "inner"):
        raise ValueError("body")
    try:
        with Scope(events, "entered"), Scope(events, "failed", False, True):
            events.append("unreachable")
    except ValueError as entering:
        events.append(str(entering))
    try:
        with Scope(events, "exit", False, False, True):
            raise ValueError("replaced")
    except RuntimeError as exiting:
        events.append(str(exiting))
    return "|".join(events)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize('optimize', [0, 2])
def test_return_break_continue_and_outer_finally(tmp_path, optimize):
    LLVM().assert_matches_python(MANAGER + '''
def early(events: list[str]) -> list[str]:
    try:
        with Scope(events, "a"), Scope(events, "b"):
            return ["saved", "value"]
    finally:
        events.append("finally")
        gc_collect()

def main() -> str:
    gc_set_threshold(1)
    events: list[str] = []
    result = early(events)
    for index in range(4):
        with Scope(events, str(index)):
            if index == 0:
                continue
            if index == 2:
                break
            events.append("body")
    return "|".join(events) + ":" + "|".join(result)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize('optimize', [0, 2])
def test_as_target_failure_calls_exit(tmp_path, optimize):
    LLVM().assert_matches_python(MANAGER + '''
def main() -> str:
    events: list[str] = []
    values = ["old"]
    with Scope(events, "binding", True) as values[2]:
        events.append("unreachable")
    assert values[0] == "old"
    return "|".join(events)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize('assignment', [
    'target.value = "new"',
    'with Scope(events, "binding", True) as target.value: pass',
])
def test_property_assignment_failure_runs_context_cleanup(assignment):
    comparison = LLVM().assert_matches_python(MANAGER + '''
class Target:
    @property
    def value(self) -> str:
        return "old"
    @value.setter
    def value(self, value: str) -> None:
        raise ValueError(value)
def main() -> str:
    events: list[str] = []
    target = Target()
    try:
        ''' + assignment + '''
    except ValueError as error:
        events.append("caught:" + str(error))
    return "|".join(events)
''', sanitizers=("address", "undefined"))
    assert comparison.native.stderr == ""


@pytest.mark.parametrize('optimize', [0, 2])
def test_exit_failure_replaces_return_and_reaches_outer_handler(tmp_path, optimize):
    LLVM().assert_matches_python(MANAGER + '''
def early(events: list[str]) -> int:
    with Scope(events, "outer", True):
        with Scope(events, "inner", False, False, True):
            return 7
    return 9
def main() -> str:
    events: list[str] = []
    result = early(events)
    return "|".join(events) + ":" + str(result)
''', directory=tmp_path, optimize=optimize)


@pytest.mark.parametrize('optimize', [0, 2])
def test_allocation_failure_unwinds_context_and_allows_recovery(tmp_path, optimize):
    source = MANAGER + '''
from tests.native.allocation_support import arm
def main() -> int:
    gc_set_threshold(1)
    events: list[str] = []
    text = "value"
    with Scope(events, "allocation", True):
        arm(1)
        failed = text + text
        events.append("unreachable")
    arm(0)
    gc_collect()
    recovered = text + text
    assert recovered == "valuevalue"
    assert len(events) == 2
    assert events[1].startswith("exit:allocation:")
    return 0
'''
    run_allocation_case(transpile_llvm(source), tmp_path, managed=True, optimize=optimize)


@pytest.mark.parametrize('operation', [
    'self.saved = value', 'alias = value', 'print(traceback)',
    'name = kind.__name__', 'details = value.args',
    'self.saved = (kind is value for index in range(1))',
    'self.saved = (value is None for index in range(1))',
    'self.saved = (index for index in range(1) if traceback is None)',
    'self.saved = (item for index in range(1) for item in [kind is None])',
])
def test_borrowed_exit_details_cannot_escape_or_be_inspected(operation):
    with pytest.raises(CompilationError, match='exception details are borrowed'):
        transpile_llvm(f'''
class Scope:
    def __enter__(self) -> int:
        return 1
    def __exit__(self, kind: object, value: object, traceback: object) -> bool:
        {operation}
        return False
def main() -> int:
    with Scope():
        return 1
''')


def test_optional_exception_message_requires_narrowing():
    with pytest.raises(LLVMUnsupported, match="narrow an optional exception"):
        transpile_llvm('''
class Scope:
    def __enter__(self) -> None:
        pass
    def __exit__(self, kind: object, value: BaseException | None, traceback: object) -> bool:
        message = str(value)
        return False
def main() -> int:
    with Scope():
        return 1
''')


def test_shadowed_str_cannot_receive_borrowed_exception_details():
    with pytest.raises(CompilationError, match="not a shadowed callable"):
        transpile_llvm('''
from typing import Callable
def replacement(value: BaseException) -> str:
    return "shadowed"
class Scope:
    def __enter__(self) -> None:
        pass
    def __exit__(self, kind: object, value: BaseException | None, traceback: object) -> bool:
        str: Callable[[BaseException], str] = replacement
        if value is not None:
            message = str(value)
        return False
def main() -> int:
    with Scope():
        return 1
''')
