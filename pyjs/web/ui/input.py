from typing import cast

from pyjs import js
from pyjs.web.domx import ProxyElement, input, tw
from pyjs.web.html import HTMLInputElement


@js
class Input(ProxyElement):
    def __init__(
        self,
        input_type: str = "text",
        placeholder: str = "",
        name: str = "",
    ):
        self.element = input(
            tw(
                "flex h-9 w-full min-w-0 rounded-md border border-slate-300 bg-white px-3 "
                "py-1 text-sm text-slate-950 shadow-sm outline-none transition-colors "
                "placeholder:text-slate-400 focus:border-slate-500 focus:ring-2 "
                "focus:ring-slate-200 disabled:pointer-events-none disabled:cursor-not-allowed "
                "disabled:opacity-50 aria-invalid:border-red-500 aria-invalid:ring-red-100 "
                "dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 "
                "dark:placeholder:text-slate-500 dark:focus:border-slate-500 "
                "dark:focus:ring-slate-800 dark:aria-invalid:ring-red-950"
            ),
            {
                "data-slot": "input",
                "name": name,
                "placeholder": placeholder,
                "type": input_type,
            },
        )

    def get_value(self) -> str:
        return cast(HTMLInputElement, self.element).value

    def set_value(self, value: str):
        cast(HTMLInputElement, self.element).value = value

    def set_invalid(self, invalid: bool):
        self.element.setAttribute("aria-invalid", "true" if invalid else "false")

    def on_input(self, callback: callable):
        self.element.addEventListener("input", callback)

    def on_change(self, callback: callable):
        self.element.addEventListener("change", callback)

    def on_blur(self, callback: callable):
        self.element.addEventListener("blur", callback)
