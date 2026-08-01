from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.events import Event
from pyjs.web.ui.command import Command, CommandItem


@js
class Combobox(Command):
    def __init__(
        self,
        *items: CommandItem,
        placeholder: str = "Search options...",
        name: str = "",
    ):
        super().__init__(*items, placeholder=placeholder)
        self.selected_value = ""
        self.setAttribute("data-slot", "combobox")
        self.input.setAttribute("aria-autocomplete", "list")
        self.input.setAttribute("name", name)
        self.addEventListener("click", self.item_clicked)

    def select(self, value: str):
        self.selected_value = value
        self.input.value = value
        self.input.setAttribute("aria-expanded", "false")
        for item in self.items:
            item.setAttribute("aria-selected", "true" if item.value == value else "false")

    def item_clicked(self, event: Event):
        target: Element = event.target
        item = target.closest("[data-slot=command-item]")
        if item is None or item.getAttribute("aria-disabled") == "true":
            return
        value = item.getAttribute("data-value")
        if value is not None:
            self.select(value)
