import json

from pyjs.server import (
    OperationError,
    OperationIssue,
    operation_error,
    parse_operation_error,
)


def test_operation_errors_serialize_jsonapi_style_issues():
    error = OperationError(
        [
            OperationIssue(
                "Choose a known value.",
                ["draft", "labels/0", "display~name"],
                422,
                "Validation error",
                "invalid_choice",
            )
        ]
    )

    assert str(error) == "Choose a known value."
    assert error.status() == 422
    assert error.payload() == {
        "errors": [
            {
                "code": "invalid_choice",
                "detail": "Choose a known value.",
                "source": {
                    "pointer": "/draft/labels~10/display~0name",
                },
                "status": "422",
                "title": "Validation error",
            }
        ]
    }


def test_client_error_parser_reconstructs_typed_issues_and_pointer_paths():
    source = json.dumps(
        {
            "errors": [
                {
                    "code": "too_short",
                    "detail": "Use at least three characters.",
                    "source": {
                        "pointer": "/draft/labels~10/display~0name",
                    },
                    "status": "422",
                    "title": "Validation error",
                }
            ]
        }
    )

    error = parse_operation_error(source, 400)

    assert str(error) == "Use at least three characters."
    assert len(error.issues) == 1
    assert error.issues[0].code == "too_short"
    assert error.issues[0].detail == "Use at least three characters."
    assert error.issues[0].location == [
        "draft",
        "labels/0",
        "display~name",
    ]
    assert error.issues[0].status == 422
    assert error.issues[0].title == "Validation error"


def test_client_error_parser_falls_back_for_non_json_responses():
    error = parse_operation_error("Service unavailable", 503)

    assert error.status() == 503
    assert error.issues[0].detail == "Service unavailable"
    assert error.issues[0].location == []
    assert error.issues[0].title == "Request failed"


def test_operation_error_helper_creates_a_single_domain_issue():
    error = operation_error(
        "A title is required.",
        "draft",
        "title",
        code="required",
    )

    assert error.payload() == {
        "errors": [
            {
                "code": "required",
                "detail": "A title is required.",
                "source": {"pointer": "/draft/title"},
                "status": "422",
                "title": "Validation error",
            }
        ]
    }
