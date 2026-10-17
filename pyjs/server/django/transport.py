from pyjs import js
from pyjs.server.transport import FetchTransport
from pyjs.web.dom import document


@js
class DjangoFetchTransport(FetchTransport):
    """Fetch transport that adds Django's document CSRF token."""

    def request_headers(self) -> dict[str, str]:
        csrf_meta = document.querySelector('meta[name="csrf-token"]')
        if csrf_meta is None:
            raise RuntimeError(
                "Django CSRF metadata is missing from the current document."
            )
        csrf_token = csrf_meta.getAttribute("content")
        if csrf_token is None:
            raise RuntimeError("The Django CSRF token is missing from its metadata.")
        return {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf_token,
        }
