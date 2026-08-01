from pyjs import js
from pyjs.web.domx import ProxyElement, button, ref, tag, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget


@js
class CollapsibleTrigger(ProxyElement):
    def __init__(self, *children):
        self.element = button(
            tw(
                "flex w-full items-center justify-between rounded-md px-3 py-2 text-left "
                "text-sm font-medium text-slate-950 hover:bg-slate-100 focus-visible:ring-2 "
                "focus-visible:ring-slate-400"
            ),
            {"data-slot": "collapsible-trigger", "type": "button"},
            *children,
        )


@js
class CollapsibleContent(ProxyElement):
    def __init__(self, *children):
        self.element = tag(
            "div",
            tw("px-3 pb-3 text-sm leading-6 text-slate-600"),
            {"data-slot": "collapsible-content"},
            *children,
        )


@js
class Collapsible(Widget):
    def __init__(
        self,
        trigger: CollapsibleTrigger,
        content: CollapsibleContent,
        *,
        open: bool = False,
    ):
        super().__init__()
        self.trigger = ref(trigger)
        self.content = ref(content)
        self.link_controls()
        self.set_open(open)
        self.trigger.element.addEventListener("click", self.clicked)
        self.add(
            tw("block w-full max-w-lg rounded-lg border border-slate-200 bg-white"),
            {"data-slot": "collapsible"},
            self.trigger,
            self.content,
        )

    def link_controls(self):
        content_id = self.get_component_id() + "-content"
        self.content.setAttribute("id", content_id)
        self.trigger.setAttribute("aria-controls", content_id)

    def is_open(self) -> bool:
        return self.trigger.getAttribute("aria-expanded") == "true"

    def set_open(self, open: bool):
        state = "open" if open else "closed"
        self.setAttribute("data-state", state)
        self.trigger.setAttribute("aria-expanded", "true" if open else "false")
        self.trigger.setAttribute("data-state", state)
        self.content.setAttribute("data-state", state)
        self.content.setAttribute("style", "display: block" if open else "display: none")

    def clicked(self, event: Event):
        self.set_open(not self.is_open())
