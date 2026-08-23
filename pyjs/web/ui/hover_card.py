from typing import cast

from pyjs import js
from pyjs.web.dom import Element, document
from pyjs.web.domx import ProxyElement, a, ref, tw
from pyjs.web.events import Event, KeyboardEvent, MouseEvent
from pyjs.web.ui import Widget
from pyjs.web.ui.floating import FloatingPanel, FloatingPosition


@js
class HoverCardTrigger(ProxyElement):
    def __init__(self, *children, href: str = "#"):
        self.element = a(
            tw(
                "font-medium text-slate-950 underline decoration-slate-300 underline-offset-4 "
                "outline-none hover:decoration-slate-950 focus-visible:ring-2 "
                "focus-visible:ring-slate-400"
            ),
            {"data-slot": "hover-card-trigger", "href": href},
            *children,
        )


@js
class HoverCardContent(FloatingPanel):
    def __init__(self, *children):
        super().__init__(
            tw(
                "w-80 rounded-md border border-slate-200 bg-white p-4 text-slate-950 "
                "shadow-md outline-none"
            ),
            {"data-slot": "hover-card-content"},
            *children,
        )
        self.style.width = "320px"


@js
class HoverCardKeyListener:
    def __init__(self, card: HoverCard):
        self.card = card

    def handleEvent(self, event: KeyboardEvent):
        if event.key == "Escape":
            self.card.close()


@js
class HoverCard(Widget):
    def __init__(
        self,
        trigger: HoverCardTrigger,
        content: HoverCardContent,
        *,
        side: str = "bottom",
        align: str = "center",
        side_offset: int = 4,
    ):
        super().__init__()
        self.trigger = ref(trigger)
        self.content = ref(content)
        self.setAttribute("data-side", side)
        self.setAttribute("data-align", align)
        self.setAttribute("data-side-offset", str(side_offset))

        self.trigger.element.addEventListener("mouseenter", self.show)
        self.trigger.element.addEventListener("mouseleave", self.maybe_hide)
        self.trigger.element.addEventListener("focus", self.show)
        self.trigger.element.addEventListener("blur", self.maybe_hide)
        self.content.addEventListener("mouseenter", self.show)
        self.content.addEventListener("mouseleave", self.maybe_hide)
        self.add(
            tw("inline-block"),
            {"data-slot": "hover-card", "data-state": "closed"},
            self.trigger,
            self.content,
        )

    def initialize(self):
        self.is_open = False
        self.key_listener = HoverCardKeyListener(self)

    def open(self) -> FloatingPosition:
        side = self.getAttribute("data-side")
        align = self.getAttribute("data-align")
        side_offset = self.getAttribute("data-side-offset")
        resolved_side = "bottom"
        resolved_align = "center"
        resolved_side_offset = 4
        if side is not None:
            resolved_side = side
        if align is not None:
            resolved_align = align
        if side_offset is not None:
            resolved_side_offset = int(side_offset)
        position = self.content.open(
            self.trigger.element,
            side=resolved_side,
            align=resolved_align,
            side_offset=resolved_side_offset,
        )
        self.is_open = True
        self.setAttribute("data-state", "open")
        document.addEventListener("keydown", self.key_listener)
        return position

    def close(self):
        if not self.is_open:
            return
        document.removeEventListener("keydown", self.key_listener)
        self.content.close()
        self.is_open = False
        self.setAttribute("data-state", "closed")

    def show(self, event: Event):
        if not self.is_open:
            self.open()

    def maybe_hide(self, event: MouseEvent):
        related = cast(Element | None, event.relatedTarget)
        if related is not None:
            if self.contains(related) or self.content.contains(related):
                return
        self.close()

    def disconnected(self):
        self.close()
