from pyjs import js
from pyjs.web.domx import ProxyElement, input, tw


@js
class Switch(ProxyElement):
    def __init__(self, name: str = "", checked: bool = False):
        self.element = input(
            tw(
                "relative inline-flex h-5 w-9 shrink-0 cursor-pointer appearance-none "
                "items-center rounded-full bg-slate-200 transition-colors before:block "
                "before:size-4 before:translate-x-0.5 before:rounded-full before:bg-white "
                "before:shadow-sm before:transition-transform checked:bg-slate-950 "
                "checked:before:translate-x-[1.125rem] focus-visible:outline-none "
                "focus-visible:ring-2 focus-visible:ring-slate-400 disabled:opacity-50"
            ),
            {
                "data-slot": "switch",
                "name": name,
                "role": "switch",
                "type": "checkbox",
            },
        )
        self.element.checked = checked
        if checked:
            self.element.setAttribute("checked", "")

    def is_checked(self) -> bool:
        return self.element.checked

    def set_checked(self, checked: bool):
        self.element.checked = checked

    def on_change(self, callback: callable):
        self.element.addEventListener("change", callback)
