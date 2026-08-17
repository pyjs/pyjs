from typing import TypedDict

from pyjs import js
from pyjs.nativescript import Http
from pyjs.server.transport import ClientTransport, TransportResponse


class HttpRequestOptions(TypedDict):
    content: str
    headers: object
    method: str
    timeout: int
    url: str


@js.inline("Object.fromEntries({headers})")
def _plain_headers(headers: dict[str, str]) -> object:
    return headers


@js
class NativeScriptTransport(ClientTransport):
    async def request(
        self,
        url: str,
        body: str,
        timeout_ms: int = 0,
    ) -> TransportResponse:
        response = await Http.request(
            HttpRequestOptions(
                url=url,
                method="POST",
                headers=_plain_headers(
                    {"Content-Type": "application/json"}
                ),
                content=body,
                timeout=timeout_ms,
            )
        )
        return TransportResponse(response.statusCode, response.content.toString())
