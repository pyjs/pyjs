"""Progressive disclosure for tool calls, steps, and diagnostic output."""

from pyjs import js
from pyjs.web.clipboard import navigator
from pyjs.web.domx import div, ref, tag, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget


@js
class CopyButton(Widget):
    def __init__(self, text: str):
        super().__init__()
        self.set_data("text", text)
        self.control = ref(tag("button", {"type": "button", "aria-label": "Copy text"},
            tw("rounded px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 "
               "focus-visible:outline-2 focus-visible:outline-slate-400"), "Copy"))
        self.append(self.control)

    def initialize(self):
        self.control.addEventListener("click", self.copy)

    async def copy(self, event: Event):
        try:
            await navigator.clipboard.writeText(self.get_data("text") or "")
            self.control.textContent = "Copied"
        except Exception:
            self.control.textContent = "Copy unavailable"


@js
def Trace(*children):
    return div(tw("min-w-0 space-y-2 text-sm text-slate-600"),
               {"data-slot": "trace"}, *children)


@js
def TraceStep(title: str, *children, status: str = "", open: bool = False):
    attributes = {"data-slot": "trace-step", "data-status": status}
    if open:
        attributes["open"] = ""
    return tag("details", attributes,
        tw("group min-w-0 rounded-lg border border-slate-200 bg-white "
           "data-[status=failed]:border-red-300"),
        tag("summary", tw("cursor-pointer rounded-lg px-3 py-2 text-sm "
                          "focus-visible:outline-2 focus-visible:outline-slate-400"),
            title, tag("span", tw("ml-2 text-xs text-slate-500"), status)),
        div(tw("min-w-0 space-y-3 border-t border-slate-100 p-3"), *children))


@js
def CodeBlock(text: str, *, language: str = ""):
    return div(tw("min-w-0 overflow-hidden rounded-lg bg-slate-950 text-slate-100"),
        {"data-slot": "code-block"},
        tag("div", tw("flex items-center justify-between px-3 pt-2 text-xs text-slate-400"),
            tag("span", language), CopyButton(text)),
        tag("pre", tw("max-h-96 overflow-auto p-3 text-xs leading-6"), tag("code", text)))
