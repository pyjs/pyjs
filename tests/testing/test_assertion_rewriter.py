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
    assert isinstance(tree.body[0], ast.Assert)
    assert ast.dump(tree.body[0].test) == ast.dump(ast.parse(condition, mode="eval").body)
    namespace = {"read": read, "message": message,
                 ASSERT_ALIAS: assert_condition, COMPARE_ALIAS: assert_compare}
    if passed:
        exec(compile(tree, "<assertion>", "exec"), namespace)
    else:
        with pytest.raises(AssertionError, match="custom detail"):
            exec(compile(tree, "<assertion>", "exec"), namespace)
    assert events == (["condition"] if passed else ["condition", "message"])


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
