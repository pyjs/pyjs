from typing import cast

from pyjs import js
from pyjs.web.dom import Element, document
from pyjs.web.domx import ProxyElement, button, div, p, ref, tag, tw
from pyjs.web.domx import dialog as dialog_element
from pyjs.web.events import CustomEvent, Event
from pyjs.web.ui import Widget


@js
class DialogCloseRequest(CustomEvent):
    event_name = "dialog-close-request"

    def __init__(self):
        super().__init__(DialogCloseRequest.event_name, bubbles=True, cancelable=True)


@js
class DialogTrigger(ProxyElement):
    def __init__(self, *children):
        self.element = button(
            tw(
                "inline-flex h-9 items-center justify-center rounded-md border border-slate-300 "
                "bg-white px-4 text-sm font-medium text-slate-950 shadow-sm transition-colors "
                "hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 "
                "focus-visible:ring-slate-400 disabled:pointer-events-none disabled:opacity-50"
            ),
            {
                "aria-expanded": "false",
                "aria-haspopup": "dialog",
                "data-slot": "dialog-trigger",
                "type": "button",
            },
            *children,
        )

    def on_click(self, callback: callable):
        self.element.addEventListener("click", callback)

    def set_expanded(self, expanded: bool):
        self.element.setAttribute("aria-expanded", "true" if expanded else "false")
        self.element.setAttribute("data-state", "open" if expanded else "closed")


@js
class DialogClose(ProxyElement):
    def __init__(self, *children):
        self.element = button(
            tw(
                "inline-flex h-9 items-center justify-center rounded-md border border-slate-300 "
                "bg-white px-4 text-sm font-medium text-slate-950 shadow-sm transition-colors "
                "hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 "
                "focus-visible:ring-slate-400"
            ),
            {"data-dialog-close": "", "data-slot": "dialog-close", "type": "button"},
            *children,
        )


@js
def DialogHeader(*children):
    return div(
        tw("flex flex-col gap-2 text-center sm:text-left"),
        {"data-slot": "dialog-header"},
        *children,
    )


@js
def DialogFooter(*children):
    return div(
        tw("flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"),
        {"data-slot": "dialog-footer"},
        *children,
    )


@js
def DialogTitle(*children):
    return tag(
        "h2",
        tw("text-lg font-semibold leading-none text-slate-950"),
        {"data-slot": "dialog-title"},
        *children,
    )


@js
def DialogDescription(*children):
    return p(
        tw("text-sm leading-6 text-slate-500"),
        {"data-slot": "dialog-description"},
        *children,
    )


