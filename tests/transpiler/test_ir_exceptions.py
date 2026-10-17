from textwrap import dedent

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.analysis.ir import (
    BlockArgument,
    ExceptionDispatch,
    IRValidationError,
    build_program_ir,
    validate_program_ir,
)
from pyjs.analysis.source import analyze_source
from pyjs.java import transpile_jvm
from pyjs.native.analysis import NATIVE_ENVIRONMENT
from pyjs.webassembly import transpile_webassembly
from tests.backend_semantics import (
    CONTEXT_MANAGER_CONTRACT,
    EXCEPTION_CONTROL_FLOW_CONTRACT,
)

SOURCE = '''
def main() -> int:
    try:
        raise ValueError("bad")
    except ValueError:
        return 7
'''


@pytest.mark.parametrize("transpile", [transpile_jvm, transpile_webassembly])
def test_backends_without_exception_regions_keep_a_focused_diagnostic(transpile):
    with pytest.raises(CompilationError, match="exception handlers are not implemented"):
        transpile(EXCEPTION_CONTROL_FLOW_CONTRACT.source)


def test_exception_ir_preserves_handlers_and_protected_edges():
    with analyze_source(SOURCE, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        assert analysis.types == dedent('''\
            def main() -> int:
                block entry:
                    jump try_body
                block exception_dispatch:
                    dispatch_exception:
                        ValueError -> except
                        unmatched -> caller
                block try_body except -> exception_dispatch:
                    raise ValueError('bad')
                block except:
                    catch __caught_exception
                    return 7
        ''').rstrip()


def test_assertion_message_control_flow_is_below_the_failure_edge():
    source = '''
def main(test: bool, detail: bool) -> int:
    assert test, ("yes" if detail else "no")
    return 7
'''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        assert analysis.types == dedent('''\
            def main(test: bool, detail: bool) -> int:
                block entry:
                    branch test:
                        true -> assert_passed
                        false -> assert_failed
                block assert_failed:
                    branch detail:
                        true -> conditional_true
                        false -> conditional_false
                block conditional_true:
                    jump conditional_done('yes')
                block conditional_false:
                    jump conditional_done('no')
                block conditional_done(conditional_done_value: str):
                    raise AssertionError(conditional_done_value)
                block assert_passed:
                    return 7
        ''').rstrip()


def test_list_assertion_ir_uses_the_length_truth_protocol():
    source = '''
def main(values: list[int]) -> int:
    assert values, "empty"
    return 7
'''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        assert analysis.types == dedent('''\
            def main(values: list__int) -> int:
                block entry:
                    branch values.[list__int]__len__():
                        true -> assert_passed
                        false -> assert_failed
                block assert_failed:
                    raise AssertionError('empty')
                block assert_passed:
                    return 7
        ''').rstrip()


@pytest.mark.parametrize("edge", ["protected", "handler", "unmatched"])
@pytest.mark.parametrize("invalid", ["missing", "arguments"])
def test_validator_rejects_invalid_exception_edges(edge, invalid):
    with analyze_source(SOURCE, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        program = build_program_ir(analysis.entry_point)
        blocks = analysis.entry_point.ir.blocks
        handler = next(block for block in blocks if block.name == "except")
        destination = "missing" if invalid == "missing" else handler.name
        if invalid == "arguments":
            handler.arguments.append(BlockArgument("invalid", analysis.entry_point.return_type, None))
        if edge == "protected":
            next(block for block in blocks if block.name == "try_body").exception_target = destination
        else:
            dispatch = next(node for block in blocks for node in block.body if isinstance(node, ExceptionDispatch))
            if edge == "handler":
                dispatch.handlers = ((dispatch.handlers[0][0], destination),)
            else:
                dispatch.unmatched = destination
        with pytest.raises(IRValidationError, match="exception target|targets missing|cannot provide"):
            validate_program_ir(program)


def test_hidden_exception_names_do_not_shadow_user_locals():
    source = '''
def main() -> int:
    __caught_exception = 8
    finally_return = 3
    try:
        return __caught_exception + finally_return
    finally:
        pass
'''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        assert "finally_return_2" in analysis.types


def test_union_return_is_transported_through_finally():
    source = '''
def main(value: list[int] | str) -> list[int] | str:
    try:
        return value
    finally:
        pass
'''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        assert analysis.types == dedent('''\
            def main(value: list[int] | str) -> list[int] | str:
                block entry:
                    jump try_body
                block exception_dispatch:
                    dispatch_exception:
                        unmatched -> finally_exception
                block try_body except -> exception_dispatch:
                    jump finally_abrupt(value)
                block finally_abrupt(finally_return: list[int] | str):
                    return finally_return
                block finally_exception:
                    catch __caught_exception
                    reraise __caught_exception
        ''').rstrip()


@pytest.mark.parametrize("transpile", [transpile_jvm, transpile_webassembly])
def test_context_managers_keep_other_backends_explicitly_gated(transpile):
    with pytest.raises(CompilationError, match="context-manager regions are not implemented"):
        transpile(CONTEXT_MANAGER_CONTRACT.source)


def test_context_manager_ir_preserves_entry_and_abrupt_cleanup_order():
    source = '''
class Scope:
    def __enter__(self) -> int:
        return 4
    def __exit__(self, kind: object, value: object, traceback: object) -> bool:
        return True

def main() -> int:
    with Scope() as value:
        return value
    return 0
'''
    with analyze_source(source, wrap=False, environment=NATIVE_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        assert analysis.types == dedent('''\
            class Scope:

                def __enter__() -> int:
                    block entry:
                        return 4

                def __exit__(kind: object, value: object, traceback: object) -> bool:
                    block entry:
                        return True

            def main() -> int:
                block entry:
                    __with_manager = new[local] Scope()
                    __with_entered = __with_manager.[Scope]__enter__()
                    jump with_body
                block with_body except -> with_exception:
                    value = __with_entered
                    jump finally_abrupt(value)
                block finally_abrupt(finally_return: int):
                    __with_manager.[Scope]__exit__(None, None, None)
                    return finally_return
                block with_exception:
                    catch __caught_exception
                    branch __with_manager.[Scope]__exit__(exception_details=__caught_exception):
                        true -> with_suppressed
                        false -> with_reraise
                block with_suppressed:
                    jump with_done
                block with_reraise:
                    reraise __caught_exception
                block with_done:
                    return 0
        ''').rstrip()
