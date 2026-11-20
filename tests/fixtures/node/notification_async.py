from pyjs import js
from pyjs.electron.notifications import Notification, show_notification


@js
async def main(notification: Notification, timeout: int) -> None:
    await show_notification(notification, timeout)
