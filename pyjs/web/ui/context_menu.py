from pyjs import js
from pyjs.web.domx import div, tw
from pyjs.web.events import Event
from pyjs.web.ui.dropdown_menu import (
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
)


@js
class ContextMenuTrigger(DropdownMenuTrigger):
    def __init__(self, *children):
        self.element = div(
            tw("contents"),
            {
                "aria-expanded": "false",
                "aria-haspopup": "menu",
                "data-slot": "context-menu-trigger",
                "tabindex": "0",
            },
            *children,
        )


@js
class ContextMenuItem(DropdownMenuItem):
    def __init__(self, value: str, *children):
        super().__init__(value, *children)
        self.setAttribute("data-slot", "context-menu-item")


@js
class ContextMenuContent(DropdownMenuContent):
    def __init__(self, *children):
        super().__init__(*children)
        self.setAttribute("data-slot", "context-menu-content")


@js
def ContextMenuLabel(*children):
    label = DropdownMenuLabel(*children)
    label.setAttribute("data-slot", "context-menu-label")
    return label


@js
def ContextMenuSeparator():
    separator = DropdownMenuSeparator()
    separator.setAttribute("data-slot", "context-menu-separator")
    return separator


@js
class ContextMenu(DropdownMenu):
    def __init__(self, trigger: ContextMenuTrigger, content: ContextMenuContent):
        super().__init__(trigger, content, open_event="contextmenu")
        self.setAttribute("data-slot", "context-menu")

    def toggle(self, event: Event):
        event.preventDefault()
        super().toggle(event)
