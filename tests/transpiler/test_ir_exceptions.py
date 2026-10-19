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
from pyjs.java.analysis import JVM_ENVIRONMENT
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


def test_webassembly_exception_regions_keep_a_focused_diagnostic():
    with pytest.raises(CompilationError, match="exception handlers are not implemented"):
        transpile_webassembly(EXCEPTION_CONTROL_FLOW_CONTRACT.source)


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


def test_jvm_owned_exception_ir_keeps_the_original_value():
    source = '''
def main() -> int:
    saved = ValueError("retained")
    try:
        raise saved
    except ValueError as error:
        return 42 if error is saved else 1
'''
    with analyze_source(source, wrap=False, environment=JVM_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        assert analysis.types == dedent('''\
            def main() -> int:
                block entry:
                    saved: ValueError = ValueError('retained')
                    jump try_body
                block exception_dispatch:
                    dispatch_exception:
                        ValueError -> except
                        unmatched -> caller
                block try_body except -> exception_dispatch:
                    raise saved
                block except:
                    catch __caught_exception
                    error = __caught_exception
                    branch error.[object]__is__(saved):
                        true -> conditional_true
                        false -> conditional_false
                block conditional_true:
                    jump conditional_done(42)
                block conditional_false:
                    jump conditional_done(1)
                block conditional_done(conditional: int):
                    return conditional
        ''').rstrip()
    with pytest.raises(CompilationError, match="constructor or a caught exception"):
        with analyze_source('''
def main() -> int:
    saved = ValueError("retained")
    raise saved
''', wrap=False, environment=NATIVE_ENVIRONMENT):
            pass


def test_jvm_exception_ir_preserves_explicit_causes_and_from_none():
    source = '''
def main() -> int:
    saved = ValueError("original")
    try:
        raise RuntimeError("wrapper") from saved
    except RuntimeError as error:
        raise error from None
'''
    with analyze_source(source, wrap=False, environment=JVM_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        assert analysis.types == dedent('''\
            def main() -> int:
                block entry:
                    saved: ValueError = ValueError('original')
                    jump try_body
                block exception_dispatch:
                    dispatch_exception:
                        RuntimeError -> except
                        unmatched -> caller
                block try_body except -> exception_dispatch:
                    raise RuntimeError('wrapper') from saved
                block except:
                    catch __caught_exception
                    error = __caught_exception
                    raise error from None
        ''').rstrip()


def test_conditional_cause_stays_at_the_raise_operand_position():
    source = '''
def main(target: ValueError, choose: bool, first: RuntimeError, second: RuntimeError) -> None:
    raise target from (first if choose else second)
'''
    with analyze_source(source, wrap=False, environment=JVM_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        assert analysis.types == dedent('''\
            def main(target: ValueError, choose: bool, first: RuntimeError, second: RuntimeError) -> None:
                block entry:
                    raise target from first if choose else second
        ''').rstrip()


def test_ir_tracks_handled_state_separately_from_exception_dispatch_edges():
    source = '''
def main() -> int:
    try:
        raise ValueError("outer")
    except ValueError:
        try:
            raise RuntimeError("inner")
        except RuntimeError:
            pass
        return 1
    return 0
'''
    with analyze_source(source, wrap=False, environment=JVM_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        states = [
            (block.name, [
                (type(statement).__name__, getattr(statement.handled_exception, "id", None))
                for statement in block.body
            ])
            for block in analysis.entry_point.ir.blocks
        ]
        assert states == [
            ("entry", [("Jump", None)]),
            ("exception_dispatch", [("ExceptionDispatch", None)]),
            ("try_body", [("ExceptionRaise", None)]),
            ("except", [("ExceptionCatch", None), ("Jump", "__caught_exception")]),
            ("exception_dispatch_2", [("ExceptionDispatch", "__caught_exception")]),
            ("try_body_2", [("ExceptionRaise", "__caught_exception")]),
            ("except_2", [("ExceptionCatch", "__caught_exception"), ("Jump", "__caught_exception")]),
            ("try_done_2", [("Return", "__caught_exception")]),
        ]


@pytest.mark.parametrize("cause", ['ValueError("original")', "None"])
@pytest.mark.parametrize("backend", ["javascript", "llvm", "webassembly"])
def test_explicit_causes_remain_a_focused_unsupported_backend_boundary(cause, backend):
    source = f'def main() -> int:\n    raise RuntimeError("wrapper") from {cause}\n'
    with pytest.raises(CompilationError, match="exception chaining with 'raise .* from .*' is not supported"):
        if backend == "webassembly":
            transpile_webassembly(source)
        else:
            kwargs = {"environment": NATIVE_ENVIRONMENT} if backend == "llvm" else {}
            with analyze_source(source, wrap=False, **kwargs):
                pass


def test_llvm_context_inspection_keeps_the_borrowed_exception_boundary():
    with pytest.raises(CompilationError, match="native exception details are borrowed"):
        with analyze_source('''
def main() -> int:
    try:
        raise ValueError("original")
    except ValueError as error:
        return 1 if error.__context__ is None else 0
''', wrap=False, environment=NATIVE_ENVIRONMENT):
            pass


def test_narrowed_caught_exception_retains_reraise_metadata():
    source = '''
def main() -> int:
    try:
        raise ValueError("failed")
    except Exception as error:
        if isinstance(error, ValueError):
            raise error
        return 1
'''
    with analyze_source(source, wrap=False, environment=JVM_ENVIRONMENT) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        assert analysis.types == dedent('''\
            def main() -> int:
                block entry:
                    jump try_body
                block exception_dispatch:
                    dispatch_exception:
                        Exception -> except
                        unmatched -> caller
                block try_body except -> exception_dispatch:
                    raise ValueError('failed')
                block except:
                    catch __caught_exception
                    error = __caught_exception
                    branch isinstance(error, ValueError):
                        true -> if_true
                        false -> if_done
                block if_true:
                    raise error
                block if_done:
                    return 1
        ''').rstrip()


@pytest.mark.parametrize("attribute", ["__cause__", "__context__", "__suppress_context__"])
@pytest.mark.parametrize("backend", ["llvm", "webassembly"])
@pytest.mark.parametrize("caught_value", [False, True], ids=["parameter", "handler"])
def test_chaining_properties_remain_an_explicit_backend_boundary(attribute, backend, caught_value):
    from pyjs.webassembly.analysis import WEBASSEMBLY_ENVIRONMENT

    source = f'''def main() -> bool:
    try:
        raise ValueError("failure")
    except Exception as error:
        return error.{attribute} is None
    return False
''' if caught_value else f'''def main(error: Exception) -> bool:
    return error.{attribute} is None
'''
    environment = NATIVE_ENVIRONMENT if backend == "llvm" else WEBASSEMBLY_ENVIRONMENT
    with pytest.raises(CompilationError) as caught:
        with analyze_source(source, wrap=False, environment=environment):
            pass
    error = caught.value
    assert error.diagnostic.code == "PYJS2001"
    if caught_value:
        if backend == "llvm":
            assert error.diagnostic.message == (
                "native exception details are borrowed: use str(value), compare with None, "
                "or reraise a caught exception"
            )
            assert (error.lineno, error.offset) == (5, 16)
        else:
            assert error.diagnostic.message == "native IR exception handlers are not implemented"
            assert (error.lineno, error.offset) == (2, 5)
    else:
        assert error.diagnostic.message == "exception chaining state is not implemented by this backend"
        assert (error.lineno, error.offset) == (2, 12)


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT], ids=["llvm", "jvm"])
def test_global_narrowing_does_not_require_a_local_exception_binding(environment):
    source = '''
VALUE: str | None = "value"
def main() -> int:
    if isinstance(VALUE, str):
        return 42
    return 0
'''
    with analyze_source(source, wrap=False, environment=environment) as analysis:
        validate_program_ir(build_program_ir(analysis.entry_point))
        assert analysis.types == dedent('''\
            VALUE: __const__ = 'value'

            def main() -> int:
                block entry:
                    branch isinstance(VALUE, str):
                        true -> if_true
                        false -> if_done
                block if_true:
                    return 42
                block if_done:
                    return 0
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


def test_webassembly_context_managers_remain_explicitly_gated():
    with pytest.raises(CompilationError, match="context-manager regions are not implemented"):
        transpile_webassembly(CONTEXT_MANAGER_CONTRACT.source)


@pytest.mark.parametrize("environment", [NATIVE_ENVIRONMENT, JVM_ENVIRONMENT], ids=["llvm", "jvm"])
def test_context_manager_ir_preserves_entry_and_abrupt_cleanup_order(environment):
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
    with analyze_source(source, wrap=False, environment=environment) as analysis:
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
