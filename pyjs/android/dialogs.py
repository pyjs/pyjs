"""Native confirmation dialogs."""

from pyjs import jvm
from pyjs.android import CharSequence, Context
from pyjs.java import i32


@jvm.native("android/content/DialogInterface", interface=True)
class DialogInterface:
    def dismiss(self) -> None: ...


@jvm.native("android/content/DialogInterface$OnClickListener", interface=True)
class DialogClickListener:
    def onClick(self, dialog: DialogInterface, which: i32) -> None: ...


@jvm.native("android/app/AlertDialog")
class AlertDialog:
    def dismiss(self) -> None: ...


@jvm.native("android/app/AlertDialog$Builder")
class AlertDialogBuilder:
    def __init__(self, context: Context) -> None: ...

    def setTitle(self, title: CharSequence) -> AlertDialogBuilder: ...

    def setMessage(self, message: CharSequence) -> AlertDialogBuilder: ...

    def setPositiveButton(
        self, text: CharSequence, listener: DialogClickListener | None,
    ) -> AlertDialogBuilder: ...

    def setNegativeButton(
        self, text: CharSequence, listener: DialogClickListener | None,
    ) -> AlertDialogBuilder: ...

    def show(self) -> AlertDialog: ...
