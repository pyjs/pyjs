"""Python-aware exception reporting for direct JVM applications."""

from pyjs import jvm


@jvm.native("pyjs/runtime/ExceptionReports", name="format")
def format_exception(error: BaseException, /) -> str:
    """Render explicit causes and unsuppressed context, oldest error first.

    CPython uses its traceback formatter. JVM retains native frame syntax and
    suppressed-error details while applying Python's chain selection and order.
    """
    import traceback

    return "".join(traceback.format_exception(error))
