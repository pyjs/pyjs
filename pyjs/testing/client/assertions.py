from pyjs import js
from pyjs.web.dom import window


@js
def finish_assertion(condition: bool, detail: str, message: callable | None):
    status = "passed" if condition else "failed"
    line = "[assert:" + status + "] " + detail
    if condition:
        window.console.info(line)
        return

    window.console.error(line)
    failure_detail = detail
    if message is not None:
        failure_detail += " | message: " + str(message())
    assert condition, failure_detail


@js
def assert_condition(condition: bool, expression: str, message: callable | None):
    detail = expression + " => " + str(condition)
    finish_assertion(condition, detail, message)


@js
def assert_compare(
    condition: bool,
    left: object,
    left_expression: str,
    operator: str,
    right: object,
    right_expression: str,
    message: callable | None,
):
    detail = (
        left_expression
        + " "
        + operator
        + " "
        + right_expression
        + " => "
        + str(condition)
        + " | left="
        + str(left)
        + " | right="
        + str(right)
    )
    finish_assertion(condition, detail, message)
