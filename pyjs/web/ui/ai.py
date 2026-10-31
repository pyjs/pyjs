"""Composable agent UI. Actions remain owned by the application's transport."""

from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.domx import div, tag, tw
from pyjs.web.events import KeyboardEvent
from pyjs.web.html import HTMLFormElement, HTMLTextAreaElement
from pyjs.web.ui import Widget
from pyjs.web.ui.button import Button
from pyjs.web.ui.hover_card import HoverCard, HoverCardContent, HoverCardTrigger
from pyjs.web.ui.input_group import InputGroup, InputGroupAddon
from pyjs.web.ui.native_select import NativeSelect
from pyjs.web.ui.trace import CodeBlock, TraceStep


@js
class PromptInput(Widget):
    """Enter submits the enclosing form; Shift+Enter and IME retain text editing."""

    def __init__(self, control: Element, *actions):
        super().__init__()
        self.add(tw("block"), {"data-slot": "prompt-input"}, InputGroup(
            div(tw("w-full p-1"), control),
            InputGroupAddon(*actions, align="block-end")))

    def initialize(self):
        self.addEventListener("keydown", self.keydown)

    def keydown(self, event: KeyboardEvent):
        if (event.key != "Enter" or event.shiftKey or event.isComposing
                or not isinstance(event.target, HTMLTextAreaElement)):
            return
        form = self.closest("form")
        if isinstance(form, HTMLFormElement):
            event.preventDefault()
            form.requestSubmit()


@js
def Tool(name: str, arguments: str, output: str = "", *, status: str = ""):
    return TraceStep(name, CodeBlock(arguments, language="Input"),
                     CodeBlock(output, language="Output") if output else div(), status=status)


@js
def Reasoning(summary: str, *, running: bool = False, duration: str = ""):
    """Display an agent's public summary, never private model reasoning."""
    return TraceStep("Reasoning summary", tag("p", tw("whitespace-pre-wrap"), summary),
                     status="Working…" if running else duration, open=running)


@js
def Plan(title: str, *steps, completed: int = 0, total: int = 0):
    return TraceStep(title, *steps, status=str(completed) + " / " + str(total), open=True)


@js
def Task(title: str, *steps, status: str = ""):
    return TraceStep(title, *steps, status=status, open=status == "running")


@js
def Queue(*items):
    return tag("ul", tw("space-y-2"), {"data-slot": "queue", "aria-label": "Queued work"}, *items)


@js
def QueueItem(title: str, *, completed: bool = False):
    return tag("li", tw("flex items-center gap-2 text-sm data-[completed=true]:text-slate-400 "
                        "data-[completed=true]:line-through"),
               {"data-slot": "queue-item", "data-completed": "true" if completed else "false"},
               tag("span", {"aria-label": "Completed" if completed else "Pending"}, "✓" if completed else "○"), title)


@js
def Confirmation(title: str, *actions, description: str = ""):
    return tag("section", tw("rounded-xl border border-slate-300 bg-slate-50 p-4"),
        {"data-slot": "confirmation", "aria-label": title},
        tag("h3", tw("text-sm font-medium"), title),
        tag("p", tw("mt-1 whitespace-pre-wrap text-sm text-slate-600"), description),
        div(tw("mt-3 flex flex-wrap gap-2"), *actions))


@js
def Checkpoint(label: str, *actions):
    return div(tw("my-4 flex items-center gap-3 border-y border-dashed border-slate-200 py-2 text-xs text-slate-500"),
               {"data-slot": "checkpoint"}, tag("span", tw("flex-1"), label), *actions)


@js
def Context(used: int, capacity: int, *details):
    return HoverCard(HoverCardTrigger(str(used) + " / " + str(capacity) + " tokens"),
        HoverCardContent(tag("progress", {"value": str(used), "max": str(max(1, capacity)),
                                          "aria-label": "Context used"}, tw("w-full")), *details))


@js
def FileTree(*entries):
    return div(tw("space-y-1 font-mono text-xs"), {"data-slot": "file-tree"}, *entries)


@js
def FileTreeFolder(name: str, *entries, open: bool = False):
    return TraceStep(name, FileTree(*entries), open=open)


@js
def FileTreeFile(name: str, *children):
    return Button(name, *children, variant="ghost", size="sm")


@js
def InlineCitation(label: str, *details, href: str = "#"):
    return HoverCard(HoverCardTrigger(label, href=href), HoverCardContent(*details))


@js
def Sources(*sources):
    return TraceStep("Sources", *sources, status=str(len(sources)))


@js
def ModelSelector(*options, name: str = "model"):
    return NativeSelect(*options, name=name, label="Model")


@js
def Suggestion(text: str):
    return Button(text, variant="outline", size="sm")


@js
def StackTrace(message: str, *frames):
    return TraceStep(message, *frames, status="failed")


@js
def Subagent(name: str, *activity, status: str = ""):
    return TraceStep(name, *activity, status=status, open=status == "running")


@js
def Terminal(command: str, output: str, *, status: str = ""):
    return TraceStep(command, CodeBlock(output, language="Terminal"), status=status)


@js
def TestResults(*suites, passed: int = 0, failed: int = 0, skipped: int = 0):
    return TraceStep("Tests", *suites,
        status=str(passed) + " passed · " + str(failed) + " failed · " + str(skipped) + " skipped",
        open=failed > 0)
