"""Runtime for generated typed API proxies on the JVM."""

from pyjs.server.errors import OperationError, OperationIssue
from pyjs.server.jvm import JVMTransport
from pyjs.server.transport import ClientTransport


class API:
    def __init__(self, path: str = "/api", relationship: bool = False,
                 transport: ClientTransport | None = None, timeout_ms: int = 0):
        if relationship:
            raise ValueError("JVM API relationships are not implemented")
        self._path = path
        self._timeout_ms = timeout_ms
        self._transport: ClientTransport = JVMTransport() if transport is None else transport

    async def _request(self, operation: str, body: str) -> str:
        response = await self._transport.request(self._path + "/" + operation, body, self._timeout_ms)
        if not response.ok:
            raise OperationError([OperationIssue(response.body, [], response.status, "Request failed")])
        return response.body
