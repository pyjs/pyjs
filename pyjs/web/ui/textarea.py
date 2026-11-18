from typing import cast

from pyjs import js
from pyjs.web.domx import ProxyElement, textarea, tw
from pyjs.web.html import HTMLTextAreaElement


@js
class Textarea(ProxyElement):
    """Native multiline input, optionally sized to its wrapped content.

    ``auto_size`` starts at one touch-friendly row and grows or shrinks with
    content and available width. Older browsers retain native scrolling and
    manual vertical resizing when CSS field sizing is unavailable.
    """

    def __init__(self, placeholder: str = "", name: str = "", *, auto_size: bool = False):
        sizing = tw("min-h-24")
        if auto_size:
            sizing = tw("min-h-11 field-sizing-content resize-y supports-[field-sizing:content]:resize-none")
        style = tw(
            "flex min-w-0 w-full rounded-md border border-slate-300 bg-white px-3 py-2 "
            "text-sm text-slate-950 shadow-sm outline-none placeholder:text-slate-400 "
            "focus:border-slate-500 focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed "
            "disabled:opacity-50 aria-invalid:border-red-500 aria-invalid:ring-red-100"
        )
        style["class"] += " " + sizing["class"]
        self.element = textarea(
            style,
            {"data-slot": "textarea", "name": name, "placeholder": placeholder},
        )
        if auto_size:
            self.element.setAttribute("rows", "1")

    def get_value(self) -> str:
        return cast(HTMLTextAreaElement, self.element).value

    @js
    def set_value(self, value: str):
        # HTML parsing discards one leading newline in a textarea.
        self.element.textContent = "\n" + value
        cast(HTMLTextAreaElement, self.element).value = value

    @set_value.client
    def set_value(self, value: str):
        cast(HTMLTextAreaElement, self.element).value = value

    def set_invalid(self, invalid: bool):
        self.element.setAttribute("aria-invalid", "true" if invalid else "false")

    def on_input(self, callback: callable):
        self.element.addEventListener("input", callback)
