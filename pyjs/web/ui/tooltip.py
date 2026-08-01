from pyjs import js
from pyjs.web.dom import document
from pyjs.web.domx import ProxyElement, button, ref, tw
from pyjs.web.events import Event, KeyboardEvent
from pyjs.web.ui import Widget
from pyjs.web.ui.floating import FloatingPanel, FloatingPosition


@js
class TooltipTrigger(ProxyElement):
    def __init__(self, *children):
        self.element = button(
            tw(
                "inline-flex size-9 items-center justify-center rounded-md border "
                "border-slate-300 bg-white text-sm font-medium text-slate-950 shadow-sm "
                "hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 "
                "focus-visible:ring-slate-400"
            ),
            {"data-slot": "tooltip-trigger", "type": "button"},
            *children,
        )


@js
class TooltipContent(FloatingPanel):
    def __init__(self, *children):
        super().__init__(
            tw(
                "pointer-events-none max-w-64 rounded-md bg-slate-950 px-3 py-1.5 "
                "text-xs text-white shadow-md"
            ),
            {"data-slot": "tooltip-content", "role": "tooltip"},
            *children,
        )


@js
class TooltipKeyListener:
    def __init__(self, tooltip: Tooltip):
        self.tooltip = tooltip

    @js(include=True)
    def handleEvent(self, event: KeyboardEvent):
        if event.key == "Escape":
            self.tooltip.close()


@js
class Tooltip(Widget):
    def __init__(
        self,
        trigger: TooltipTrigger,
        content: TooltipContent,
        *,
        side: str = "top",
        align: str = "center",
        side_offset: int = 4,
    ):
        super().__init__()
        self.trigger = ref(trigger)
        self.content = ref(content)
        self.setAttribute("data-side", side)
        self.setAttribute("data-align", align)
        self.setAttribute("data-side-offset", str(side_offset))

        self.link_content()
        self.trigger.element.addEventListener("mouseenter", self.mouse_entered)
        self.trigger.element.addEventListener("mouseleave", self.mouse_left)
        self.trigger.element.addEventListener("focus", self.focused)
        self.trigger.element.addEventListener("blur", self.blurred)
        self.trigger.element.addEventListener("click", self.clicked)
        self.add(
            tw("inline-block"),
            {"data-slot": "tooltip", "data-state": "closed"},
            self.trigger,
            self.content,
        )

    def link_content(self):
        content_id = self.content.get_component_id() + "-content"
        self.content.setAttribute("id", content_id)
        described_by = self.trigger.getAttribute("aria-describedby")
        if described_by is None:
            self.trigger.setAttribute("aria-describedby", content_id)
            return
        ids = ""
        for existing_id in described_by.split():
            if existing_id != content_id:
                duplicate = False
                for added_id in ids.split():
                    if added_id == existing_id:
                        duplicate = True
                if not duplicate:
                    if ids != "":
                        ids += " "
                    ids += existing_id
        if ids != "":
            ids += " "
        self.trigger.setAttribute("aria-describedby", ids + content_id)

    def initialize(self):
        self.is_open = False
        self.is_hovered = False
        self.has_focus = False
        self.key_listener = TooltipKeyListener(self)

    def open(self) -> FloatingPosition:
        side = self.getAttribute("data-side")
        align = self.getAttribute("data-align")
        side_offset = self.getAttribute("data-side-offset")
        resolved_side = "top"
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

    def mouse_entered(self, event: Event):
        self.is_hovered = True
        if not self.is_open:
            self.open()

    def mouse_left(self, event: Event):
        self.is_hovered = False
        if not self.has_focus:
            self.close()

    def focused(self, event: Event):
        self.has_focus = True
        if not self.is_open:
            self.open()

    def blurred(self, event: Event):
        self.has_focus = False
        if not self.is_hovered:
            self.close()

    def clicked(self, event: Event):
        self.close()

    @js(include=True)
    def disconnectedCallback(self):
        self.close()
