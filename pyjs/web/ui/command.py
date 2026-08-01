from pyjs import js
from pyjs.web.domx import ProxyElement, div, input, span, tag, tw
from pyjs.web.events import Event, KeyboardEvent
from pyjs.web.ui import Widget


@js
class CommandItem(ProxyElement):
    def __init__(self, value: str, *children, disabled: bool = False):
        self.value = value
        attributes = {
            "aria-disabled": "true" if disabled else "false",
            "data-slot": "command-item",
            "data-value": value,
            "role": "option",
            "tabindex": "-1",
        }
        self.element = div(
            tw(
                "flex cursor-default items-center rounded-sm px-2 py-1.5 text-sm outline-none "
                "hover:bg-slate-100 aria-selected:bg-slate-100 aria-disabled:opacity-50"
            ),
            attributes,
            *children,
        )

    def set_visible(self, visible: bool):
        if visible:
            self.element.removeAttribute("hidden")
        else:
            self.element.setAttribute("hidden", "")


@js
def CommandGroup(label: str, *children):
    return div(
        tw("overflow-hidden p-1"),
        {"aria-label": label, "data-slot": "command-group", "role": "group"},
        div(tw("px-2 py-1.5 text-xs font-medium text-slate-500"), label),
        *children,
    )


@js
def CommandSeparator():
    return tag(
        "div",
        tw("-mx-1 h-px bg-slate-200"),
        {"data-slot": "command-separator", "role": "separator"},
    )


@js
def CommandShortcut(*children):
    return span(
        tw("ml-auto text-xs tracking-widest text-slate-400"),
        {"data-slot": "command-shortcut"},
        *children,
    )


@js
class Command(Widget):
    def __init__(self, *items: CommandItem, placeholder: str = "Type a command..."):
        super().__init__()
        self.items: list[CommandItem] = []
        for item in items:
            self.items.append(item)
        self.input = input(
            tw("h-11 w-full border-b border-slate-200 px-3 text-sm outline-none"),
            {
                "aria-label": placeholder,
                "autocomplete": "off",
                "data-slot": "command-input",
                "placeholder": placeholder,
                "role": "combobox",
            },
        )
        self.empty = div(
            tw("py-6 text-center text-sm text-slate-500"),
            {"data-slot": "command-empty", "hidden": ""},
            "No results found.",
        )
        self.add(
            tw("overflow-hidden rounded-md border border-slate-200 bg-white"),
            {"data-slot": "command"},
            self.input,
            div(
                tw("max-h-72 overflow-y-auto p-1"),
                {"data-slot": "command-list", "role": "listbox"},
                self.empty,
                *items,
            ),
        )
        self.input.addEventListener("input", self.search)
        self.input.addEventListener("keydown", self.keydown)

    def search(self, event: Event):
        query = self.input.value.lower()
        visible_count = 0
        for item in self.items:
            visible = query == "" or query in item.value.lower()
            item.set_visible(visible)
            if visible:
                visible_count += 1
        if visible_count == 0:
            self.empty.removeAttribute("hidden")
        else:
            self.empty.setAttribute("hidden", "")

    def keydown(self, event: KeyboardEvent):
        if event.key != "ArrowDown":
            return
        for item in self.items:
            if item.element.getAttribute("hidden") is None:
                event.preventDefault()
                item.element.focus()
                return
