from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.domx import input, ref, tag, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget


@js
class RadioGroupItem(Widget):
    def __init__(self, value: str, *children, checked: bool = False):
        super().__init__()
        self.control = ref(
            input(
                tw(
                    "size-4 shrink-0 cursor-pointer accent-slate-950 focus-visible:outline-none "
                    "focus-visible:ring-2 focus-visible:ring-slate-400 disabled:opacity-50"
                ),
                {
                    "data-slot": "radio-group-control",
                    "type": "radio",
                    "value": value,
                },
            )
        )
        self.add(
            tw("block"),
            {
                "data-slot": "radio-group-item",
                "data-state": "checked" if checked else "unchecked",
                "data-value": value,
            },
            tag(
                "label",
                tw("flex cursor-pointer items-center gap-2 text-sm text-slate-950"),
                self.control,
                *children,
            ),
        )
        self.set_checked(checked)

    def get_value(self) -> str:
        value = self.getAttribute("data-value")
        if value is None:
            return ""
        return value

    def is_checked(self) -> bool:
        return self.control.checked

    def set_checked(self, checked: bool):
        self.control.checked = checked
        self.setAttribute("data-state", "checked" if checked else "unchecked")
        if checked:
            self.control.setAttribute("checked", "")
        else:
            self.control.removeAttribute("checked")

    def set_name(self, name: str):
        self.control.setAttribute("name", name)


@js
class RadioGroup(Widget):
    def __init__(
        self,
        *items: RadioGroupItem,
        value: str = "",
        name: str = "",
        orientation: str = "vertical",
    ):
        super().__init__()
        values: list[str] = []
        selected_value = value
        group_name = name
        if group_name == "":
            group_name = self.get_component_id()
        for item in items:
            item_value = item.get_value()
            for existing in values:
                if existing == item_value:
                    raise ValueError(
                        "RadioGroupItem values must be unique within a RadioGroup"
                    )
            values.append(item_value)
            item.set_name(group_name)
            if value == "" and item.is_checked():
                selected_value = item_value
            elif value != "":
                item.set_checked(item_value == value)
        self.add(
            tw(
                "grid gap-3 data-[orientation=horizontal]:flex "
                "data-[orientation=horizontal]:items-center"
            ),
            {
                "aria-orientation": orientation,
                "data-orientation": orientation,
                "data-slot": "radio-group",
                "data-value": selected_value,
                "role": "radiogroup",
            },
            *items,
        )
        self.addEventListener("change", self.changed)

    def get_items(self) -> list[RadioGroupItem]:
        items: list[RadioGroupItem] = self.children
        return items

    def current_value(self) -> str:
        value = self.getAttribute("data-value")
        if value is None:
            return ""
        return value

    def select(self, value: str, focus: bool = False):
        for item in self.get_items():
            checked = item.get_value() == value
            item.set_checked(checked)
            if checked and focus:
                item.control.focus()
        self.setAttribute("data-value", value)

    def changed(self, event: Event):
        target: Element = event.target
        for item in self.get_items():
            if item.control.contains(target):
                self.select(item.get_value())
                return
