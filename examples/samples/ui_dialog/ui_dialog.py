from pyjs import js
from pyjs.web.domx import CustomElement, ref, tag, tw
from pyjs.web.ui.dialog import (
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
)


@js
class DialogSample(CustomElement):
    def __init__(self):
        super().__init__()
        self.close_button = ref(DialogClose("Close"))
        self.dialog = ref(
            Dialog(
                DialogTrigger("Open dialog"),
                DialogContent(
                    "Welcome to PyJS",
                    DialogHeader(
                        DialogTitle("Welcome to PyJS"),
                        DialogDescription(
                            "This accessible modal is implemented with native browser APIs."
                        ),
                    ),
                    DialogFooter(self.close_button),
                ),
            )
        )
        tag(
            self,
            tag(
                "main",
                tw("grid min-h-screen place-items-center bg-slate-50 font-sans text-slate-950"),
                tag(
                    "section",
                    tw(
                        "w-full max-w-md rounded-xl border border-slate-200 "
                        "bg-white p-8 text-center shadow-lg"
                    ),
                    tag("h1", tw("mb-2 text-2xl font-semibold"), "Native dialog"),
                    tag(
                        "p",
                        tw("mb-6 text-sm leading-6 text-slate-500"),
                        "Open the dialog to see focus management and accessible modal behavior.",
                    ),
                    self.dialog,
                ),
            ),
        )


def main():
    return DialogSample()


if __name__ == "__main__":
    from pyjs.server import serve

    serve("ui_dialog")
