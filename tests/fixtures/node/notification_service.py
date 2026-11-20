"""Private-session Linux notification daemon for the opt-in Electron test."""
import subprocess
import sys

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

INTERFACE = "org.freedesktop.Notifications"


class Notifications(dbus.service.Object):
    def __init__(self, bus):
        self.name = dbus.service.BusName(INTERFACE, bus=bus)
        super().__init__(self.name, "/org/freedesktop/Notifications")

    @dbus.service.method(INTERFACE, in_signature="", out_signature="as")
    def GetCapabilities(self):
        return ["body", "actions"]

    @dbus.service.method(INTERFACE, in_signature="", out_signature="ssss")
    def GetServerInformation(self):
        return "Test notifications", "Example", "1.0", "1.2"

    @dbus.service.method(INTERFACE, in_signature="susssasa{sv}i", out_signature="u")
    def Notify(self, app, replaces, icon, title, body, actions, hints, expires):
        print("notify:", title, body, flush=True)
        if title == "Failure example":
            raise dbus.exceptions.DBusException(
                "publication rejected", name="org.freedesktop.DBus.Error.Failed")
        if title != "Native example" or body != "Body 🐍":
            raise AssertionError("Unexpected native notification payload")
        GLib.timeout_add(50, self.activate)
        return 1

    def activate(self):
        self.ActionInvoked(1, "default")
        return False

    @dbus.service.method(INTERFACE, in_signature="u", out_signature="")
    def CloseNotification(self, identifier):
        print("close:", identifier, flush=True)
        self.NotificationClosed(identifier, 3)

    @dbus.service.signal(INTERFACE, signature="us")
    def ActionInvoked(self, identifier, action):
        pass

    @dbus.service.signal(INTERFACE, signature="uu")
    def NotificationClosed(self, identifier, reason):
        pass


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    service = Notifications(dbus.SessionBus())
    loop = GLib.MainLoop()
    process = subprocess.Popen(sys.argv[1:])

    def poll():
        if process.poll() is None:
            return True
        loop.quit()
        return False

    GLib.timeout_add(50, poll)
    try:
        loop.run()
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        service.remove_from_connection()
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
