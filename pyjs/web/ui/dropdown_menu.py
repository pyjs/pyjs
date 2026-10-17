from typing import cast

from pyjs import js
from pyjs.web.dom import Element, document
from pyjs.web.domx import ProxyElement, button, ref, span, tag, tw
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
def DropdownMenuShortcut(*children):
    return span(
        tw("ml-auto text-xs tracking-widest text-slate-400"),
        {"data-slot": "dropdown-menu-shortcut"},
        *children,
    )


@js
class DropdownMenuCheckboxItem(DropdownMenuItem):
    def __init__(self, value: str, *children, checked: bool = False):
        super().__init__(value, *children)
        self.setAttribute("role", "menuitemcheckbox")
        self.setAttribute("aria-checked", "true" if checked else "false")
        self.setAttribute("data-checked", "true" if checked else "false")
        self.setAttribute("data-slot", "dropdown-menu-checkbox-item")


@js
class DropdownMenuRadioItem(DropdownMenuItem):
    def __init__(self, value: str, *children, checked: bool = False):
        super().__init__(value, *children)
        self.setAttribute("role", "menuitemradio")
        self.setAttribute("aria-checked", "true" if checked else "false")
        self.setAttribute("data-checked", "true" if checked else "false")
        self.setAttribute("data-slot", "dropdown-menu-radio-item")


@js
class DropdownMenuSubTrigger(DropdownMenuItem):
    def __init__(self, value: str, *children):
        super().__init__(value, *children, span(tw("ml-auto text-xs"), "▸"))
        self.setAttribute("aria-haspopup", "menu")
        self.setAttribute("data-slot", "dropdown-menu-sub-trigger")


@js
class DropdownMenuContent(FloatingPanel):
    def __init__(self, *children):
        self.items: list[HTMLElement] = []
        for child in children:
            if isinstance(child, DropdownMenuItem):
                self.items.append(cast(HTMLElement, child.element))
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
class DropdownMenuSubContent(DropdownMenuContent):
    def __init__(self, *children):
        super().__init__(*children)
        self.setAttribute("data-slot", "dropdown-menu-sub-content")


