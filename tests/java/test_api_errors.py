import json

import pytest

from pyjs.server.jvm_errors import parse_operation_error
from tests.java.test_context_managers import assert_text_matches_python
from tests.java.test_exceptions import assert_compiles_to_android_dex, run_jvm


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


@pytest.mark.parametrize("status", ["bad", "9223372036854775808", "-9223372036854775809"])
def test_malformed_status_stays_inside_the_proxy_operation_error_boundary(tmp_path, status):
    body = json.dumps({"errors": [{"title": "Failure", "detail": "unavailable", "status": status}]})
    source = f'''
from pyjs.java import run_sync
from pyjs.server import API, query
from pyjs.server.errors import OperationError
from pyjs.server.transport import ClientTransport, TransportResponse
class Service(API):
    @query
    async def read(self) -> str:
        return "server only"
class Transport(ClientTransport):
    async def request(self, url: str, body: str, timeout_ms: int = 0) -> TransportResponse:
        return TransportResponse(503, {body!r})
async def execute() -> str:
    try:
        await Service("https://example.test/api", transport=Transport()).read()
    except OperationError as error:
        assert len(error.issues) == 1
        issue = error.issues[0]
        assert issue.status == 503
        assert issue.title == "Request failed"
        assert issue.detail == {body!r}
        return "fallback retained"
    return "missing error"
def main() -> str:
    return run_sync(execute())
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "fallback retained"


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
