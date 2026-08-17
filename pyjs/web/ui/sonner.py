from typing import cast

from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.domx import button, div, p, tw
from pyjs.web.events import Event
from pyjs.web.ui import Widget


@js
class Toaster(Widget):
    def __init__(self, position: str = "bottom-right"):
        super().__init__()
        self.next_id = 0
        self.add(
            tw(
                "fixed z-[100] flex w-full max-w-sm flex-col gap-2 p-4 "
                "data-[position=bottom-right]:bottom-0 data-[position=bottom-right]:right-0 "
                "data-[position=top-right]:right-0 data-[position=top-right]:top-0"
            ),
            {
                "aria-label": "Notifications",
                "aria-live": "polite",
                "data-position": position,
                "data-slot": "toaster",
                "role": "region",
            },
        )
        self.addEventListener("click", self.clicked)

    def notify(self, title: str, description: str = "", variant: str = "default") -> str:
        self.next_id += 1
        toast_id = "toast-" + str(self.next_id)
        toast = div(
            tw(
                "relative grid gap-1 rounded-lg border border-slate-200 bg-white p-4 pr-10 "
                "text-sm shadow-lg data-[variant=destructive]:border-red-300"
            ),
            {
                "data-slot": "toast",
                "data-toast-id": toast_id,
                "data-variant": variant,
                "role": "status",
            },
            div(tw("font-semibold"), {"data-slot": "toast-title"}, title),
            p(tw("text-slate-500"), {"data-slot": "toast-description"}, description),
            button(
                tw("absolute right-2 top-2 size-7 rounded-md hover:bg-slate-100"),
                {
                    "aria-label": "Dismiss notification",
                    "data-toast-close": "",
                    "type": "button",
                },
                "×",
            ),
        )
        self.append(toast)
        return toast_id

    def dismiss(self, toast_id: str):
        toast = self.querySelector("[data-toast-id='" + toast_id + "']")
        if toast is not None:
            toast.remove()

    def clicked(self, event: Event):
        target = cast(Element, event.target)
        close_button = target.closest("[data-toast-close]")
        if close_button is None:
            return
        toast = close_button.closest("[data-slot=toast]")
        if toast is not None:
            toast.remove()
