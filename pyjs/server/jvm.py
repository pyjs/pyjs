"""Blocking JVM HTTP transport for API calls made on a worker thread.

The JVM currently lowers immediately awaited calls synchronously. An async
signature does not make this transport safe to call on Android's UI thread.
"""

from typing import cast

from pyjs import int8
from pyjs.java import JVMArray, i32
from pyjs.java.collections import JavaList
from pyjs.java.io import ByteArrayOutputStream, InputStream, OutputStreamWriter
from pyjs.java.net import (
    URL,
    CookieManager,
    HttpURLConnection,
    default_cookie_handler,
    encode_form_value,
)
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

    Headers are explicit, including authentication and CSRF if needed. Django
    HTTPS POSTs also need a trusted HTTPS Referer; desktop OpenJDK drops Origin.
    An optional CookieManager keeps a private, in-memory session; no global
    cookie handler is installed. Do not reuse credential headers across origins.
    Redirects are returned without following them. Native I/O exceptions propagate.
    timeout_ms is a connect/read timeout, not a total request deadline; zero
    disables those timeouts, matching ClientTransport. Responses are bounded
    in bytes. Applications should set a finite timeout for network operations.
    """

    def __init__(
        self,
        headers: list[tuple[str, str]] | None = None,
        max_response_bytes: int = 8_388_608,
        cookies: CookieManager | None = None,
    ):
        if max_response_bytes <= 0:
            raise ValueError("API response byte limit must be positive")
        self.headers: list[tuple[str, str]] = []
        if headers is not None:
            for header in headers:
                self.headers.append(header)
        self.max_response_bytes = max_response_bytes
        self.cookies = cookies

    async def request(
        self,
        url: str,
        body: str,
        timeout_ms: int = 0,
    ) -> TransportResponse:
        return await self._send("POST", url, body, "application/json; charset=utf-8", timeout_ms)

    async def get(self, url: str, timeout_ms: int = 0) -> TransportResponse:
        return await self._send("GET", url, "", "", timeout_ms)

    async def post_form(self, url: str, fields: list[tuple[str, str]], timeout_ms: int = 0) -> TransportResponse:
        parts: list[str] = []
        for name, value in fields:
            parts.append(encode_form_value(name, "UTF-8") + "=" + encode_form_value(value, "UTF-8"))
        return await self._send("POST", url, "&".join(parts), "application/x-www-form-urlencoded; charset=utf-8", timeout_ms)

    async def _send(self, method: str, url: str, body: str, content_type: str, timeout_ms: int) -> TransportResponse:
        if timeout_ms < 0 or timeout_ms > 2147483647:
            raise ValueError("API request timeout must be between 0 and 2147483647 milliseconds")
        if self.cookies is not None and default_cookie_handler() is not None:
            raise ValueError("Managed sessions cannot share a process-global CookieHandler")
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
            connection.setRequestMethod(method)
            cookies = self.cookies
            for name, value in self.headers:
                if cookies is not None and (name.lower() == "cookie" or name.lower() == "cookie2"):
                    raise ValueError("Managed cookies cannot be combined with explicit Cookie headers")
                connection.setRequestProperty(name, value)
            if cookies is not None:
                cookie_headers = cookies.get(target.toURI(), connection.getRequestProperties())
                for key in ["Cookie", "Cookie2"]:
                    raw = cookie_headers.get(key)
                    if raw is not None:
                        values = cast(JavaList, raw)
                        parts: list[str] = []
                        for index in range(int(values.size())):
                            parts.append(cast(str, values.get(i32(index))))
                        connection.setRequestProperty(key, "; ".join(parts))
            if method == "POST":
                connection.setDoOutput(True)
                connection.setRequestProperty("Content-Type", content_type)
                writer = OutputStreamWriter(connection.getOutputStream(), "UTF-8")
                try:
                    writer.write(body)
                finally:
                    writer.close()
            status = connection.getResponseCode()
            if cookies is not None:
                cookies.put(target.toURI(), connection.getHeaderFields())
            stream = (connection.getErrorStream() if status >= 400
                      else connection.getInputStream())
            result = "" if stream is None else _read_body(stream, self.max_response_bytes)
            return TransportResponse(int(status), result)
        finally:
            connection.disconnect()
