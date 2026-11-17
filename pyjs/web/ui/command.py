from typing import cast

from pyjs import js
from pyjs.web.dom import Element, Node
from pyjs.web.domx import ProxyElement, div, input, ref, span, tag, tw
from pyjs.web.events import Event, KeyboardEvent
from pyjs.web.html import HTMLElement
from pyjs.web.ui import Widget
from pyjs.web.ui.collection import ListNavigation, filter_items
from pyjs.web.ui.dialog import (
    DialogCloseRequest,
    DialogContent,
    DialogDescription,
    DialogTitle,
)


@js.inline("{element}")
def command_item_element(element: Element) -> HTMLElement:
    if not isinstance(element, HTMLElement):
        raise TypeError("Command items must be HTML elements.")
    return element


@js
class CommandItem(ProxyElement):
    def __init__(
        self,
        value: str,
        *children,
        disabled: bool = False,
        keywords: str = "",
    ):
        self.value = value
        attributes = {
            "aria-disabled": "true" if disabled else "false",
            "data-slot": "command-item",
            "data-value": value,
            "role": "option",
            "tabindex": "-1",
        }
        if keywords != "":
            attributes["data-keywords"] = keywords
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
    def __init__(
        self,
        *items: CommandItem,
        placeholder: str = "Type a command...",
        enter_selects: bool = True,
    ):
        super().__init__()
        self.navigation = ListNavigation([], attribute="aria-selected")
        self.enter_selects = enter_selects
        for item in items:
            self.navigation.items.append(cast(HTMLElement, item.element))
        self.input = ref(
            input(
                tw("h-11 w-full border-b border-slate-200 px-3 text-sm outline-none"),
                {
                    "aria-label": placeholder,
                    "autocomplete": "off",
                    "data-slot": "command-input",
                    "placeholder": placeholder,
                    "role": "combobox",
                },
            )
        )
        self.empty = ref(
            div(
                tw("py-6 text-center text-sm text-slate-500"),
                {"data-slot": "command-empty", "hidden": ""},
                "No results found.",
            )
        )
        self.list = ref(
            div(
                tw("max-h-72 overflow-y-auto p-1"),
                {"data-slot": "command-list", "role": "listbox"},
                self.empty,
                *items,
            )
        )
        self.add(
            tw("overflow-hidden rounded-md border border-slate-200 bg-white"),
            {
                "data-enter-selects": "true" if enter_selects else "false",
                "data-slot": "command",
            },
            self.input,
            self.list,
        )

    def initialize(self):
        self.navigation = ListNavigation([], attribute="aria-selected")
        self.enter_selects = self.getAttribute("data-enter-selects") != "false"
        for item in self.querySelectorAll("[data-slot=command-item]"):
            self.navigation.items.append(command_item_element(item))
        self.input.addEventListener("input", self.search)
        self.input.addEventListener("keydown", self.keydown)
        self.addEventListener("click", self.item_clicked)
        self.highlight(0)

    def visible_items(self) -> list[HTMLElement]:
        return self.navigation.available()

    def highlight(self, index: int) -> None:
        item = self.navigation.highlight(index)
        if item is not None:
            item.scrollIntoView(block="nearest")

    def highlighted_item(self) -> HTMLElement | None:
        return self.navigation.current()

    def replace_items(self, *items: CommandItem) -> None:
        self.navigation = ListNavigation([], attribute="aria-selected")
        nodes: list[Element] = []
        nodes.append(self.empty)
        for item in items:
            nodes.append(item.element)
            self.navigation.items.append(cast(HTMLElement, item.element))
        self.list.replaceChildren(*nodes)
        self.search(Event("input"))

    def emit_select(self) -> None:
        item = self.highlighted_item()
        if item is None:
            return
        self.dispatchEvent(Event("command-select", bubbles=True))

    def search(self, event: Event):
        query = self.input.value
        visible_count = filter_items(self.navigation.items, query, ["data-value", "data-keywords"])
        if visible_count == 0:
            self.empty.removeAttribute("hidden")
        else:
            self.empty.setAttribute("hidden", "")
        for group in self.querySelectorAll("[data-slot=command-group]"):
            shown = 0
            for child in group.querySelectorAll("[data-slot=command-item]"):
                if child.getAttribute("hidden") is None:
                    shown = shown + 1
            if shown == 0:
                group.setAttribute("hidden", "")
            else:
                group.removeAttribute("hidden")
        self.highlight(0)

    def keydown(self, event: KeyboardEvent):
        if event.key == "ArrowDown":
            event.preventDefault()
            self.highlight(self.navigation.index + 1)
            return
        if event.key == "ArrowUp":
            event.preventDefault()
            self.highlight(self.navigation.index - 1)
            return
        if event.key == "Enter":
            event.preventDefault()
            if self.enter_selects:
                self.emit_select()
            else:
                self.dispatchEvent(Event("command-submit", bubbles=True))
            return
        if event.key == "Escape":
            event.preventDefault()
            self.dispatchEvent(Event("command-cancel", bubbles=True))

    def item_clicked(self, event: Event):
        current = event.target
        if isinstance(current, Node) and not isinstance(current, Element):
            current = current.parentElement
        if not isinstance(current, Element):
            return
        row = current.closest("[data-slot=command-item]")
        if row is None or row.getAttribute("aria-disabled") == "true":
            return
        visible = self.visible_items()
        index = 0
        while index < len(visible):
            if visible[index] is row:
                self.highlight(index)
                self.emit_select()
                return
            index = index + 1


@js
class CommandDialog(Widget):
    def __init__(
        self,
        *items: CommandItem,
        title: str = "Command Palette",
        description: str = "Search for a command to run...",
        placeholder: str = "Type a command...",
        show_close: bool = True,
    ):
        super().__init__()
        self.command = ref(Command(*items, placeholder=placeholder))
        self.panel = ref(
            DialogContent(
                title,
                div(
                    tw("sr-only"),
                    DialogTitle(title),
                    DialogDescription(description),
                ),
                self.command,
                show_close=show_close,
            )
        )
        self.add(
            tw("contents"),
            {"data-slot": "command-dialog"},
            self.panel,
        )
        self.panel.addEventListener(DialogCloseRequest.event_name, self.close_requested)
        self.command.addEventListener("command-cancel", self.close_requested)

    def open(self) -> None:
        self.panel.show_modal()
        self.command.input.focus()

    def close(self) -> None:
        self.panel.close()

    def close_requested(self, event: Event) -> None:
        self.close()
