from typing import NotRequired, TypedDict

from pyjs import js


@js.native
class FetchResponse:
    def __init__(self):
        self.status = 0

    async def text(self) -> str: ...


@js.native
class AbortSignal:
    @staticmethod
    def timeout(milliseconds: int) -> AbortSignal: ...


class FetchOptions(TypedDict):
    body: str
    headers: dict[str, str]
    method: str
    signal: NotRequired[AbortSignal]


@js.native
async def fetch(url: str, options: FetchOptions) -> FetchResponse: ...


@js
class TransportResponse:
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body

    @property
    def ok(self) -> bool:
        return self.status >= 200 and self.status < 300


@js
class ClientTransport:
    async def request(
        self,
        url: str,
        body: str,
        timeout_ms: int = 0,
    ) -> TransportResponse: ...


@js
class FetchTransport(ClientTransport):
    async def request(
        self,
        url: str,
        body: str,
        timeout_ms: int = 0,
    ) -> TransportResponse:
        options = FetchOptions(
            method="POST",
            headers={"Content-Type": "application/json"},
            body=body,
        )
        if timeout_ms > 0:
            options["signal"] = AbortSignal.timeout(timeout_ms)
        response = await fetch(url, options)
        return TransportResponse(response.status, await response.text())
