from typing import cast

from pyjs import js
from pyjs.web.dom import Element
from pyjs.web.domx import button, div, p, tw
from pyjs.web.events import CustomEvent, Event
from pyjs.web.timers import setTimeout
from pyjs.web.ui import Widget


@js
class Toaster(Widget):
    def __init__(self, position: str = "bottom-right"):
        super().__init__()
        self.next_id = 0
        self.last_action_toast_id = ""
        self.add(
            tw(
                "fixed z-[100] flex w-full max-w-sm flex-col gap-2 p-4 "
                "data-[position=bottom-right]:bottom-0 data-[position=bottom-right]:right-0 "
                "data-[position=top-right]:right-0 data-[position=top-right]:top-0 "
                "data-[position=bottom-left]:bottom-0 data-[position=bottom-left]:left-0 "
                "data-[position=top-left]:left-0 data-[position=top-left]:top-0"
            ),
            {
                "aria-label": "Notifications",
                "aria-live": "polite",
                "data-position": position,
                "data-slot": "toaster",
                "role": "region",
            },
        )

    def initialize(self):
        self.next_id = self.childElementCount
        self.last_action_toast_id = ""
        self.addEventListener("click", self.clicked)

    def notify(
        self,
        title: str,
        description: str = "",
        variant: str = "default",
        duration: int = 4000,
        action_label: str = "",
    ) -> str:
        self.next_id += 1
        toast_id = "toast-" + str(self.next_id)
        close_button = button(
            tw("absolute right-2 top-2 size-7 rounded-md hover:bg-slate-100"),
            {
                "aria-label": "Dismiss notification",
                "data-toast-close": "",
                "type": "button",
            },
            "×",
        )
        title_el = div(tw("font-semibold"), {"data-slot": "toast-title"}, title)
        description_el = p(
            tw("text-slate-500"), {"data-slot": "toast-description"}, description
        )
        attrs = {
            "data-slot": "toast",
            "data-toast-id": toast_id,
            "data-variant": variant,
            "role": "status",
        }
        classes = tw(
            "relative grid gap-1 rounded-lg border border-slate-200 bg-white p-4 pr-10 "
            "text-sm shadow-lg data-[variant=destructive]:border-red-300 "
            "data-[variant=error]:border-red-300 data-[variant=success]:border-emerald-300 "
            "data-[variant=warning]:border-amber-300 data-[variant=loading]:border-slate-300"
        )
        if action_label != "":
            toast = div(
                classes,
                attrs,
                title_el,
                description_el,
                button(
                    tw(
                        "mt-2 inline-flex h-7 items-center rounded-md border border-slate-300 "
                        "px-2 text-xs font-medium hover:bg-slate-100"
                    ),
                    {
                        "data-toast-action": toast_id,
                        "data-toast-id": toast_id,
                        "type": "button",
                    },
                    action_label,
                ),
                close_button,
            )
        else:
            toast = div(classes, attrs, title_el, description_el, close_button)
        self.append(toast)
        if duration > 0:
            setTimeout(self._expire, duration, toast_id)
        return toast_id

    def success(self, title: str, description: str = "", duration: int = 4000) -> str:
        return self.notify(title, description, "success", duration)

    def error(self, title: str, description: str = "", duration: int = 4000) -> str:
        return self.notify(title, description, "error", duration)

    def warning(self, title: str, description: str = "", duration: int = 4000) -> str:
        return self.notify(title, description, "warning", duration)

    def loading(self, title: str, description: str = "", duration: int = 0) -> str:
        return self.notify(title, description, "loading", duration)

    def dismiss(self, toast_id: str):
        toast = self.querySelector("[data-toast-id='" + toast_id + "']")
        if toast is not None:
            toast.remove()

    def _expire(self, toast_id: str) -> None:
        self.dismiss(toast_id)

    def clicked(self, event: Event):
        target = cast(Element, event.target)
        action_button = target.closest("[data-toast-action]")
        if action_button is not None:
            toast_id = action_button.getAttribute("data-toast-action") or ""
            self.last_action_toast_id = toast_id
            self.dispatchEvent(
                CustomEvent("toast-action", bubbles=True, detail=toast_id)
            )
            if toast_id != "":
                self.dismiss(toast_id)
            return
        close_button = target.closest("[data-toast-close]")
        if close_button is None:
            return
        toast = close_button.closest("[data-slot=toast]")
        if toast is not None:
            toast.remove()
