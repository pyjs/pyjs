from pyjs import js
from pyjs.electron import App, Event, HostContext
from pyjs.electron.notifications import (
    Notification,
    NotificationOptions,
    create_notification,
    is_supported,
    on_failed,
    show_notification,
)
from pyjs.node import Timer, clear_timeout, set_timeout


@js
class Delivery:
    def __init__(self, app: App):
        self.app = app
        self.notification: Notification | None = None
        self.timer: Timer | None = None

    async def start(self) -> None:
        assert is_supported()
        self.timer = set_timeout(self.timeout, 5000)
        delayed = create_notification(NotificationOptions("Delayed example"))
        # Linux blocks inside show(): the event timer cannot preempt the daemon.
        await show_notification(delayed, timeout_ms=10)
        print("native-delayed-acknowledged")
        delayed.close()
        notification = create_notification(NotificationOptions("Native example", "Body 🐍"))
        self.notification = notification
        notification.on("show", self.shown)
        notification.on("click", self.clicked)
        await show_notification(notification)
        print("native-acknowledged")

    def shown(self, event: Event) -> None:
        print("native-shown")

    def clicked(self, event: Event) -> None:
        print("native-clicked")
        notification = self.notification
        if notification is not None:
            notification.close()
        notification = create_notification(NotificationOptions("Failure example"))
        self.notification = notification
        on_failed(notification, self.failed)
        notification.show()

    def failed(self, error: str) -> None:
        print("native-failed")
        clear_timeout(self.timer)
        self.app.quit()

    def timeout(self) -> None:
        print("native-timeout")
        self.app.quit()


@js
async def main(context: HostContext) -> None:
    await Delivery(context.app).start()
