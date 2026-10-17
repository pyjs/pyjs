from typing import cast

from pyjs import js
from pyjs.web.dom import Element, document
from pyjs.web.domx import ProxyElement, button, div, input, ref, span, tw
from pyjs.web.events import Event, KeyboardEvent
from pyjs.web.html import HTMLElement
from pyjs.web.ui import Widget
from pyjs.web.ui.floating import FloatingPanel


@js
class ComboboxItem(ProxyElement):
    def __init__(self, value: str, label: str, *children, disabled: bool = False):
        self.value = value
        self.label = label
        attributes = {
            "aria-disabled": "true" if disabled else "false",
            "data-label": label,
            "data-slot": "combobox-item",
            "data-value": value,
            "role": "option",
            "tabindex": "-1",
        }
        shown = label
        if len(children) > 0:
            self.element = div(
                tw(
                    "flex cursor-default items-center rounded-sm px-2 py-1.5 text-sm "
                    "outline-none hover:bg-slate-100 aria-selected:bg-slate-100 "
                    "data-[highlighted]:bg-slate-100 aria-disabled:opacity-50"
                ),
                attributes,
                *children,
            )
            return
        self.element = div(
            tw(
                "flex cursor-default items-center rounded-sm px-2 py-1.5 text-sm "
                "outline-none hover:bg-slate-100 aria-selected:bg-slate-100 "
                "data-[highlighted]:bg-slate-100 aria-disabled:opacity-50"
            ),
            attributes,
            shown,
        )


@js
class ComboboxContent(FloatingPanel):
    def __init__(self, *children):
        super().__init__(
            tw("min-w-56 rounded-md border border-slate-200 bg-white p-0 shadow-md"),
            {"data-slot": "combobox-content"},
            *children,
        )


@js
class ComboboxChip(ProxyElement):
    def __init__(self, value: str, label: str):
        self.value = value
        self.element = span(
            tw(
                "inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 "
                "text-xs text-slate-700"
            ),
            {"data-slot": "combobox-chip", "data-value": value},
            label,
            button(
                tw("inline-flex size-4 items-center justify-center rounded-full hover:bg-slate-200"),
                {
                    "aria-label": "Remove " + label,
                    "data-chip-remove": value,
                    "type": "button",
                },
                "×",
            ),
        )


@js
class ComboboxClickListener:
    def __init__(self, combobox: Combobox):
        self.combobox = combobox

    def handleEvent(self, event: Event):
        self.combobox.handle_document_click(event)


