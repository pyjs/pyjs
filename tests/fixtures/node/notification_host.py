from pyjs import js
from pyjs.electron import Event
from pyjs.electron.notifications import (
    Notification,
    NotificationOptions,
    create_notification,
    is_supported,
    on_failed,
)


@js
class Delivery:
    def __init__(self):
        self.shown = 0
        self.clicked = 0
        self.closed = 0
        self.errors: list[str] = []

    def show(self, event: Event) -> None:
        self.shown += 1

    def click(self, event: Event) -> None:
        self.clicked += 1

    def close(self, event: Event) -> None:
        self.closed += 1

    def failed(self, error: str) -> None:
        self.errors.append(error)


@js
def main() -> Notification | None:
    if not is_supported():
        return None
    notification = create_notification(NotificationOptions(
        "Example 🐍", "Open the app", id="schedule-1", groupId="account-1", silent=True))
    state = Delivery()
    shown = state.show
    notification.on("show", shown)
    notification.on("click", state.click)
    notification.on("close", state.close)
    unsubscribe = on_failed(notification, state.failed)
    notification.show()
    notification.show()
    notification.close()
    assert state.shown == 2 and state.clicked == 2 and state.closed == 1
    assert state.errors == ["publication failed", "publication failed"]
    unsubscribe()
    unsubscribe()
    notification.removeListener("show", shown)
    notification.show()
    assert state.shown == 2 and state.clicked == 3
    assert state.errors == ["publication failed", "publication failed"]
    create_notification(NotificationOptions("Defaults"))
    return notification
