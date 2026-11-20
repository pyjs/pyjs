from pyjs import js
from pyjs.electron.notifications import notification_service


@js
def main(timeout: int):
    return notification_service("org.example.notes", "Example Notes", timeout)