@js
class DropdownMenuSub(Widget):
    def __init__(
        self, trigger: DropdownMenuSubTrigger, content: DropdownMenuSubContent
    ):
        super().__init__()
        self.trigger = ref(trigger)
        self.panel = ref(content)
        self.owner: Widget | None = None
        self.add(
            {"data-slot": "dropdown-menu-sub", "data-state": "closed"},
            self.trigger,
            self.panel,
        )

    def initialize(self):
        owner: Widget | None = None
        current: Element | None = self.parentElement
        while current is not None:
            if isinstance(current, DropdownMenu):
                owner = current
                break
            current = current.parentElement
        self.owner = owner
        self.trigger.element.addEventListener("mouseenter", self.open_sub)
        self.trigger.element.addEventListener("keydown", self.sub_keydown)
        self.panel.addEventListener("click", self.panel_clicked)

    def panel_clicked(self, event: Event) -> None:
        owner = self.owner
        if isinstance(owner, DropdownMenu):
            owner.item_clicked(event)

    def _containing_panel(self) -> Element | None:
        current: Element | None = self.parentElement
        while current is not None:
            slot = current.getAttribute("data-slot") or ""
            if slot == "dropdown-menu-content" or slot == "dropdown-menu-sub-content":
                return current
            current = current.parentElement
        return None

    def open_sub(self, event: Event) -> None:
        owner = self.owner
        if isinstance(owner, DropdownMenu):
            panel = self._containing_panel()
            for sub in owner._submenus():
                if sub is not self and sub.is_sub_open() and sub._containing_panel() is panel:
                    sub.close_sub()
        self.panel.open(self.trigger.element, side="right", align="start")
        self.setAttribute("data-state", "open")

    def close_sub(self) -> None:
        self.panel.close()
        self.setAttribute("data-state", "closed")

    def is_sub_open(self) -> bool:
        return self.getAttribute("data-state") == "open"

    def disconnected(self):
        parent = self.panel.parentElement
        if parent is document.body:
            self.close_sub()

    def sub_keydown(self, event: KeyboardEvent) -> None:
        if event.key != "ArrowRight":
            return
        event.preventDefault()
        self.open_sub(event)
        items = self.panel_items()
        if len(items) == 0:
            return
        items[0].focus()
        owner = self.owner
        if isinstance(owner, DropdownMenu):
            owner.focused_index = 0

    def panel_items(self) -> list[HTMLElement]:
        found: list[HTMLElement] = []
        for item in self.panel.querySelectorAll("[data-value]"):
            role = item.getAttribute("role") or ""
            if (
                role != "menuitem"
                and role != "menuitemcheckbox"
                and role != "menuitemradio"
            ):
                continue
            if self._is_deeper_nested_item(item):
                continue
            found.append(dropdown_item_element(item))
        return found

    def _is_deeper_nested_item(self, item: Element) -> bool:
        current: Element | None = item.parentElement
        while current is not None and current is not self.panel:
            slot = current.getAttribute("data-slot") or ""
            if slot == "dropdown-menu-sub-content":
                return True
            current = current.parentElement
        return False


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
                "data-slot": "dropdown-menu",
            },
            self.trigger,
            self.content,
        )

    def initialize(self):
        self.items = []
        for item in self.content.querySelectorAll("[data-value]"):
            if self._is_menu_item(item):
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

    def _is_menu_item(self, item: Element) -> bool:
        role = item.getAttribute("role") or ""
        return (
            role == "menuitem"
            or role == "menuitemcheckbox"
            or role == "menuitemradio"
        )

    def _submenus(self) -> list[DropdownMenuSub]:
        found: list[DropdownMenuSub] = []
        pending: list[Element] = [self.content]
        index = 0
        while index < len(pending):
            root = pending[index]
            index = index + 1
            for node in root.querySelectorAll("[data-slot=dropdown-menu-sub]"):
                if not isinstance(node, DropdownMenuSub):
                    continue
                already = False
                for existing in found:
                    if existing is node:
                        already = True
                if already:
                    continue
                found.append(node)
                pending.append(node.panel)
        return found

    def _close_open_submenu(self) -> bool:
        sub = self._open_submenu()
        if sub is None:
            return False
        sub.close_sub()
        trigger = cast(HTMLElement, sub.trigger.element)
        trigger.focus()
        items = self.item_elements()
        index = 0
        while index < len(items):
            if items[index] is trigger:
                self.focused_index = index
                break
            index = index + 1
        return True

    def disconnected(self):
        if self.is_open:
            self.close()
            return
        for sub in self._submenus():
            sub.close_sub()

    def _is_nested_item(self, item: HTMLElement) -> bool:
        current: Element | None = item
        while current is not None:
            slot = current.getAttribute("data-slot") or ""
            if slot == "dropdown-menu-sub-content":
                return True
            current = current.parentElement
        return False

    def _parent_items(self) -> list[HTMLElement]:
        found: list[HTMLElement] = []
        for item in self.items:
            if self._is_nested_item(item):
                continue
            found.append(item)
        return found

    def _open_submenu(self) -> DropdownMenuSub | None:
        found: DropdownMenuSub | None = None
        for sub in self._submenus():
            if sub.is_sub_open():
                found = sub
        return found

    def item_elements(self) -> list[HTMLElement]:
        sub = self._open_submenu()
        if sub is not None:
            return sub.panel_items()
        return self._parent_items()

    def item_clicked(self, event: Event):
        target = cast(Element, event.target)
        item = target.closest("[data-value]")
        if item is None or not self._is_menu_item(item):
            return
        if item.getAttribute("aria-haspopup") == "menu":
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
        for sub in self._submenus():
            sub.close_sub()
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
        for sub in self._submenus():
            if sub.contains(target) or sub.panel.contains(target):
                return
        self.close()

    def handle_keydown(self, event: KeyboardEvent):
        if event.key == "Escape" and self.is_open:
            event.preventDefault()
            if self._close_open_submenu():
                return
            self.close()
            cast(HTMLElement, self.trigger.element).focus()
            return
        if event.key == "ArrowLeft" and self.is_open:
            if self._close_open_submenu():
                event.preventDefault()
                return
        if (event.key == "Enter" or event.key == " ") and self.is_open:
            items = self.item_elements()
            chosen: HTMLElement | None = None
            if self.focused_index >= 0 and self.focused_index < len(items):
                chosen = items[self.focused_index]
            else:
                target = cast(Element, event.target)
                closest = target.closest("[data-value]")
                if isinstance(closest, HTMLElement) and self._is_menu_item(closest):
                    chosen = closest
            if chosen is None:
                return
            if chosen.getAttribute("aria-haspopup") == "menu":
                return
            value = chosen.getAttribute("data-value")
            if value is None:
                return
            event.preventDefault()
            self.select(value)
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
        items = self._parent_items()
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
        chosen: HTMLElement | None = None
        for item in self.items:
            if item.getAttribute("data-value") == value:
                chosen = item
        if chosen is not None:
            role = chosen.getAttribute("role")
            if role == "menuitemcheckbox":
                checked = chosen.getAttribute("aria-checked") != "true"
                chosen.setAttribute("aria-checked", "true" if checked else "false")
                chosen.setAttribute("data-checked", "true" if checked else "false")
                self.selected_value = value
                self.set_data("value", value)
                return
            if role == "menuitemradio":
                for item in self.items:
                    if item.getAttribute("role") == "menuitemradio":
                        same = item.getAttribute("data-value") == value
                        item.setAttribute("aria-checked", "true" if same else "false")
                        item.setAttribute("data-checked", "true" if same else "false")
                self.selected_value = value
                self.set_data("value", value)
                self.close()
                cast(HTMLElement, self.trigger.element).focus()
                return
        self.selected_value = value
        self.set_data("value", value)
        self.close()
        cast(HTMLElement, self.trigger.element).focus()
