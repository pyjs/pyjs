from pyjs import js
from pyjs.web.domx import ProxyElement, textarea, tw


@js
class Textarea(ProxyElement):
    def __init__(self, placeholder: str = "", name: str = ""):
        self.element = textarea(
            tw(
                "flex min-h-24 w-full rounded-md border border-slate-300 bg-white px-3 py-2 "
                "text-sm text-slate-950 shadow-sm outline-none placeholder:text-slate-400 "
                "focus:border-slate-500 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed "
                "disabled:opacity-50 aria-invalid:border-red-500 aria-invalid:ring-red-100"
            ),
            {"data-slot": "textarea", "name": name, "placeholder": placeholder},
        )

    def get_value(self) -> str:
        return self.element.value

    def set_value(self, value: str):
        self.element.value = value

    def set_invalid(self, invalid: bool):
        self.element.setAttribute("aria-invalid", "true" if invalid else "false")

    def on_input(self, callback: callable):
        self.element.addEventListener("input", callback)
