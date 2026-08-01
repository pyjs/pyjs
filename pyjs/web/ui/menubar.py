from pyjs import js
from pyjs.web.domx import div, tw
from pyjs.web.ui.dropdown_menu import (
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
)


@js
def Menubar(*menus: DropdownMenu):
    return div(
        tw(
            "flex h-10 items-center gap-1 rounded-md border border-slate-200 bg-white p-1"
        ),
        {"aria-label": "Application menu", "data-slot": "menubar", "role": "menubar"},
        *menus,
    )


@js
def MenubarMenu(label: str, *items: DropdownMenuItem):
    trigger = DropdownMenuTrigger(label)
    trigger.setAttribute("data-slot", "menubar-trigger")
    trigger.setAttribute("role", "menuitem")
    content = DropdownMenuContent(*items)
    content.setAttribute("data-slot", "menubar-content")
    return DropdownMenu(trigger, content)


@js
def MenubarItem(value: str, *children):
    item = DropdownMenuItem(value, *children)
    item.setAttribute("data-slot", "menubar-item")
    return item


@js
def MenubarLabel(*children):
    label = DropdownMenuLabel(*children)
    label.setAttribute("data-slot", "menubar-label")
    return label


@js
def MenubarSeparator():
    separator = DropdownMenuSeparator()
    separator.setAttribute("data-slot", "menubar-separator")
    return separator