@js
class DialogContent(Widget):
    def __init__(
        self,
        label: str,
        *children,
        component: str = "dialog",
        placement: str = "center",
        role: str = "dialog",
        show_close: bool = True,
        close_on_backdrop: bool = True,
    ):
        super().__init__()
        if (
            placement != "center"
            and placement != "top"
            and placement != "right"
            and placement != "bottom"
            and placement != "left"
        ):
            raise ValueError(
                "DialogContent placement must be center, top, right, bottom, or left"
            )
        close_button = button(
            tw(
                "absolute right-4 top-4 inline-flex size-8 items-center justify-center "
                "rounded-sm text-2xl font-light leading-none text-slate-500 opacity-70 "
                "transition-opacity hover:opacity-100 focus-visible:outline-none "
                "focus-visible:ring-2 focus-visible:ring-slate-400"
            ),
            {
                "aria-label": "Close",
                "data-dialog-close": "",
                "data-slot": component + "-close",
                "type": "button",
            },
            "×",
        )
        content_style = tw(
            "fixed left-1/2 top-1/2 z-50 m-0 w-full max-w-[calc(100%-2rem)] "
            "-translate-x-1/2 -translate-y-1/2 overflow-visible rounded-lg border "
            "border-slate-200 bg-white p-0 text-slate-950 shadow-xl backdrop:bg-black/50 "
            "sm:max-w-lg"
        )
        if placement == "right":
            content_style = tw(
                "fixed inset-y-0 right-0 left-auto top-0 z-50 m-0 h-full max-h-none w-3/4 "
                "max-w-sm overflow-visible border-l border-slate-200 bg-white p-0 text-slate-950 "
                "shadow-xl backdrop:bg-black/50"
            )
        elif placement == "left":
            content_style = tw(
                "fixed inset-y-0 left-0 right-auto top-0 z-50 m-0 h-full max-h-none w-3/4 "
                "max-w-sm overflow-visible border-r border-slate-200 bg-white p-0 text-slate-950 "
                "shadow-xl backdrop:bg-black/50"
            )
        elif placement == "top":
            content_style = tw(
                "fixed inset-x-0 top-0 z-50 m-0 w-full max-w-none overflow-visible border-b "
                "border-slate-200 bg-white p-0 text-slate-950 shadow-xl backdrop:bg-black/50"
            )
        elif placement == "bottom":
            content_style = tw(
                "fixed inset-x-0 bottom-0 top-auto z-50 m-0 w-full max-w-none overflow-visible "
                "border-t border-slate-200 bg-white p-0 text-slate-950 shadow-xl "
                "backdrop:bg-black/50"
            )
        surface = div(
            tw(
                "relative grid gap-4 p-6 "
                "data-[placement=left]:h-full data-[placement=right]:h-full"
            ),
            {"data-placement": placement},
            *children,
        )
        if show_close:
            surface.append(close_button)
        self.surface = ref(surface)
        self.dialog_element = ref(
            dialog_element(
                content_style,
                {
                    "aria-label": label,
                    "data-close-on-backdrop": "true" if close_on_backdrop else "false",
                    "data-side": placement,
                    "data-slot": component + "-content",
                    "data-state": "closed",
                    "role": role,
                },
                self.surface,
            )
        )
        self.dialog_element.addEventListener("cancel", self.cancel)
        self.dialog_element.addEventListener("click", self.dialog_clicked)
        self.add(
            tw("contents"), {"data-slot": component + "-portal"}, self.dialog_element
        )

    def show_modal(self):
        self.dialog_element.setAttribute("data-state", "open")
        self.dialog_element.showModal()

    def close(self):
        if self.dialog_element.open:
            self.dialog_element.close()
        self.dialog_element.setAttribute("data-state", "closed")

    def request_close(self, event: Event):
        self.dispatchEvent(DialogCloseRequest())

    def cancel(self, event: Event):
        event.preventDefault()
        self.request_close(event)

    def dialog_clicked(self, event: Event):
        target = cast(Element, event.target)
        close_control = target.closest("[data-dialog-close]")
        close_on_backdrop = (
            self.dialog_element.getAttribute("data-close-on-backdrop") == "true"
        )
        if (
            close_control is not None
            or event.target is self.dialog_element
            and close_on_backdrop
        ):
            self.request_close(event)


@js
class Dialog(Widget):
    def __init__(
        self,
        trigger: DialogTrigger,
        content: DialogContent,
        *,
        component: str = "dialog",
    ):
        super().__init__()
        self.trigger = ref(trigger)
        self.content = ref(content)
        self.is_open = False
        self.previous_body_overflow = ""

        self.trigger.on_click(self.toggle)
        self.content.addEventListener(DialogCloseRequest.event_name, self.close_requested)
        self.content.dialog_element.addEventListener("close", self.native_closed)
        self.add(
            tw("inline-block"),
            {"data-slot": component, "data-state": "closed"},
            self.trigger,
            self.content,
        )

    def open(self):
        if self.is_open:
            return
        self.is_open = True
        self.previous_body_overflow = document.body.style.overflow
        document.body.style.overflow = "hidden"
        self.setAttribute("data-state", "open")
        self.trigger.set_expanded(True)
        self.content.show_modal()

    def close(self):
        if not self.is_open:
            return
        self.content.close()
        self.finish_close()

    def toggle(self, event: Event):
        if self.is_open:
            self.close()
        else:
            self.open()

    def close_requested(self, event: DialogCloseRequest):
        event.preventDefault()
        self.close()

    def native_closed(self, event: Event):
        self.content.dialog_element.setAttribute("data-state", "closed")
        self.finish_close()

    def finish_close(self):
        if not self.is_open:
            return
        self.is_open = False
        document.body.style.overflow = self.previous_body_overflow
        self.setAttribute("data-state", "closed")
        self.trigger.set_expanded(False)
        self.trigger.element.focus()

    @js.keep
    def disconnectedCallback(self):
        if self.is_open:
            self.close()
