"""Blocking JVM HTTP transport for API calls made on a worker thread.

The JVM currently lowers immediately awaited calls synchronously. An async
signature does not make this transport safe to call on Android's UI thread.
"""

from typing import cast

from pyjs import int8
from pyjs.java import JVMArray, i32
from pyjs.java.io import ByteArrayOutputStream, InputStream, OutputStreamWriter
from pyjs.java.net import URL, HttpURLConnection
from pyjs.server.transport import ClientTransport, TransportResponse


def _read_body(stream: InputStream, limit: int) -> str:
    try:
        output = ByteArrayOutputStream()
        buffer = JVMArray[int8](8192)
        total = 0
        while True:
            count = stream.read(buffer)
            if count == -1:
                break
            total += int(count)
            if total > limit:
                raise ValueError("API response exceeds the configured byte limit")
            output.write(buffer, i32(0), count)
        return output.toString("UTF-8")
    finally:
        stream.close()


class JVMTransport(ClientTransport):
    """POST JSON over native HTTP(S), retaining non-success response bodies.

    Headers are explicit, including authentication and CSRF if needed. Redirects
    are returned without following them. Native I/O exceptions propagate.
    timeout_ms is a connect/read timeout, not a total request deadline; zero
    disables those timeouts, matching ClientTransport. Responses are bounded
    in bytes. Applications should set a finite timeout for network operations.
    """

    def __init__(
        self,
        headers: list[tuple[str, str]] | None = None,
        max_response_bytes: int = 8_388_608,
    ):
        if max_response_bytes <= 0:
            raise ValueError("API response byte limit must be positive")
        self.headers: list[tuple[str, str]] = []
        if headers is not None:
            for header in headers:
                self.headers.append(header)
        self.max_response_bytes = max_response_bytes

    async def request(
        self,
        url: str,
        body: str,
        timeout_ms: int = 0,
    ) -> TransportResponse:
        if timeout_ms < 0 or timeout_ms > 2147483647:
            raise ValueError("API request timeout must be between 0 and 2147483647 milliseconds")
        target = URL(url)
        protocol = target.getProtocol()
        if protocol != "http" and protocol != "https":
            raise ValueError("API requests require an absolute HTTP or HTTPS URL")
        connection = cast(HttpURLConnection, target.openConnection())
        try:
            connection.setConnectTimeout(i32(timeout_ms))
            connection.setReadTimeout(i32(timeout_ms))
            connection.setInstanceFollowRedirects(False)
            connection.setUseCaches(False)
            connection.setRequestMethod("POST")
            connection.setDoOutput(True)
            for name, value in self.headers:
                connection.setRequestProperty(name, value)
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            writer = OutputStreamWriter(connection.getOutputStream(), "UTF-8")
            try:
                writer.write(body)
            finally:
                writer.close()
            status = connection.getResponseCode()
            stream = (connection.getErrorStream() if status >= 400
                      else connection.getInputStream())
            result = "" if stream is None else _read_body(stream, self.max_response_bytes)
            return TransportResponse(int(status), result)
        finally:
            connection.disconnect()
