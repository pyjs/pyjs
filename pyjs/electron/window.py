"""Explicit window policy and native menus for Electron hosts."""
from collections.abc import Callable

from pyjs import js
from pyjs.electron import BrowserWindow, WebContents, WindowOptions


@js.inline("new (require('electron').BrowserWindow)({options})")
def create_window(options: WindowOptions) -> BrowserWindow:
    """Create a window whose navigation policy is owned by the caller.

    Unlike HostContext.createWindow, this does not install a blanket navigation
    blocker or hide the application menu. Use WebPreferences for isolated,
    sandboxed defaults and install guards before loading untrusted content.
    """
    ...


@js.inline("((contents, allowed) => {{ const guard = (event, url) => {{ if (!allowed(url)) event.preventDefault(); }}; contents.on('will-navigate', guard); contents.on('will-redirect', guard); }})({contents}, {allowed})")
def allow_navigation(contents: WebContents, allowed: Callable[[str], bool]) -> None:
    """Guard main-frame user navigations and redirects, not host loadURL calls."""
    ...


@js.inline("{contents}.on('will-attach-webview', event => event.preventDefault())")
def deny_webviews(contents: WebContents) -> None: ...


@js.inline("((contents, callback) => contents.setWindowOpenHandler(details => {{ callback(details.url); return {{action: 'deny'}}; }}))({contents}, {callback})")
def handle_window_requests(contents: WebContents, callback: Callable[[str], None]) -> None:
    """Deny native popups and notify the host so it can open a controlled window."""
    ...


@js.dictionary
class MenuItem:
    def __init__(self, label: str | None = None, role: str | None = None,
                 type: str | None = None, accelerator: str | None = None,
                 click: Callable[[], None] | None = None,
                 submenu: list[MenuItem] | None = None):
        if label is not None:
            self.label = label
        if role is not None:
            self.role = role
        if type is not None:
            self.type = type
        if accelerator is not None:
            self.accelerator = accelerator
        if click is not None:
            self.click = click
        if submenu is not None:
            self.submenu = submenu


@js.inline("require('electron').Menu.setApplicationMenu(require('electron').Menu.buildFromTemplate({items}))")
def set_application_menu(items: list[MenuItem]) -> None: ...
