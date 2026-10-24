import json

import pytest

from pyjs.server.jvm_errors import parse_operation_error
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_compiles_to_android_dex


def error_corpus():
    documents = [
        {"errors": [{"detail": "雪😀", "title": "Invalid", "status": "422", "code": "bad",
                     "source": {"pointer": "/draft/a~1b/~0key/"}},
                    {"detail": "denied", "title": "Permission", "source": {"pointer": "/"}}]},
        {"errors": [{"detail": "", "title": "", "status": "", "source": None}]},
        {"errors": [], "ignored": {"deep": [1, None, True]}},
    ]
    payloads = [json.dumps(value) for value in documents] + [
        "<html>gateway down</html>", "", "null", "[]", '{"errors":null}',
        '{"errors":[{}]}', '{"errors":[{"title":"a","detail":42}]}',
        '{"errors":[{"title":"a","detail":"b","status":"bad"}]}',
        '{"errors":[{"title":"a","detail":"b"}]} trailing',
    ]
    return f'''
from pyjs.server.jvm_errors import parse_operation_error
def main() -> str:
    output: list[str] = []
    for payload in {payloads!r}:
        error = parse_operation_error(payload, 503)
        output.append(str(error))
        for issue in error.issues:
            output.append(issue.title + ":" + issue.code + ":" + str(issue.status))
            output.append(str(len(issue.location)) + ":" + "|".join(issue.location))
    return "\\n".join(output)
'''


def test_operation_error_decoder_matches_host(tmp_path):
    assert_text_matches_python(error_corpus(), tmp_path)


def test_operation_error_decoder_compiles_to_android_dex(tmp_path):
    assert_compiles_to_android_dex(error_corpus(), tmp_path)


@pytest.mark.parametrize(("pointer", "expected"), [
    ("", []), ("/", [""]), ("/x/", ["x", ""]),
    ("/a~1b/~01/雪", ["a/b", "~1", "雪"]),
])
def test_error_pointer_preserves_empty_and_escaped_segments(pointer, expected):
    payload = {"errors": [{"title": "Invalid", "detail": "bad", "source": {"pointer": pointer}}]}
    issue = parse_operation_error(json.dumps(payload), 422).issues[0]
    assert issue.location == expected
    assert issue.status == 422
    assert issue.code == "invalid"
