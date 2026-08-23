import re

from pyjs import js


@js.inline("new RegExp({pattern}).test({value})")
def regex_search(pattern: str, value: str) -> bool:
    return re.search(pattern, value) is not None


@js.inline("{error}.constructor")
def exception_type(error: Exception) -> type[Exception]:
    return type(error)


@js.inline(
    "({exception_type} === RangeError ? 'ValueError' : "
    "{exception_type} === Error ? 'Exception' : {exception_type}.name)"
)
def exception_type_name(exception_type: type[Exception]) -> str:
    return exception_type.__name__


@js
class ExceptionInfo:
    def __init__(self, value: Exception):
        self.value = value
        self.type = exception_type(value)
        self.traceback: object | None = None


@js
class RaisesContext:
    def __init__(
        self,
        expected: type[Exception],
        match: str | None,
    ):
        self.expected = expected
        self.match = match
        self.info = ExceptionInfo(Exception(""))

    def __enter__(self) -> ExceptionInfo:
        return self.info

    def __exit__(
        self,
        exc_type: type[Exception] | None,
        exc: Exception | None,
        traceback: object | None,
    ) -> bool:
        if exc is None:
            raise AssertionError(
                "DID NOT RAISE " + exception_type_name(self.expected)
            )
        if not isinstance(exc, self.expected):
            return False
        if self.match is not None and not regex_search(self.match, str(exc)):
            raise AssertionError(
                "Regex pattern did not match.\n"
                + " Regex: "
                + repr(self.match)
                + "\n Input: "
                + repr(str(exc))
            )
        self.info.value = exc
        self.info.type = exception_type(exc)
        self.info.traceback = traceback
        return True


@js
def raises(
    expected_exception: type[Exception],
    *,
    match: str | None = None,
) -> RaisesContext:
    return RaisesContext(expected_exception, match)
