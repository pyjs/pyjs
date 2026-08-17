import json
from typing import NotRequired, TypedDict

from pyjs import js, nojs


class OperationErrorSource(TypedDict):
    pointer: str


class OperationIssuePayload(TypedDict):
    status: str
    title: str
    detail: str
    code: NotRequired[str]
    source: NotRequired[OperationErrorSource]


class OperationErrorPayload(TypedDict):
    errors: list[OperationIssuePayload]


@js
class OperationIssue:
    def __init__(
        self,
        detail: str,
        location: list[str],
        status: int = 400,
        title: str = "Invalid request",
        code: str = "invalid",
    ):
        self.detail = detail
        self.location = location
        self.status = status
        self.title = title
        self.code = code

    @nojs
    def payload(self) -> OperationIssuePayload:
        value: OperationIssuePayload = {
            "code": self.code,
            "detail": self.detail,
            "status": str(self.status),
            "title": self.title,
        }
        if self.location:
            segments = [
                segment.replace("~", "~0").replace("/", "~1")
                for segment in self.location
            ]
            value["source"] = {"pointer": "/" + "/".join(segments)}
        return value


@js
class OperationError(Exception):
    def __init__(self, issues: list[OperationIssue]):
        message = "Operation failed"
        if issues:
            message = issues[0].detail
        super().__init__(message)
        self.issues = issues

    @nojs
    def payload(self) -> OperationErrorPayload:
        return {"errors": [issue.payload() for issue in self.issues]}

    @nojs
    def status(self) -> int:
        if not self.issues:
            return 400
        return self.issues[0].status


def operation_error(
    detail: str,
    *location: str,
    status: int = 422,
    title: str = "Validation error",
    code: str = "invalid",
) -> OperationError:
    return OperationError(
        [OperationIssue(detail, list(location), status, title, code)]
    )


@js.inline("JSON.parse({source})")
def parse_operation_error_payload(source: str) -> OperationErrorPayload:
    return json.loads(source)


@js
def parse_operation_error(source: str, response_status: int) -> OperationError:
    try:
        payload = parse_operation_error_payload(source)
    except Exception:
        return OperationError(
            [OperationIssue(source, [], response_status, "Request failed")]
        )
    issues: list[OperationIssue] = []
    for value in payload.get("errors", []):
        status_value = value.get("status", "")
        status = response_status if status_value == "" else int(status_value)
        location: list[str] = []
        error_source = value.get("source", None)
        if error_source is not None:
            pointer = error_source["pointer"]
            if pointer.startswith("/"):
                pointer = pointer[1:]
            if pointer:
                for segment in pointer.split("/"):
                    location.append(
                        segment.replace("~1", "/").replace("~0", "~")
                    )
        issues.append(
            OperationIssue(
                value["detail"],
                location,
                status,
                value["title"],
                value.get("code", "invalid"),
            )
        )
    if not issues:
        issues.append(
            OperationIssue(source, [], response_status, "Request failed")
        )
    return OperationError(issues)
