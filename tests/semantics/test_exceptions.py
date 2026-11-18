import pytest

from tests.backend_semantics import (
    ASSERT_TRUTH_CONTRACT,
    CONTEXT_MANAGER_CONTRACT,
    CUSTOM_EXCEPTION_CONTRACT,
    EXCEPTION_CLEANUP_CONTRACT,
    EXCEPTION_CONTROL_FLOW_CONTRACT,
    EXCEPTION_OBJECT_CONTRACT,
    EXCEPTION_VALUE_IDENTITY_CONTRACT,
)

from .helpers import assert_semantics


def test_assertion_truth_and_lazy_evaluation():
    assert_semantics(ASSERT_TRUTH_CONTRACT.print_source + "\nmain()\n")


@pytest.mark.parametrize("protocol, annotation, result", [
    ("__bool__", "bool", "self.calls == 1"),
    ("__len__", "int", "1 if self.calls == 1 else 0"),
])
@pytest.mark.parametrize("expression", [
    "value or False", "value and True", "value and value", "value or value",
    "not (value or False)", "not (value and False)",
    "(value or False) and True", "(value and False) or True",
    "value if value or False else False", "False if value and False else value",
])
def test_assertion_short_circuit_truth_runs_only_at_the_consumed_operands(
    protocol, annotation, result, expression,
):
    assert_semantics(f'''
        from pyjs import js
        @js
        class Changing:
            def __init__(self):
                self.calls = 0
            def {protocol}(self) -> {annotation}:
                self.calls += 1
                print("truth", self.calls)
                return {result}
        @js
        def message() -> str:
            print("message")
            return "failed"
        value = Changing()
        try:
            assert {expression}, message()
            print("passed")
        except AssertionError:
            print("failed")
        print(value.calls)
    ''')


@pytest.mark.parametrize("empty, present", [
    ("[]", "[0]"), ("()", "(0,)"), ("{}", "{0: 0}"),
    ("set[int]()", "{0}"), ("''", "'0'"), ("0", "1"), ("None", "True"),
])
def test_assertions_share_collection_and_scalar_truthiness(empty, present):
    assert_semantics(f'''
        try:
            assert {empty}
        except AssertionError:
            print("empty")
        value = {present}
        assert value
        print("present")
    ''')


def test_assertion_length_protocol_and_errors_evaluate_once():
    assert_semantics('''
        from pyjs import js
        @js
        class Sized:
            def __init__(self, count: int):
                self.count = count
            def __len__(self) -> int:
                print("length")
                if self.count < 0:
                    raise ValueError("unavailable")
                return self.count
        @js
        def condition(count: int) -> Sized:
            print("condition")
            return Sized(count)
        @js
        def message() -> str:
            print("message")
            return "empty"
        for count in [0, 1, -1]:
            try:
                assert condition(count), message()
            except (AssertionError, ValueError) as error:
                print(str(error))
    ''')


def test_assertion_union_truth_dispatches_without_erasing_the_value():
    assert_semantics('''
        from pyjs import js
        @js
        def check(value: list[int] | str | None) -> None:
            try:
                assert value, "empty"
                if isinstance(value, str):
                    print(value.upper())
                else:
                    print(value[0])
            except AssertionError as error:
                print(str(error))
        check([])
        check([0])
        check("")
        check("kept")
        check(None)
    ''')


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
