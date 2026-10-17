from pyjs import js
from pyjs.web.domx import ProxyElement, button, div, p, tag, tw
from pyjs.web.ui.dialog import Dialog, DialogContent, DialogTrigger


@js
class DrawerTrigger(DialogTrigger):
    def __init__(self, *children):
        super().__init__(*children)
        self.setAttribute("data-slot", "drawer-trigger")


@js
class DrawerClose(ProxyElement):
    def __init__(self, *children):
        self.element = button(
            tw(
                "inline-flex h-9 items-center justify-center rounded-md border px-4 text-sm"
            ),
            {"data-dialog-close": "", "data-slot": "drawer-close", "type": "button"},
            *children,
        )


@js
def DrawerHeader(*children):
    return div(
        tw("grid gap-1.5 text-center sm:text-left"),
        {"data-slot": "drawer-header"},
        *children,
    )


@js
def DrawerFooter(*children):
    return div(
        tw("mt-auto flex flex-col gap-2"), {"data-slot": "drawer-footer"}, *children
    )


@js
def DrawerTitle(*children):
    return tag(
        "h2", tw("text-lg font-semibold"), {"data-slot": "drawer-title"}, *children
    )


@js
def DrawerDescription(*children):
    return p(tw("text-sm text-slate-500"), {"data-slot": "drawer-description"}, *children)


@js
class DrawerContent(DialogContent):
    def __init__(self, label: str, *children, placement: str = "bottom"):
        handle = div(
            tw("mx-auto mt-3 h-1.5 w-12 rounded-full bg-slate-300"),
            {"aria-hidden": "true", "data-slot": "drawer-handle"},
        )
        if placement != "bottom":
            handle = div()
        super().__init__(
            label,
            handle,
            *children,
            component="drawer",
            placement=placement,
        )


@js
class Drawer(Dialog):
    def __init__(self, trigger: DrawerTrigger, content: DrawerContent):
        super().__init__(trigger, content, component="drawer")
