from pyjs import js
from pyjs.web.domx import ProxyElement, button, div, p, tag, tw
from pyjs.web.ui.dialog import Dialog, DialogContent, DialogTrigger


@js
class AlertDialogTrigger(DialogTrigger):
    def __init__(self, *children):
        super().__init__(*children)
        self.setAttribute("data-slot", "alert-dialog-trigger")


@js
class AlertDialogAction(ProxyElement):
    def __init__(self, *children):
        self.element = button(
            tw(
                "inline-flex h-9 items-center justify-center rounded-md bg-slate-950 px-4 "
                "text-sm font-medium text-white shadow-sm hover:bg-slate-800 "
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
            ),
            {
                "data-dialog-close": "",
                "data-slot": "alert-dialog-action",
                "type": "button",
            },
            *children,
        )


@js
class AlertDialogCancel(ProxyElement):
    def __init__(self, *children):
        self.element = button(
            tw(
                "inline-flex h-9 items-center justify-center rounded-md border border-slate-300 "
                "bg-white px-4 text-sm font-medium text-slate-950 shadow-sm hover:bg-slate-100 "
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
            ),
            {
                "data-dialog-close": "",
                "data-slot": "alert-dialog-cancel",
                "type": "button",
            },
            *children,
        )


@js
def AlertDialogHeader(*children):
    return div(
        tw("flex flex-col gap-2 text-center sm:text-left"),
        {"data-slot": "alert-dialog-header"},
        *children,
    )


@js
def AlertDialogFooter(*children):
    return div(
        tw("flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"),
        {"data-slot": "alert-dialog-footer"},
        *children,
    )


@js
def AlertDialogTitle(*children):
    return tag(
        "h2",
        tw("text-lg font-semibold leading-none text-slate-950"),
        {"data-slot": "alert-dialog-title"},
        *children,
    )


@js
def AlertDialogDescription(*children):
    return p(
        tw("text-sm leading-6 text-slate-500"),
        {"data-slot": "alert-dialog-description"},
        *children,
    )


@js
class AlertDialogContent(DialogContent):
    def __init__(self, label: str, *children):
        super().__init__(
            label,
            *children,
            component="alert-dialog",
            role="alertdialog",
            show_close=False,
            close_on_backdrop=False,
        )


@js
class AlertDialog(Dialog):
    def __init__(self, trigger: AlertDialogTrigger, content: AlertDialogContent):
        super().__init__(trigger, content, component="alert-dialog")
