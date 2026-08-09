from pyjs import js
from pyjs.web.domx import ProxyElement, button, div, p, tag, tw
from pyjs.web.ui.dialog import Dialog, DialogContent, DialogTrigger


@js
class SheetTrigger(DialogTrigger):
    def __init__(self, *children):
        super().__init__(*children)
        self.setAttribute("data-slot", "sheet-trigger")


@js
class SheetClose(ProxyElement):
    def __init__(self, *children):
        self.element = button(
            tw(
                "inline-flex h-9 items-center justify-center rounded-md border border-slate-300 "
                "bg-white px-4 text-sm font-medium text-slate-950 shadow-sm hover:bg-slate-100"
            ),
            {"data-dialog-close": "", "data-slot": "sheet-close", "type": "button"},
            *children,
        )


@js
def SheetHeader(*children):
    return div(
        tw("grid gap-1.5 text-left"),
        {"data-slot": "sheet-header"},
        *children,
    )


@js
def SheetFooter(*children):
    return div(
        tw("mt-auto flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"),
        {"data-slot": "sheet-footer"},
        *children,
    )


@js
def SheetTitle(*children):
    return tag(
        "h2",
        tw("text-lg font-semibold text-slate-950"),
        {"data-slot": "sheet-title"},
        *children,
    )


@js
def SheetDescription(*children):
    return p(
        tw("text-sm leading-6 text-slate-500"),
        {"data-slot": "sheet-description"},
        *children,
    )


@js
class SheetContent(DialogContent):
    def __init__(
        self,
        label: str,
        *children,
        side: str = "right",
        show_close: bool = True,
        close_on_backdrop: bool = True,
    ):
        super().__init__(
            label,
            *children,
            component="sheet",
            placement=side,
            show_close=show_close,
            close_on_backdrop=close_on_backdrop,
        )


@js
class Sheet(Dialog):
    def __init__(self, trigger: SheetTrigger, content: SheetContent):
        super().__init__(trigger, content, component="sheet")
