from pyjs import js
from pyjs.web.clipboard import ClipboardEvent
from pyjs.web.dom import Element
from pyjs.web.events import CustomEvent
from pyjs.web.files import File


@js
class FilePasteController:
    """Offer clipboard files to an existing element without changing its layout.

    Call connect/disconnect with the host's client lifecycle. Listen on the host
    for the non-bubbling ``files-paste`` event; its detail is a list of Files.
    Accept synchronously with preventDefault(), before awaiting any upload.
    Unaccepted files and ordinary text retain their native paste behavior.
    Validation, pending-file ownership and persistence belong to the consumer.
    """

    def __init__(self, host: Element):
        self.host = host
        self.listener: callable = self.paste

    def connect(self):
        self.host.addEventListener("paste", self.listener)

    def disconnect(self):
        self.host.removeEventListener("paste", self.listener)

    def paste(self, event: ClipboardEvent):
        data = event.clipboardData
        if event.defaultPrevented or not event.cancelable or data is None:
            return
        files: list[File] = []
        for index in range(data.files.length):
            file = data.files.item(index)
            if file is not None:
                files.append(file)
        if not files:
            return
        # Clipboard data is only readable during the native event dispatch.
        offer = CustomEvent("files-paste", cancelable=True, detail=files)
        if not self.host.dispatchEvent(offer):
            event.preventDefault()
            event.stopPropagation()
