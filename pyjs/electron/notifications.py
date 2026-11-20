"""Native main-process notifications; applications own delivery policy."""
from collections.abc import Callable

from pyjs import js
from pyjs.electron import Event


@js.dictionary
class NotificationOptions:
    def __init__(self, title: str, body: str = "", id: str | None = None,
                 groupId: str | None = None, silent: bool = False):
        self.title = title
        self.body = body
        self.silent = silent
        if id is not None:
            self.id = id
        if groupId is not None:
            self.groupId = groupId


@js.native
class Notification:
    def show(self) -> None: ...
    def close(self) -> None: ...
    def on(self, name: str, callback: Callable[[Event], None]) -> None: ...
    def removeListener(self, name: str, callback: Callable[[Event], None]) -> None: ...


@js.inline("require('electron').Notification.isSupported()")
def is_supported() -> bool:
    """Check native presenter availability, not permission or visible delivery."""
    ...


@js.inline("new (require('electron').Notification)({options})")
def create_notification(options: NotificationOptions) -> Notification:
    """Create after app readiness; retain the object and listen before show().

    IDs and groups apply on macOS and Windows, not Linux. Windows limits each
    to 64 UTF-16 units. OS signing, registration and permission still apply.
    """
    ...


@js.inline("((notification, callback) => {{ const listener = (_event, error) => callback(error); notification.on('failed', listener); return () => notification.removeListener('failed', listener); }})({notification}, {callback})")
def on_failed(notification: Notification, callback: Callable[[str], None]) -> Callable[[], None]:
    """Subscribe to native publication errors and return an owned unsubscriber.

    The native Event is not forwarded. Missing events are not proof of success;
    applications must bound their wait and retain retryable work.
    """
    ...
