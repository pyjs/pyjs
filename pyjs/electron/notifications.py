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
    applications must handle missing asynchronous events and retain retryable work.
    """
    ...


@js
async def show_notification(notification: Notification, timeout_ms: int = 5000) -> None:
    """Wait for native publication, not user viewing; keep the object for clicks.

    Dismiss the object's previous alert before observing a new publication.
    Failure, early close, timeout and synchronous errors reject. Only this
    call's listeners are removed. The caller owns closing an uncertain alert
    after rejection and must not concurrently show the same object.

    The timer bounds event waiting, not synchronous native work. Electron 45
    on Linux publishes through blocking libnotify/D-Bus calls. A slow daemon
    stalls the main event loop; publication can resolve after timeout_ms or
    fail at the native timeout (observed around 25 seconds). This helper
    cannot preempt that call or provide a hard wall-clock deadline.
    """
    ...


show_notification.source("""
if (!Number.isSafeInteger(timeout_ms) || timeout_ms < 1 || timeout_ms > 2147483647) {
    throw new RangeError('Notification timeout must be 1..2147483647 milliseconds');
}
notification.close();
await new Promise((resolve, reject) => {
    let settled = false;
    const finish = (success, error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        notification.removeListener('show', shown);
        notification.removeListener('failed', failed);
        notification.removeListener('close', closed);
        if (success) resolve(); else reject(error);
    };
    const shown = () => finish(true);
    const failed = (_event, error) => finish(false, new Error(error || 'Notification publication failed'));
    const closed = () => finish(false, new Error('Notification closed before publication'));
    const timer = setTimeout(() => finish(false, new Error('Notification publication timed out')), timeout_ms);
    notification.on('show', shown);
    notification.on('failed', failed);
    notification.on('close', closed);
    try { notification.show(); } catch (error) { finish(false, error); }
});
""")
