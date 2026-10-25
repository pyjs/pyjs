"""Schema-directed decoding of operation errors for native JVM clients."""

from pyjs.java.json import JSONReader
from pyjs.server.errors import OperationError, OperationIssue


def _location(reader: JSONReader) -> list[str]:
    pointer = ""
    if reader.take("null"):
        return []
    reader.expect("{")
    if not reader.take("}"):
        while True:
            name = reader.string()
            reader.expect(":")
            if name == "pointer":
                pointer = reader.string()
            else:
                reader.skip()
            if reader.take("}"):
                break
            reader.expect(",")
    location: list[str] = []
    if pointer != "":
        if pointer.startswith("/"):
            pointer = pointer[1:]
        for segment in pointer.split("/"):
            location.append(segment.replace("~1", "/").replace("~0", "~"))
    return location


def _issue(reader: JSONReader, response_status: int) -> OperationIssue:
    detail = ""
    title = ""
    code = "invalid"
    has_detail = False
    has_title = False
    status = response_status
    location: list[str] = []
    reader.expect("{")
    if not reader.take("}"):
        while True:
            name = reader.string()
            reader.expect(":")
            if name == "detail":
                detail = reader.string()
                has_detail = True
            elif name == "title":
                title = reader.string()
                has_title = True
            elif name == "code":
                code = reader.string()
            elif name == "status":
                value = reader.string()
                status = response_status if value == "" else int(value)
            elif name == "source":
                location = _location(reader)
            else:
                reader.skip()
            if reader.take("}"):
                break
            reader.expect(",")
    if not has_detail or not has_title:
        raise ValueError("Operation issues require detail and title")
    return OperationIssue(detail, location, status, title, code)


def parse_operation_error(source: str, response_status: int) -> OperationError:
    """Retain structured failures, falling back to the body for invalid payloads."""
    issues: list[OperationIssue] = []
    try:
        reader = JSONReader(source)
        reader.expect("{")
        if not reader.take("}"):
            while True:
                name = reader.string()
                reader.expect(":")
                if name == "errors":
                    issues = []
                    reader.expect("[")
                    if not reader.take("]"):
                        while True:
                            issues.append(_issue(reader, response_status))
                            if reader.take("]"):
                                break
                            reader.expect(",")
                else:
                    reader.skip()
                if reader.take("}"):
                    break
                reader.expect(",")
        reader.finish()
    except (ValueError, OverflowError):
        issues = []
    if not issues:
        issues.append(OperationIssue(source, [], response_status, "Request failed"))
    return OperationError(issues)
