from typing import cast

from pyjs import js
from pyjs.web.domx import ProxyElement, input, tag, tw
from pyjs.web.html import HTMLInputElement


@js
class Checkbox(ProxyElement):
    def __init__(self, name: str = "", checked: bool = False):
        self.element = input(
            tw(
                "size-4 shrink-0 cursor-pointer rounded border border-slate-300 bg-white "
                "accent-slate-950 focus-visible:outline-none focus-visible:ring-2 "
                "focus-visible:ring-slate-400 disabled:cursor-not-allowed disabled:opacity-50 "
                "aria-invalid:border-red-500 aria-invalid:ring-2 aria-invalid:ring-red-100"
            ),
            {"data-slot": "checkbox", "name": name, "type": "checkbox"},
        )
        cast(HTMLInputElement, self.element).checked = checked
        if checked:
            self.element.setAttribute("checked", "")

    def is_checked(self) -> bool:
        return cast(HTMLInputElement, self.element).checked

    def set_checked(self, checked: bool):
        cast(HTMLInputElement, self.element).checked = checked

    def set_invalid(self, invalid: bool):
        self.element.setAttribute("aria-invalid", "true" if invalid else "false")

    def on_change(self, callback: callable):
        self.element.addEventListener("change", callback)


@js
def CheckboxTarget(checkbox: Checkbox):
    """Give an unlabelled standalone checkbox a 36px native activation area.

    The input remains the sole focusable control and owns checked, disabled,
    form and change-event semantics. Set its accessible name separately. Do
    not nest this target in another label or add other interactive children.
    """
    return tag(
        "label",
        tw("inline-flex size-9 shrink-0 items-center justify-center cursor-pointer "
           "has-disabled:cursor-not-allowed"),
        {"data-slot": "checkbox-target"},
        checkbox,
    )
