from collections.abc import Callable

from pyjs import js
from pyjs.electron import WebContents
from pyjs.electron.session import PermissionCheckDetails, PermissionRequest, Session


@js
class Policy:
    def __init__(self, origin: str):
        self.origin = origin

    def check(self, contents: WebContents | None, permission: str, origin: str,
              details: PermissionCheckDetails) -> bool:
        return (contents is not None and permission == "clipboard-sanitized-write"
                and origin == self.origin and details.isMainFrame
                and details.requestingUrl == self.origin + "/editor"
                and contents.getURL() == details.requestingUrl)

    def request(self, contents: WebContents, permission: str,
                done: Callable[[bool], None], details: PermissionRequest) -> None:
        done(permission == "clipboard-sanitized-write" and details.isMainFrame
             and details.requestingUrl == self.origin + "/editor"
             and contents.getURL() == details.requestingUrl)


@js
def main(session: Session) -> None:
    session.setPermissionCheckHandler(None)
    session.setPermissionRequestHandler(None)
    policy = Policy("https://example.test")
    session.setPermissionCheckHandler(policy.check)
    session.setPermissionRequestHandler(policy.request)
    policy = Policy("https://must-not-replace-bound-policy.test")
