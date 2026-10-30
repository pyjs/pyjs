"""Typed xterm.js bindings, installed through ``pyjs npm sync``."""

from collections.abc import Callable

from pyjs import js
from pyjs.tooling.npm import NpmImport, NpmPackage
from pyjs.web.dom import Element

__pyjs_npm_imports__ = (
    NpmImport(NpmPackage("@xterm/xterm", "6.0.0"), "$xterm", ("css/xterm.css",)),
    NpmImport(NpmPackage("@xterm/addon-fit", "0.11.0"), "$fit"),
)


@js.dictionary
class Theme:
    def __init__(self, background: str = "#1e1e1e", foreground: str = "#d4d4d4",
                 cursor: str = "#d4d4d4"):
        self.background = background
        self.foreground = foreground
        self.cursor = cursor


@js.dictionary
class TerminalOptions:
    def __init__(self, *, cols: int = 80, rows: int = 24, fontSize: float = 14,
                 fontFamily: str = "ui-monospace, monospace", scrollback: int = 5000,
                 cursorBlink: bool = True, theme: Theme | None = None):
        self.cols = cols
        self.rows = rows
        self.fontSize = fontSize
        self.fontFamily = fontFamily
        self.scrollback = scrollback
        self.cursorBlink = cursorBlink
        if theme is not None:
            self.theme = theme


@js.native
class Subscription:
    def dispose(self) -> None: ...


@js.native
class FitAddon:
    def fit(self) -> None: ...
    def dispose(self) -> None: ...


@js.native
class BufferLine:
    def translateToString(self, trimRight: bool = False) -> str: ...


@js.native
class Buffer:
    def __init__(self):
        self.length: int = 0
        self.cursorX: int = 0
        self.cursorY: int = 0
        self.type: str = "normal"

    @js.inline("({self}.getLine({index}) ?? null)")
    def getLine(self, index: int) -> BufferLine | None: ...


@js.native
class BufferNamespace:
    def __init__(self):
        self.active: Buffer = Buffer()


@js.native
class RuntimeOptions:
    """Mutable options available on an existing terminal."""

    def __init__(self):
        self.fontSize: float = 14
        self.fontFamily: str = "ui-monospace, monospace"
        self.scrollback: int = 5000
        self.cursorBlink: bool = True


@js.native
class Terminal:
    def __init__(self):
        self.cols: int = 80
        self.rows: int = 24
        self.buffer: BufferNamespace = BufferNamespace()
        self.options: RuntimeOptions = RuntimeOptions()
    def open(self, element: Element) -> None: ...
    def write(self, text: str, callback: Callable[[], None]) -> None: ...
    def focus(self) -> None: ...
    def reset(self) -> None: ...
    def clear(self) -> None: ...
    def dispose(self) -> None: ...
    def loadAddon(self, addon: FitAddon) -> None: ...
    def onData(self, callback: Callable[[str], None]) -> Subscription: ...


@js
def create_terminal(options: TerminalOptions) -> Terminal: ...


create_terminal.source("return new $xterm.Terminal(options);")


@js
def create_fit() -> FitAddon: ...


create_fit.source("return new $fit.FitAddon();")


@js
async def write(terminal: Terminal, text: str) -> None: ...


write.source("return new Promise(resolve => terminal.write(text, resolve));")
