from pyjs import js
from pyjs.web.domx import require_element, span, tw
from pyjs.web.ui.dropdown_menu import (
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
)


@js
class SelectTrigger(DropdownMenuTrigger):
    def __init__(self, placeholder: str = "Select an option"):
        super().__init__(
            span({"data-slot": "select-value"}, placeholder),
            span(tw("ml-2 text-xs text-slate-500"), {"aria-hidden": "true"}, "▼"),
        )
        self.setAttribute("data-slot", "select-trigger")

    def set_value_text(self, value: str):
        value_element = require_element(self.element, "[data-slot=select-value]")
        value_element.textContent = value


@js
class SelectItem(DropdownMenuItem):
    def __init__(self, value: str, label: str, *children):
        super().__init__(value, label, *children)
        self.setAttribute("data-slot", "select-item")
        self.setAttribute("data-label", label)


@js
class SelectContent(DropdownMenuContent):
    def __init__(self, *children):
        super().__init__(*children)
        self.setAttribute("data-slot", "select-content")


@js
def SelectLabel(*children):
    label = DropdownMenuLabel(*children)
    label.setAttribute("data-slot", "select-label")
    return label


@js
def SelectSeparator():
    separator = DropdownMenuSeparator()
    separator.setAttribute("data-slot", "select-separator")
    return separator


@js
class Select(DropdownMenu):
    def __init__(
        self,
        trigger: SelectTrigger,
        content: SelectContent,
        *,
        value: str = "",
    ):
        super().__init__(trigger, content)
        self.setAttribute("data-slot", "select")
        if value != "":
            self.select(value)

    def select(self, value: str):
        self.selected_value = value
        self.set_data("value", value)
        for item in self.item_elements():
            selected = item.getAttribute("data-value") == value
            item.setAttribute("aria-selected", "true" if selected else "false")
            if selected:
                label = item.getAttribute("data-label")
                if label is not None:
                    value_element = require_element(
                        self.trigger.element, "[data-slot=select-value]"
                    )
                    value_element.textContent = label
        if self.content.getAttribute("data-state") == "open":
            self.close()