@js
class Combobox(Widget):
    def __init__(
        self,
        *items: ComboboxItem,
        placeholder: str = "Search options...",
        name: str = "",
        multiple: bool = False,
    ):
        super().__init__()
        self.placeholder = placeholder
        self.multiple = multiple
        self.selected_value = ""
        self.selected_values: list[str] = []
        self.selected = 0
        self.is_open = False
        self.items: list[HTMLElement] = []
        for item in items:
            self.items.append(cast(HTMLElement, item.element))
        self.input = ref(
            input(
                tw("h-9 min-w-0 flex-1 border-0 bg-transparent px-3 text-sm outline-none"),
                {
                    "aria-autocomplete": "list",
                    "aria-expanded": "false",
                    "autocomplete": "off",
                    "data-slot": "combobox-input",
                    "name": name,
                    "placeholder": placeholder,
                    "role": "combobox",
                },
            )
        )
        self.clear = ref(
            button(
                tw(
                    "inline-flex size-7 items-center justify-center rounded-sm text-slate-500 "
                    "hover:bg-slate-100"
                ),
                {
                    "aria-label": "Clear selection",
                    "data-slot": "combobox-clear",
                    "hidden": "",
                    "type": "button",
                },
                "×",
            )
        )
        self.trigger = ref(
            button(
                tw(
                    "inline-flex size-7 items-center justify-center rounded-sm text-slate-500 "
                    "hover:bg-slate-100"
                ),
                {
                    "aria-label": "Open options",
                    "data-slot": "combobox-trigger",
                    "type": "button",
                },
                "▾",
            )
        )
        self.chips = ref(
            div(
                tw("flex flex-wrap gap-1 px-2 pt-1"),
                {"data-slot": "combobox-chips", "hidden": ""},
            )
        )
        self.empty = ref(
            div(
                tw("px-2 py-4 text-center text-sm text-slate-500"),
                {"data-slot": "combobox-empty", "hidden": ""},
                "No results found.",
            )
        )
        self.list = ref(
            div(
                tw("max-h-60 overflow-y-auto p-1"),
                {"data-slot": "combobox-list", "role": "listbox"},
                self.empty,
                *items,
            )
        )
        self.panel = ref(ComboboxContent(self.list))
        self.add(
            tw("relative inline-flex min-w-48 flex-col rounded-md border border-slate-300 bg-white"),
            {
                "data-multiple": "true" if multiple else "false",
                "data-slot": "combobox",
            },
            self.chips,
            div(
                tw("flex items-center"),
                self.input,
                self.clear,
                self.trigger,
            ),
            self.panel,
        )

    def initialize(self):
        self.items = []
        for item in self.querySelectorAll("[data-slot=combobox-item]"):
            if isinstance(item, HTMLElement):
                self.items.append(item)
        self.selected_value = self.get_data("value") or ""
        self.selected_values = []
        stored = self.get_data("values") or ""
        if stored != "":
            parts = stored.split(",")
            for part in parts:
                if part != "":
                    self.selected_values.append(part)
        self.selected = 0
        self.is_open = False
        self.multiple = self.getAttribute("data-multiple") == "true"
        self.click_listener = ComboboxClickListener(self)
        self.input.addEventListener("input", self.on_input)
        self.input.addEventListener("keydown", self.keydown)
        self.input.addEventListener("focus", self.open)
        self.trigger.addEventListener("click", self.toggle)
        self.clear.addEventListener("click", self.clear_clicked)
        self.list.addEventListener("click", self.item_clicked)
        self.chips.addEventListener("click", self.chip_clicked)
        self._sync_clear()
        self._sync_chips()

    def disconnected(self):
        self.close()

    def visible_items(self) -> list[HTMLElement]:
        found: list[HTMLElement] = []
        for item in self.items:
            if item.getAttribute("hidden") is not None:
                continue
            if item.getAttribute("aria-disabled") == "true":
                continue
            found.append(item)
        return found

    def highlight(self, index: int) -> None:
        visible = self.visible_items()
        if len(visible) == 0:
            self.selected = 0
            return
        if index < 0:
            index = len(visible) - 1
        if index >= len(visible):
            index = 0
        self.selected = index
        for item in self.items:
            item.removeAttribute("data-highlighted")
        visible[index].setAttribute("data-highlighted", "true")
        self._sync_aria_selected()

    def highlighted_item(self) -> HTMLElement | None:
        visible = self.visible_items()
        if self.selected < 0 or self.selected >= len(visible):
            return None
        return visible[self.selected]

    def open(self, event: Event | None = None) -> None:
        if self.is_open:
            return
        self.is_open = True
        self.input.setAttribute("aria-expanded", "true")
        self.panel.open(self.input, side="bottom", align="start")
        document.addEventListener("click", self.click_listener)
        self.filter_items()
        self.highlight(0)

    def close(self) -> None:
        if not self.is_open:
            return
        document.removeEventListener("click", self.click_listener)
        self.panel.close()
        self.is_open = False
        self.input.setAttribute("aria-expanded", "false")

    def toggle(self, event: Event) -> None:
        event.preventDefault()
        if self.is_open:
            self.close()
        else:
            self.open()
            self.input.focus()

    def handle_document_click(self, event: Event) -> None:
        target = cast(Element, event.target)
        if self.contains(target) or self.panel.contains(target):
            return
        self.close()

    def filter_items(self) -> None:
        query = self.input.value.lower()
        if not self.multiple and self.selected_value != "" and query == self._label_for(
            self.selected_value
        ).lower():
            query = ""
        visible_count = 0
        for item in self.items:
            value = item.getAttribute("data-value") or ""
            label = item.getAttribute("data-label") or value
            visible = query == "" or query in label.lower() or query in value.lower()
            if visible:
                item.removeAttribute("hidden")
                visible_count = visible_count + 1
            else:
                item.setAttribute("hidden", "")
        if visible_count == 0:
            self.empty.removeAttribute("hidden")
        else:
            self.empty.setAttribute("hidden", "")
        self.highlight(0)

    def on_input(self, event: Event) -> None:
        self.open()
        self.filter_items()

    def keydown(self, event: KeyboardEvent) -> None:
        if event.key == "ArrowDown":
            event.preventDefault()
            if not self.is_open:
                self.open()
            self.highlight(self.selected + 1)
            return
        if event.key == "ArrowUp":
            event.preventDefault()
            if not self.is_open:
                self.open()
            self.highlight(self.selected - 1)
            return
        if event.key == "Enter":
            event.preventDefault()
            item = self.highlighted_item()
            if item is not None:
                self._choose(item)
            return
        if event.key == "Escape":
            event.preventDefault()
            self.close()

    def item_clicked(self, event: Event) -> None:
        current = event.target
        if not isinstance(current, Element):
            return
        row = current.closest("[data-slot=combobox-item]")
        if row is None or row.getAttribute("aria-disabled") == "true":
            return
        self._choose(row)

    def _choose(self, item: Element) -> None:
        value = item.getAttribute("data-value")
        if value is None or value == "":
            return
        if self.multiple:
            self._toggle_value(value)
            self.input.value = ""
            self.filter_items()
            return
        self.select(value)
        self.close()

    def select(self, value: str) -> None:
        self.selected_value = value
        self.set_data("value", value)
        label = self._label_for(value)
        self.input.value = label
        for item in self.items:
            selected = item.getAttribute("data-value") == value
            item.setAttribute("aria-selected", "true" if selected else "false")
        self._sync_clear()

    def _toggle_value(self, value: str) -> None:
        kept: list[str] = []
        found = False
        for current in self.selected_values:
            if current == value:
                found = True
            else:
                kept.append(current)
        if not found:
            kept.append(value)
        self.selected_values = kept
        joined = ""
        for part in kept:
            if joined != "":
                joined = joined + ","
            joined = joined + part
        self.set_data("values", joined)
        self._sync_chips()
        self._sync_clear()
        self._sync_aria_selected()

    def _sync_aria_selected(self) -> None:
        for item in self.items:
            value = item.getAttribute("data-value") or ""
            selected = False
            if self.multiple:
                for current in self.selected_values:
                    if current == value:
                        selected = True
            elif value == self.selected_value:
                selected = True
            item.setAttribute("aria-selected", "true" if selected else "false")

    def _label_for(self, value: str) -> str:
        for item in self.items:
            if item.getAttribute("data-value") == value:
                return item.getAttribute("data-label") or value
        return value

    def _sync_clear(self) -> None:
        has_value = self.selected_value != "" or len(self.selected_values) > 0
        if has_value:
            self.clear.removeAttribute("hidden")
        else:
            self.clear.setAttribute("hidden", "")

    def _sync_chips(self) -> None:
        if not self.multiple:
            self.chips.setAttribute("hidden", "")
            return
        if len(self.selected_values) == 0:
            self.chips.setAttribute("hidden", "")
            self.chips.replaceChildren()
            return
        self.chips.removeAttribute("hidden")
        chips: list[Element] = []
        for value in self.selected_values:
            chips.append(ComboboxChip(value, self._label_for(value)).element)
        self.chips.replaceChildren(*chips)

    def chip_clicked(self, event: Event) -> None:
        current = event.target
        if not isinstance(current, Element):
            return
        remove = current.closest("[data-chip-remove]")
        if remove is None:
            return
        value = remove.getAttribute("data-chip-remove")
        if value is None:
            return
        self._toggle_value(value)

    def clear_clicked(self, event: Event) -> None:
        event.preventDefault()
        event.stopPropagation()
        self.selected_value = ""
        self.selected_values = []
        self.set_data("value", "")
        self.set_data("values", "")
        self.input.value = ""
        self._sync_chips()
        self._sync_clear()
        self.filter_items()
        self.input.focus()
