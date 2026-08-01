from pyjs import js
from pyjs.web.dom import Element, document
from pyjs.web.domx import ProxyElement, button, tag, tw
from pyjs.web.events import Event, KeyboardEvent
from pyjs.web.ui import Widget
from pyjs.web.ui.floating import FloatingPanel, FloatingPosition


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
        self.menu: DropdownMenu | None = None
        self.element = button(
            tw(
                "block w-full rounded-sm px-2 py-1.5 text-left text-sm "
                "hover:bg-slate-100 focus:bg-slate-100 focus:outline-none"
            ),
            {
                "data-slot": "dropdown-menu-item",
                "role": "menuitem",
                "tabindex": "-1",
            },
            *children,
        )
        self.element.addEventListener("click", self.select)

    def select(self, event: Event):
        if self.menu is not None:
            self.menu.select(self.value)

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
        self.items: list[DropdownMenuItem] = []
        for child in children:
            if isinstance(child, DropdownMenuItem):
                self.items.append(child)


@js
class DropdownMenuClickListener:
    def __init__(self, menu: DropdownMenu):
        self.menu = menu

    @js(include=True)
    def handleEvent(self, event: Event):
        self.menu.handle_document_click(event)


@js
class DropdownMenuKeyListener:
    def __init__(self, menu: DropdownMenu):
        self.menu = menu

    @js(include=True)
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
        open_event: str = "click",
    ):
        super().__init__()
        self.trigger = trigger
        self.content = content
        self.side = side
        self.align = align
        self.side_offset = side_offset
        self.align_offset = align_offset
        self.is_open = False
        self.selected_value = ""
        self.focused_index = -1
        self.click_listener = DropdownMenuClickListener(self)
        self.key_listener = DropdownMenuKeyListener(self)

        content_id = self.content.get_component_id() + "-content"
        self.content.setAttribute("id", content_id)
        self.trigger.setAttribute("aria-controls", content_id)
        self.trigger.element.addEventListener(open_event, self.toggle)
        self.trigger.on_keydown(self.handle_trigger_keydown)
        for item in self.content.items:
            item.menu = self
        self.add(self.trigger)

    def open(self) -> FloatingPosition:
        position = self.content.open(
            self.trigger.element,
            side=self.side,
            align=self.align,
            side_offset=self.side_offset,
            align_offset=self.align_offset,
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
        target: Element = event.target
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
        if len(self.content.items) == 0:
            return
        target: Element = event.target
        if self.contains(target):
            return
        event.preventDefault()
        if event.key == "Home":
            next_index = 0
        elif event.key == "End":
            next_index = len(self.content.items) - 1
        elif event.key == "ArrowDown":
            next_index = self.focused_index + 1
        else:
            next_index = self.focused_index - 1
        next_index += len(self.content.items)
        self.focused_index = next_index % len(self.content.items)
        self.content.items[self.focused_index].element.focus()

    def handle_trigger_keydown(self, event: KeyboardEvent):
        if event.key != "ArrowDown" and event.key != "ArrowUp":
            return
        if len(self.content.items) == 0:
            return
        event.preventDefault()
        if not self.is_open:
            self.open()
        if event.key == "ArrowDown":
            self.focused_index = 0
        else:
            self.focused_index = len(self.content.items) - 1
        self.content.items[self.focused_index].element.focus()

    def select(self, value: str):
        self.selected_value = value
        self.close()
        self.trigger.element.focus()
