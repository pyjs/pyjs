"""Typed Electron host and isolated-preload interfaces."""
from collections.abc import Awaitable, Callable

from pyjs import js


@js.native
class Event:
    def preventDefault(self) -> None: ...


@js.native
class App:
    def setName(self, name: str) -> None: ...
    def setDesktopName(self, name: str) -> None: ...
    def quit(self) -> None: ...
    def on(self, name: str, callback: Callable[[Event], None]) -> None: ...


@js.native
class Frame:
    def __init__(self):
        self.url: str = ""


@js.native
class Debugger:
    def attach(self, version: str) -> None: ...


@js.native
class WebContents:
    def __init__(self):
        self.mainFrame: Frame = Frame()
        self.debugger: Debugger = Debugger()


@js.native
class IpcEvent:
    def __init__(self):
        self.sender: WebContents = WebContents()
        self.senderFrame: Frame = Frame()


@js.dictionary
class WebPreferences:
    def __init__(self, preload: str, partition: str = ""):
        self.preload = preload
        if partition:
            self.partition = partition


@js.dictionary
class WindowOptions:
    def __init__(self, title: str, webPreferences: WebPreferences | None = None,
                 width: int = 1280, height: int = 900):
        self.title = title
        self.width = width
        self.height = height
        self.webPreferences = webPreferences


@js.native
class BrowserWindow:
    def __init__(self):
        self.webContents: WebContents = WebContents()
    def isDestroyed(self) -> bool: ...
    def destroy(self) -> None: ...
    async def loadURL(self, url: str) -> None: ...
    async def loadFile(self, filename: str) -> None: ...
    def on(self, name: str, callback: Callable[[], None]) -> None: ...


@js.native
class HostContext:
    def __init__(self):
        self.app: App = App()
        self.renderer: str = ""
    def createWindow(self, options: WindowOptions) -> BrowserWindow: ...


@js.dictionary
class Response:
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body


@js.inline("((channel, callback) => require('electron').ipcMain.handle(channel, (event, url, options) => callback(event, url, JSON.stringify(options ?? {{}}))))({channel}, {callback})")
def handle(channel: str, callback: Callable[[IpcEvent, str, str], Awaitable[Response]]) -> None: ...

@js.inline("{debugger}.sendCommand({method}, JSON.parse({params})).then(value => JSON.stringify(value))")
async def send_command(debugger: Debugger, method: str, params: str) -> str: ...

@js.inline("((target, callback) => target.on('message', (_event, method, params) => callback(method, JSON.stringify(params))))({debugger}, {callback})")
def on_debug_message(debugger: Debugger, callback: Callable[[str, str], None]) -> None: ...

@js.inline("((target, callback) => target.on('detach', (_event, reason) => callback(reason)))({debugger}, {callback})")
def on_debug_detach(debugger: Debugger, callback: Callable[[str], None]) -> None: ...

@js.inline("{window}.loadFile({filename}, {{query: {{debugTarget: '1'}}}})")
async def load_debug_target(window: BrowserWindow, filename: str) -> None: ...

@js.inline("require('electron').contextBridge.exposeInMainWorld({name}, {api})")
def expose(name: str, api: object) -> None: ...

@js.inline("require('electron').ipcRenderer.invoke({channel}, {url}, {options})")
async def invoke(channel: str, url: str, options: object) -> Response: ...
