import pytest
from pydantic import BaseModel

from pyjs import js
from pyjs.server import (
    API,
    ClientTransport,
    OperationError,
    Stream,
    TransportResponse,
    mutation,
    query,
    stream,
)
from pyjs.server.django import DjangoFetchTransport
from pyjs.web.dom import document


@js
class RecordingTransport(ClientTransport):
    def __init__(self, status: int, body: str):
        super().__init__()
        self.status = status
        self.body = body
        self.url = ""
        self.request_body = ""
        self.timeout_ms = 0

    async def request(
        self,
        url: str,
        body: str,
        timeout_ms: int = 0,
    ) -> TransportResponse:
        self.url = url
        self.request_body = body
        self.timeout_ms = timeout_ms
        return TransportResponse(self.status, self.body)


@js
class TransportAPI(API):
    @query
    async def echo(self, value: str) -> str:
        raise RuntimeError("server only")


@js
class TransportTask(BaseModel):
    id: int | None = None
    title: str


@js
class PydanticTransportAPI(API):
    @mutation
    async def save(self, task: TransportTask) -> TransportTask:
        raise RuntimeError("server only")


@js
class TransportLogLine(BaseModel):
    sequence: int
    text: str


@js
class StreamTransportAPI(API):
    @stream
    def output(self, job_id: int) -> Stream[TransportLogLine]:
        raise RuntimeError("server only")


@pytest.mark.pyjs_web
@js
async def test_api_uses_injected_transport_in_the_browser():
    transport = RecordingTransport(200, '"accepted"')
    api = TransportAPI("/rpc", False, transport, 2500)

    response = await api.echo("hello")

    assert response == "accepted"
    assert transport.url == "/rpc/echo"
    assert transport.request_body == '{"value":"hello"}'
    assert transport.timeout_ms == 2500


@pytest.mark.pyjs_web
@js
async def test_api_translates_transport_errors_in_the_browser():
    transport = RecordingTransport(
        422,
        '{"errors":[{"status":"422","title":"Invalid request",'
        '"detail":"Title is required","code":"required",'
        '"source":{"pointer":"/title"}}]}',
    )
    api = TransportAPI("/rpc", False, transport)

    try:
        await api.echo("")
    except OperationError as error:
        assert error.issues[0].detail == "Title is required"
        assert error.issues[0].location == ["title"]
        assert error.issues[0].status == 422
    else:
        raise AssertionError("Expected the transport error to be raised")


@pytest.mark.pyjs_web
@js
async def test_api_validates_typed_values_through_injected_transport():
    transport = RecordingTransport(
        200,
        '{"id":7,"title":"Saved through custom transport"}',
    )
    api = PydanticTransportAPI(transport=transport)

    saved = await api.save(TransportTask(title="Portable request"))

    assert transport.request_body == (
        '{"task":{"id":null,"title":"Portable request"}}'
    )
    assert isinstance(saved, TransportTask)
    assert saved.id == 7
    assert saved.title == "Saved through custom transport"


@pytest.mark.pyjs_web
@js
async def test_api_stream_builds_a_typed_resumable_browser_session():
    api = StreamTransportAPI("/rpc")
    session = api.output(7).resume_after(3)
    line = session._decode(
        {
            "sequence": 4,
            "text": "container started",
        }
    )

    assert session.path == (
        "/rpc/output?arguments=%7B%22job_id%22%3A7%7D"
    )
    assert session.sequence == 3
    assert isinstance(line, TransportLogLine)
    assert line.sequence == 4
    assert line.text == "container started"


@pytest.mark.pyjs_web
@js
def test_api_live_session_reuses_its_path_and_transport():
    transport = RecordingTransport(200, "{}")
    api = TransportAPI("/rpc", transport=transport)

    session = api.live_session(autostart=False)

    assert session.path == "/rpc"
    assert session._transport is transport
    assert session.autostart is False
    assert session.transport == "stopped"


@pytest.mark.pyjs_web
@js
def test_django_transport_requires_and_reads_csrf_metadata():
    transport = DjangoFetchTransport()

    try:
        transport.request_headers()
    except RuntimeError as error:
        assert str(error) == (
            "Django CSRF metadata is missing from the current document."
        )
    else:
        raise AssertionError("Expected missing CSRF metadata to be rejected")

    meta = document.createElement("meta")
    meta.setAttribute("name", "csrf-token")
    meta.setAttribute("content", "browser-csrf-token")
    document.head.append(meta)

    headers = transport.request_headers()

    assert headers == {
        "Content-Type": "application/json",
        "X-CSRFToken": "browser-csrf-token",
    }
    meta.remove()
