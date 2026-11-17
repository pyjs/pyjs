from collections.abc import Callable

from pyjs import js
from pyjs.ui.floating import FloatingPosition, FloatingRect, place_floating
from pyjs.web.dom import DOMRect, Element, ResizeObserver, document, window
from pyjs.web.domx import tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget


@js
def floating_rect(rect: DOMRect) -> FloatingRect:
    return FloatingRect(rect.left, rect.top, rect.width, rect.height)


@js
class FloatingPanel(Widget):
    """Anchored top-layer content; owns viewport constraints and open-time listeners."""

    anchor: Element
    observer: ResizeObserver
    container: Element
    on_close: Callable[[], None] | None
    side: str
    align: str
    side_offset: int
    align_offset: int

    def __init__(self, *children):
        super().__init__()
        self.add(
            tw("fixed z-50"),
            {
                "data-state": "closed",
                "popover": "manual",
                "style": (
                    "position: fixed; inset: auto; margin: 0; left: 0px; top: 0px; "
                    "z-index: 50; display: none; visibility: hidden"
                ),
            },
            *children,
        )

    def open_from(self, owner: Element, anchor: Element,
                  on_close: Callable[[], None] | None = None) -> FloatingPosition:
        return self.open(
            anchor,
            side=owner.getAttribute("data-side") or "bottom",
            align=owner.getAttribute("data-align") or "start",
            side_offset=int(owner.getAttribute("data-side-offset") or "4"),
            align_offset=int(owner.getAttribute("data-align-offset") or "0"),
            on_close=on_close,
        )

    def open(
        self,
        anchor: Element,
        side: str = "bottom",
        align: str = "start",
        side_offset: int = 4,
        align_offset: int = 0,
        *,
        on_close: Callable[[], None] | None = None,
    ) -> FloatingPosition:
        if self.getAttribute("data-state") == "open":
            self.close()
        self.anchor = anchor
        self.side = side
        self.align = align
        self.side_offset = side_offset
        self.align_offset = align_offset
        self.on_close = on_close
        # A body portal outside a modal's DOM remains inert even at a high z-index.
        container = anchor.closest("dialog[open]")
        if container is None:
            container = document.body
        self.container = container
        container.append(self)
        self.style.display = "block"
        self.style.visibility = "hidden"
        self.observer = ResizeObserver(self.reposition)
        self.setAttribute("data-state", "open")
        try:
            self.showPopover()
            position = self.reposition()
        except Exception:
            self.close()
            raise
        self.style.visibility = "visible"
        self.observer.observe(anchor)
        self.observer.observe(self)
        container.addEventListener("close", self)
        self.addEventListener("toggle", self)
        document.addEventListener("scroll", self, capture=True, passive=True)
        window.addEventListener("resize", self)
        visual = window.visualViewport
        if visual is not None:
            visual.addEventListener("resize", self)
            visual.addEventListener("scroll", self)
        return position

    def reposition(self) -> FloatingPosition:
        # Measure intrinsic size, not the previous viewport's size constraint.
        self.style.removeProperty("max-width")
        self.style.removeProperty("max-height")
        visual = window.visualViewport
        viewport = FloatingRect(0, 0, window.innerWidth, window.innerHeight)
        if visual is not None:
            viewport = FloatingRect(visual.offsetLeft, visual.offsetTop,
                                    visual.width, visual.height)
        position = place_floating(
            floating_rect(self.anchor.getBoundingClientRect()),
            floating_rect(self.getBoundingClientRect()), viewport,
            self.side, self.align, self.side_offset, self.align_offset,
            rtl=window.getComputedStyle(self.anchor).getPropertyValue("direction") == "rtl",
        )
        self.style.left = str(position.left) + "px"
        self.style.top = str(position.top) + "px"
        self.style.setProperty("--floating-available-width", str(position.available_width) + "px")
        self.style.setProperty("--floating-available-height", str(position.available_height) + "px")
        self.style.setProperty("max-width", "var(--floating-available-width)")
        self.style.setProperty("max-height", "var(--floating-available-height)")
        self.style.overflow = "auto"
        self.setAttribute("data-side", position.side)
        self.setAttribute("data-align", self.align)
        return position

    def handleEvent(self, event: Event):
        if event.type == "close":
            self.close()
        elif event.type == "toggle":
            if not self.matches(":popover-open"):
                self.close()
        else:
            self.reposition()

    def disconnected(self):
        if self.getAttribute("data-state") != "open":
            return
        self.setAttribute("data-state", "closed")
        self.observer.disconnect()
        self.container.removeEventListener("close", self)
        self.removeEventListener("toggle", self)
        document.removeEventListener("scroll", self, capture=True)
        window.removeEventListener("resize", self)
        visual = window.visualViewport
        if visual is not None:
            visual.removeEventListener("resize", self)
            visual.removeEventListener("scroll", self)
        if self.on_close is not None:
            self.on_close()

    def close(self):
        if self.getAttribute("data-state") == "open":
            self.hidePopover()
            self.disconnected()
        self.style.display = "none"
        self.setAttribute("data-state", "closed")
        self.remove()
