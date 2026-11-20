import ast

import pytest

from pyjs.testing.assertion_rewriter import ASSERT_ALIAS, COMPARE_ALIAS, AssertionRewriter
from pyjs.testing.client.assertions import assert_compare, assert_condition


@pytest.mark.parametrize("condition", [
    "isinstance(read(), int)", "read() is not None", "not (read() is None)",
    "read() and True", "read()", "read() == 'yes'",
])
@pytest.mark.parametrize("passed", [False, True])
def test_rewritten_conditions_evaluate_once_and_keep_messages_lazy(condition, passed):
    events = []

    def read():
        events.append("condition")
        return ("yes" if "'yes'" in condition else 1) if passed else None

    def message():
        events.append("message")
        return "custom detail"

    source = f"assert {condition}, message()"
    tree = ast.fix_missing_locations(AssertionRewriter(source).visit(ast.parse(source)))
    namespace = {"read": read, "message": message,
                 ASSERT_ALIAS: assert_condition, COMPARE_ALIAS: assert_compare}
    if passed:
        exec(compile(tree, "<assertion>", "exec"), namespace)
    else:
        with pytest.raises(AssertionError, match="custom detail"):
            exec(compile(tree, "<assertion>", "exec"), namespace)
    assert events == (["condition"] if passed else ["condition", "message"])


@pytest.mark.parametrize("condition", [
    "value is not None", "None is value", "record.value is None",
    "value == 'yes'", "'no' != record.value", "not (value is None)",
    "isinstance(read(), int)", "value and value.text", "value",
])
def test_narrowing_guards_retain_the_original_assertion(condition):
    source = f"assert {condition}"
    tree = ast.fix_missing_locations(AssertionRewriter(source).visit(ast.parse(source)))
    assert isinstance(tree.body[0], ast.Assert)
    assert ast.dump(tree.body[0].test) == ast.dump(ast.parse(condition, mode="eval").body)


@pytest.mark.parametrize("condition", [
    "'needle' in value", "'needle' not in value", "left is right", "left is not right",
    "value < 'yes'", "'yes' >= value", "read() == 'yes'", "read() is not None", "value == 4",
])
def test_non_narrowing_comparisons_keep_operand_details(condition):
    tree = ast.fix_missing_locations(AssertionRewriter(f"assert {condition}").visit(
        ast.parse(f"assert {condition}")))
    assert isinstance(tree.body[-1], ast.Expr)
    call = tree.body[-1].value
    assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    assert call.func.id == COMPARE_ALIAS


def test_rewritten_truth_protocol_is_not_called_again_for_reporting():
    class Truth:
        calls = 0

        def __bool__(self):
            self.calls += 1
            return self.calls == 1

    source = "assert value"
    tree = ast.fix_missing_locations(AssertionRewriter(source).visit(ast.parse(source)))
    value = Truth()
    exec(compile(tree, "<assertion>", "exec"), {"value": value, ASSERT_ALIAS: assert_condition})
    assert value.calls == 1
