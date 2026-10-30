"""Typed Electron host and isolated-preload interfaces."""
from collections.abc import Awaitable, Callable

from pyjs import js


@js.native
class Event:
    def preventDefault(self) -> None: ...


@js.native
class CommandLine:
    def hasSwitch(self, name: str) -> bool: ...


@js.native
class App:
    def __init__(self):
        self.commandLine: CommandLine = CommandLine()
    def setName(self, name: str) -> None: ...
    def setAppUserModelId(self, name: str) -> None: ...
    def setDesktopName(self, name: str) -> None: ...
    def getPath(self, name: str) -> str: ...
    def setPath(self, name: str, path: str) -> None: ...
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
    def send(self, channel: str, message: str) -> None: ...


@js.native
class IpcEvent:
    def __init__(self):
        self.sender: WebContents = WebContents()
        self.senderFrame: Frame = Frame()


@js.dictionary
class WebPreferences:
    def __init__(self, preload: str | None = None, partition: str | None = None,
                 sandbox: bool = True, contextIsolation: bool = True,
                 nodeIntegration: bool = False, webSecurity: bool = True,
                 webviewTag: bool = False):
        if preload is not None:
            self.preload = preload
        if partition is not None:
            self.partition = partition
        self.sandbox = sandbox
        self.contextIsolation = contextIsolation
        self.nodeIntegration = nodeIntegration
        self.webSecurity = webSecurity
        self.webviewTag = webviewTag


@js.dictionary
class WindowOptions:
    def __init__(self, title: str, webPreferences: WebPreferences | None = None,
                 width: int = 1280, height: int = 900, minWidth: int = 0,
                 minHeight: int = 0, backgroundColor: str = "#fff"):
        self.title = title
        self.width = width
        self.height = height
        self.webPreferences = webPreferences
        self.minWidth = minWidth
        self.minHeight = minHeight
        self.backgroundColor = backgroundColor


@js.native
class BrowserWindow:
    def __init__(self):
        self.webContents: WebContents = WebContents()
    def isDestroyed(self) -> bool: ...
    def focus(self) -> None: ...
    def destroy(self) -> None: ...
    def close(self) -> None: ...
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


@js.inline("((channel, callback) => {{ const ipc = require('electron').ipcRenderer; const listener = (_event, message) => callback(message); ipc.on(channel, listener); return () => ipc.removeListener(channel, listener); }})({channel}, {callback})")
def listen(channel: str, callback: Callable[[str], None]) -> Callable[[], None]:
    """Subscribe in a preload and return a function that removes the listener.

    Only the message is forwarded; the Electron event stays in the preload.
    Expose a fixed-channel application callback to isolated renderers.
    """
    ...
