"""Session-local network and protocol APIs for Python-authored hosts.

Handlers belong to the selected partition, not the default browser session.
Fetch uses Chromium cookies and certificate validation. Bypassing protocol
handlers is explicit, for forwarding intercepted requests without recursion.
"""
from collections.abc import Awaitable, Callable

from pyjs import js
from pyjs.web.network import Request, Response


@js.native
class Protocol:
    def handle(self, scheme: str, handler: Callable[[Request], Awaitable[Response]]) -> None: ...
    def unhandle(self, scheme: str) -> None: ...


@js.dictionary
class FetchOptions:
    def __init__(self, credentials: str = "same-origin", redirect: str = "follow",
                 bypassCustomProtocolHandlers: bool = False):
        self.credentials = credentials
        self.redirect = redirect
        self.bypassCustomProtocolHandlers = bypassCustomProtocolHandlers


@js.native
class Session:
    def __init__(self):
        self.protocol: Protocol = Protocol()

    async def fetch(self, request: Request | str, options: FetchOptions) -> Response: ...


@js.inline("require('electron').session.fromPartition({partition})")
def from_partition(partition: str) -> Session: ...


@js.inline("((session) => {{ session.setPermissionCheckHandler(() => false); session.setPermissionRequestHandler((_contents, _permission, done) => done(false)); }})({session})")
def deny_permissions(session: Session) -> None:
    """Deny both permission queries and requests for this session."""
    ...


@js.inline("((session, allowed) => session.webRequest.onBeforeRequest((details, done) => done({{cancel: !allowed(details.url)}})))({session}, {allowed})")
def allow_requests(session: Session, allowed: Callable[[str], bool]) -> None:
    """Replace the session's request filter with a synchronous URL predicate.

    Electron permits one listener for this event; registering again replaces it.
    Redirect hops also pass through the filter. False cancels the request.
    """
    ...
