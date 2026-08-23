from typing import cast

from pyjs import js
from pyjs.web.dom import Element, document
from pyjs.web.domx import ProxyElement, button, ref, tag, tw
from pyjs.web.events import Event, KeyboardEvent
from pyjs.web.html import HTMLElement
from pyjs.web.ui import Widget
from pyjs.web.ui.floating import FloatingPanel, FloatingPosition


@js.inline("{element}")
def dropdown_item_element(element: Element) -> HTMLElement:
    if not isinstance(element, HTMLElement):
        raise TypeError("Dropdown menu items must be HTML elements.")
    return element


@js
class DropdownMenuTrigger(ProxyElement):
    def __init__(self, *children):
        self.element = button(
            tw(
                "rounded-md border border-slate-300 bg-white px-3 py-2 text-sm "
                "font-medium text-slate-900 shadow-sm"
            ),
            {
                "aria-expanded": "false",
                "aria-haspopup": "menu",
                "data-slot": "dropdown-menu-trigger",
            },
            *children,
        )

    def on_click(self, callback: callable):
        self.element.addEventListener("click", callback)

    def on_keydown(self, callback: callable):
        self.element.addEventListener("keydown", callback)

    def set_expanded(self, expanded: bool):
        self.element.setAttribute("aria-expanded", "true" if expanded else "false")


@js
class DropdownMenuItem(ProxyElement):
    def __init__(self, value: str, *children):
        self.value = value
        self.element = button(
            tw(
                "block w-full rounded-sm px-2 py-1.5 text-left text-sm "
                "hover:bg-slate-100 focus:bg-slate-100 focus:outline-none"
            ),
            {
                "data-slot": "dropdown-menu-item",
                "data-value": value,
                "role": "menuitem",
                "tabindex": "-1",
            },
            *children,
        )

    def on_select(self, callback: callable):
        self.element.addEventListener("click", callback)


@js
def DropdownMenuLabel(*children):
    return tag(
        "div",
        tw("px-2 py-1.5 text-sm font-semibold"),
        {"data-slot": "dropdown-menu-label"},
        *children,
    )


@js
def DropdownMenuSeparator():
    return tag(
        "div",
        tw("-mx-1 my-1 h-px bg-slate-200"),
        {"data-slot": "dropdown-menu-separator", "role": "separator"},
    )


@js
class DropdownMenuContent(FloatingPanel):
    def __init__(self, *children):
        self.items: list[HTMLElement] = []
        for child in children:
            if isinstance(child, DropdownMenuItem):
                self.items.append(child.element)
        super().__init__(
            tw(
                "min-w-48 rounded-md border border-slate-200 bg-white p-1 text-slate-950 shadow-md"
            ),
            {
                "data-slot": "dropdown-menu-content",
                "role": "menu",
            },
            *children,
        )
        self.style.width = "192px"


@js
class DropdownMenuClickListener:
    def __init__(self, menu: DropdownMenu):
        self.menu = menu

    def handleEvent(self, event: Event):
        self.menu.handle_document_click(event)


@js
class DropdownMenuKeyListener:
    def __init__(self, menu: DropdownMenu):
        self.menu = menu

    def handleEvent(self, event: KeyboardEvent):
        self.menu.handle_keydown(event)


@js
class DropdownMenu(Widget):
    def __init__(
        self,
        trigger: DropdownMenuTrigger,
        content: DropdownMenuContent,
        side: str = "bottom",
        align: str = "start",
        side_offset: int = 4,
        align_offset: int = 0,
    ):
        super().__init__()
        self.trigger = ref(trigger)
        self.content = ref(content)
        self.items = content.items
        self.content.setAttribute("id", self.get_component_id() + "-content")
        self.trigger.setAttribute(
            "aria-controls", self.get_component_id() + "-content"
        )
        self.add(
            {
                "data-align": align,
                "data-align-offset": str(align_offset),
                "data-side": side,
                "data-side-offset": str(side_offset),
            },
            self.trigger,
            self.content,
        )

    def initialize(self):
        self.items = []
        for item in self.content.querySelectorAll("[role=menuitem][data-value]"):
            self.items.append(dropdown_item_element(item))
        self.is_open = False
        self.selected_value = self.get_data("value") or ""
        self.focused_index = -1
        self.click_listener = DropdownMenuClickListener(self)
        self.key_listener = DropdownMenuKeyListener(self)
        open_event = (
            "contextmenu"
            if self.trigger.getAttribute("data-slot") == "context-menu-trigger"
            else "click"
        )
        self.trigger.element.addEventListener(open_event, self.toggle)
        self.trigger.on_keydown(self.handle_trigger_keydown)
        self.content.addEventListener("click", self.item_clicked)

    def item_elements(self) -> list[HTMLElement]:
        return self.items

    def item_clicked(self, event: Event):
        target = cast(Element, event.target)
        item = target.closest("[role=menuitem][data-value]")
        if item is None:
            return
        value = item.getAttribute("data-value")
        if value is not None:
            self.select(value)

    def open(self) -> FloatingPosition:
        side = self.get_data("side") or "bottom"
        align = self.get_data("align") or "start"
        side_offset = int(self.get_data("side-offset") or "4")
        align_offset = int(self.get_data("align-offset") or "0")
        position = self.content.open(
            self.trigger.element,
            side=side,
            align=align,
            side_offset=side_offset,
            align_offset=align_offset,
        )
        self.is_open = True
        self.trigger.set_expanded(True)
        document.addEventListener("click", self.click_listener)
        document.addEventListener("keydown", self.key_listener)
        return position

    def close(self):
        document.removeEventListener("click", self.click_listener)
        document.removeEventListener("keydown", self.key_listener)
        self.content.close()
        self.is_open = False
        self.focused_index = -1
        self.trigger.set_expanded(False)

    def toggle(self, event: Event):
        if self.is_open:
            self.close()
        else:
            self.open()

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
            self.close()
            self.trigger.element.focus()
            return
        if (
            event.key != "ArrowDown"
            and event.key != "ArrowUp"
            and event.key != "Home"
            and event.key != "End"
        ):
            return
        items = self.item_elements()
        if len(items) == 0:
            return
        target = cast(Element, event.target)
        if self.contains(target):
            return
        event.preventDefault()
        if event.key == "Home":
            next_index = 0
        elif event.key == "End":
            next_index = len(items) - 1
        elif event.key == "ArrowDown":
            next_index = self.focused_index + 1
        else:
            next_index = self.focused_index - 1
        next_index += len(items)
        self.focused_index = next_index % len(items)
        items[self.focused_index].focus()

    def handle_trigger_keydown(self, event: KeyboardEvent):
        if event.key != "ArrowDown" and event.key != "ArrowUp":
            return
        items = self.item_elements()
        if len(items) == 0:
            return
        event.preventDefault()
        if not self.is_open:
            self.open()
        if event.key == "ArrowDown":
            self.focused_index = 0
        else:
            self.focused_index = len(items) - 1
        items[self.focused_index].focus()

    def select(self, value: str):
        self.selected_value = value
        self.set_data("value", value)
        self.close()
        self.trigger.element.focus()
