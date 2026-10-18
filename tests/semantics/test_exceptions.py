import pytest

from tests.backend_semantics import (
    CONTEXT_MANAGER_CONTRACT,
    CUSTOM_EXCEPTION_CONTRACT,
    EXCEPTION_CLEANUP_CONTRACT,
    EXCEPTION_CONTROL_FLOW_CONTRACT,
    EXCEPTION_OBJECT_CONTRACT,
    EXCEPTION_VALUE_IDENTITY_CONTRACT,
)

from .helpers import assert_semantics


@pytest.mark.parametrize("contract", [EXCEPTION_CONTROL_FLOW_CONTRACT, EXCEPTION_CLEANUP_CONTRACT, EXCEPTION_VALUE_IDENTITY_CONTRACT, CUSTOM_EXCEPTION_CONTRACT, EXCEPTION_OBJECT_CONTRACT], ids=["handlers", "cleanup", "owned-value", "custom", "custom-owned"])
def test_shared_exception_control_flow_contract(contract):
    assert_semantics(contract.print_source + "\nmain()\n")


def test_shared_context_manager_contract():
    assert_semantics(CONTEXT_MANAGER_CONTRACT.print_source + "\nmain()\n")


def test_custom_exceptions_preserve_type_and_message():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class ValidationError(Exception):
            pass

        try:
            raise ValidationError("invalid")
        except Exception as error:
            print(isinstance(error, ValidationError))
            print(str(error))
        """
    )


def test_specific_handlers_preserve_order_and_rethrow_unmatched_errors():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class ValidationError(ValueError):
            pass

        @js
        def classify(kind: int):
            try:
                if kind == 1:
                    raise ValidationError("validation")
                if kind == 2:
                    raise TypeError("type")
                raise Exception("other")
            except ValidationError:
                print("validation")
            except (TypeError, ValueError) as error:
                print(str(error))

        for kind in (1, 2):
            classify(kind)
        try:
            classify(3)
        except Exception:
            print("other")
        """
    )


def test_common_exception_types_preserve_hierarchy_and_runtime_identity():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class MissingSetting(KeyError):
            pass

        @js
        def assertion_message() -> str:
            print("message")
            return "failed"

        @js
        def classify(kind: int):
            try:
                if kind == 1:
                    raise MissingSetting("setting")
                if kind == 2:
                    raise IndexError("index")
                if kind == 3:
                    raise RuntimeError("runtime")
                raise AssertionError("assertion")
            except MissingSetting:
                print("missing")
            except LookupError:
                print("lookup")
            except RuntimeError:
                print("runtime")
            except AssertionError:
                print("assertion")

        for kind in (1, 2, 3, 4):
            classify(kind)

        assert True, assertion_message()
        try:
            assert False, assertion_message()
        except AssertionError as error:
            print(str(error))

        try:
            next(iter([]))
        except StopIteration:
            print("stopped")
        """
    )


def test_not_implemented_error_preserves_runtime_error_hierarchy():
    assert_semantics(
        """\
        try:
            raise NotImplementedError("missing implementation")
        except RuntimeError as error:
            print(isinstance(error, NotImplementedError))
            print(str(error))
        """
    )


def test_try_else_only_runs_after_a_successful_body_and_precedes_finally():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def run(fail: bool):
            try:
                print("body")
                if fail:
                    raise ValueError("failed")
            except ValueError:
                print("handled")
            else:
                print("succeeded")
            finally:
                print("finally")

        run(False)
        run(True)
        """
    )


def test_try_else_does_not_run_after_return_or_catch_its_own_errors():
    assert_semantics(
        """\
        from pyjs import js

        @js
        def finish(early: bool) -> int:
            try:
                if early:
                    return 1
            except ValueError:
                print("handled")
            else:
                print("else")
            finally:
                print("finally")
            return 2

        print(finish(True))
        print(finish(False))
        try:
            try:
                print("body")
            except ValueError:
                print("inner")
            else:
                raise TypeError("from else")
        except TypeError:
            print("outer")
        """
    )


def test_bare_raise_rethrows_the_active_exception():
    assert_semantics(
        """\
        from pyjs import js

        @js
        class ValidationError(ValueError):
            pass

        @js
        def validate():
            try:
                raise ValidationError("invalid")
            except ValidationError as error:
                print(str(error))
                raise

        try:
            validate()
        except ValidationError as error:
            print(isinstance(error, ValidationError), str(error))
        """
    )
