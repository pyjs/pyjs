from typing import cast

from pyjs import js
from pyjs.web.dom import Element, document
from pyjs.web.domx import ProxyElement, button, ref, tag, tw
from pyjs.web.events import Event, KeyboardEvent
from pyjs.web.html import HTMLElement
from pyjs.web.ui import Widget
from pyjs.web.ui.floating import FloatingPanel, FloatingPosition


@js
class PopoverTrigger(ProxyElement):
    def __init__(self, *children):
        self.element = button(
            tw(
                "inline-flex h-9 items-center justify-center rounded-md border border-slate-300 "
                "bg-white px-4 text-sm font-medium text-slate-950 shadow-sm transition-colors "
                "hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 "
                "focus-visible:ring-slate-400"
            ),
            {
                "aria-expanded": "false",
                "aria-haspopup": "dialog",
                "data-slot": "popover-trigger",
                "type": "button",
            },
            *children,
        )

    def set_expanded(self, expanded: bool):
        self.element.setAttribute("aria-expanded", "true" if expanded else "false")
        self.element.setAttribute("data-state", "open" if expanded else "closed")


@js
class PopoverClose(ProxyElement):
    def __init__(self, *children):
        self.element = button(
            tw(
                "inline-flex h-9 items-center justify-center rounded-md border border-slate-300 "
                "bg-white px-3 text-sm font-medium text-slate-950 shadow-sm hover:bg-slate-100"
            ),
            {"data-slot": "popover-close", "type": "button"},
            *children,
        )


@js
def PopoverHeader(*children):
    return tag(
        "div",
        tw("grid gap-1.5"),
        {"data-slot": "popover-header"},
        *children,
    )


@js
def PopoverTitle(*children):
    return tag(
        "h3",
        tw("font-medium leading-none text-slate-950"),
        {"data-slot": "popover-title"},
        *children,
    )


@js
def PopoverDescription(*children):
    return tag(
        "p",
        tw("text-sm leading-5 text-slate-500"),
        {"data-slot": "popover-description"},
        *children,
    )


@js
class PopoverContent(FloatingPanel):
    def __init__(self, *children, label: str = "Popover"):
        super().__init__(
            tw(
                "w-72 rounded-md border border-slate-200 bg-white p-4 text-slate-950 "
                "shadow-md outline-none"
            ),
            {
                "aria-label": label,
                "data-slot": "popover-content",
                "role": "dialog",
            },
            *children,
        )
        self.style.width = "288px"


@js
class PopoverClickListener:
    def __init__(self, popover: Popover):
        self.popover = popover

    def handleEvent(self, event: Event):
        self.popover.handle_document_click(event)


@js
class PopoverKeyListener:
    def __init__(self, popover: Popover):
        self.popover = popover

    def handleEvent(self, event: KeyboardEvent):
        self.popover.handle_keydown(event)


@js
class Popover(Widget):
    def __init__(
        self,
        trigger: PopoverTrigger,
        content: PopoverContent,
        *,
        side: str = "bottom",
        align: str = "center",
        side_offset: int = 4,
        align_offset: int = 0,
    ):
        super().__init__()
        self.trigger = ref(trigger)
        self.content = ref(content)
        self.setAttribute("data-side", side)
        self.setAttribute("data-align", align)
        self.setAttribute("data-side-offset", str(side_offset))
        self.setAttribute("data-align-offset", str(align_offset))

        self.trigger.element.addEventListener("click", self.toggle)
        self.content.addEventListener("click", self.handle_content_click)
        self.add(
            tw("inline-block"),
            {"data-slot": "popover", "data-state": "closed"},
            self.trigger,
            self.content,
        )

    def initialize(self):
        self.is_open = False
        self.click_listener = PopoverClickListener(self)
        self.key_listener = PopoverKeyListener(self)

    def open(self) -> FloatingPosition:
        side = self.getAttribute("data-side")
        align = self.getAttribute("data-align")
        side_offset = self.getAttribute("data-side-offset")
        align_offset = self.getAttribute("data-align-offset")
        resolved_side = "bottom"
        resolved_align = "center"
        resolved_side_offset = 4
        resolved_align_offset = 0
        if side is not None:
            resolved_side = side
        if align is not None:
            resolved_align = align
        if side_offset is not None:
            resolved_side_offset = int(side_offset)
        if align_offset is not None:
            resolved_align_offset = int(align_offset)
        position = self.content.open(
            self.trigger.element,
            side=resolved_side,
            align=resolved_align,
            side_offset=resolved_side_offset,
            align_offset=resolved_align_offset,
        )
        self.is_open = True
        self.setAttribute("data-state", "open")
        self.trigger.set_expanded(True)
        document.addEventListener("click", self.click_listener)
        document.addEventListener("keydown", self.key_listener)
        return position

    def close(self, restore_focus: bool = False):
        if not self.is_open:
            return
        document.removeEventListener("click", self.click_listener)
        document.removeEventListener("keydown", self.key_listener)
        self.content.close()
        self.is_open = False
        self.setAttribute("data-state", "closed")
        self.trigger.set_expanded(False)
        if restore_focus:
            cast(HTMLElement, self.trigger.element).focus()

    def toggle(self, event: Event):
        if self.is_open:
            self.close()
        else:
            self.open()

    def handle_content_click(self, event: Event):
        target = cast(Element, event.target)
        if target.closest("[data-slot=popover-close]") is not None:
            self.close(restore_focus=True)

    def handle_document_click(self, event: Event):
        if not self.is_open:
            return
        target = cast(Element, event.target)
        if self.contains(target) or self.content.contains(target):
            return
        self.close()

    def handle_keydown(self, event: KeyboardEvent):
        if event.key == "Escape" and self.is_open:
            event.preventDefault()
            self.close(restore_focus=True)

    def disconnected(self):
        self.close()
