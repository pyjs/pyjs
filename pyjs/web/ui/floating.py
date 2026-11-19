from collections.abc import Callable

from pyjs import js
from pyjs.web.dom import DOMRect, Element, document
from pyjs.web.domx import tw
from pyjs.web.events import Event
from pyjs.web.html import HTMLDialogElement
from pyjs.web.ui import Widget
from pyjs.web.ui.styles import Stylesheet


@js
def ensure_floating_styles():
    if document.head.querySelector("style[data-floating-panel-reset]") is not None:
        return
    stylesheet = Stylesheet('''
@layer base {
  :where([data-floating-panel]) {
    color: inherit;
    background-color: transparent;
    overflow: visible;
    width: auto;
    height: auto;
    border: 0;
    padding: 0;
  }
}
''')
    stylesheet.setAttribute("data-floating-panel-reset", "")
    document.head.append(stylesheet)


@js
class FloatingPosition:
    def __init__(self, left: int, top: int):
        self.left = left
        self.top = top


@js
def calculate_floating_position(
    anchor: DOMRect,
    panel: DOMRect,
    side: str = "bottom",
    align: str = "start",
    side_offset: int = 4,
    align_offset: int = 0,
) -> FloatingPosition:
    horizontal = round(anchor.left) + align_offset
    vertical = round(anchor.top) + align_offset
    if align == "center":
        horizontal = round(anchor.left + (anchor.width - panel.width) / 2) + align_offset
        vertical = round(anchor.top + (anchor.height - panel.height) / 2) + align_offset
    elif align == "end":
        horizontal = round(anchor.right - panel.width) + align_offset
        vertical = round(anchor.bottom - panel.height) + align_offset

    if side == "top":
        return FloatingPosition(
            horizontal, round(anchor.top - panel.height) - side_offset
        )
    if side == "right":
        return FloatingPosition(round(anchor.right) + side_offset, vertical)
    if side == "left":
        return FloatingPosition(round(anchor.left - panel.width) - side_offset, vertical)
    return FloatingPosition(horizontal, round(anchor.bottom) + side_offset)


@js
class FloatingModalListener:
    def __init__(self, panel: FloatingPanel):
        self.panel = panel

    def handleEvent(self, event: Event):
        modal = self.panel.modal
        if modal is None:
            return
        if modal.open:
            # A reopened modal is above the surviving popover in the top layer.
            self.panel.hidePopover()
            self.panel.showPopover()
        else:
            try:
                self.panel.dismiss()
            finally:
                self.panel.close()


@js
class FloatingPanel(Widget):
    def __init__(self, *children):
        super().__init__()
        self.modal: HTMLDialogElement | None = None
        self.modal_listener = FloatingModalListener(self)
        self.dismiss: Callable[[], None] = self.close
        self.add(
            tw("fixed z-50"),
            {
                "data-floating-panel": "",
                "data-state": "closed",
                "popover": "manual",
                "style": (
                    "position: fixed; inset: auto; margin: 0; left: 0px; top: 0px; z-index: 50; "
                    "display: none; visibility: hidden"
                ),
            },
            *children,
        )

    def open(
        self,
        anchor: Element,
        side: str = "bottom",
        align: str = "start",
        side_offset: int = 4,
        align_offset: int = 0,
        on_dismiss: Callable[[], None] | None = None,
    ) -> FloatingPosition:
        self.close()
        ensure_floating_styles()
        modal = anchor.closest("dialog:modal")
        self.modal = modal if isinstance(modal, HTMLDialogElement) else None
        self.dismiss = self.close if on_dismiss is None else on_dismiss
        self.modal_listener = FloatingModalListener(self)
        if self.modal is None:
            document.body.append(self)
        else:
            self.modal.append(self)
            self.modal.addEventListener("close", self.modal_listener)
        self.style.display = "block"
        self.style.visibility = "hidden"
        self.showPopover()
        position = calculate_floating_position(
            anchor.getBoundingClientRect(),
            self.getBoundingClientRect(),
            side,
            align,
            side_offset,
            align_offset,
        )
        self.style.left = str(position.left) + "px"
        self.style.top = str(position.top) + "px"
        self.style.visibility = "visible"
        self.setAttribute("data-side", side)
        self.setAttribute("data-align", align)
        self.setAttribute("data-state", "open")
        return position

    def close(self):
        if self.getAttribute("data-state") == "open" and self.modal is not None:
            self.modal.removeEventListener("close", self.modal_listener)
            self.modal = None
        self.setAttribute("data-state", "closed")
        if self.matches(":popover-open"):
            self.hidePopover()
        self.style.display = "none"
        self.remove()

    def disconnected(self):
        if self.getAttribute("data-state") == "open":
            try:
                self.dismiss()
            finally:
                self.close()
