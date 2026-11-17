from typing import cast

import pytest

from pyjs import js
from pyjs.testing.web import mount
from pyjs.web.clipboard import ClipboardEvent
from pyjs.web.domx import div, textarea
from pyjs.web.dragdrop import DataTransfer
from pyjs.web.events import CustomEvent
from pyjs.web.files import File
from pyjs.web.ui.file_paste import FilePasteController, PastedFiles

pytestmark = pytest.mark.pyjs_web


@js
class Receiver:
    def __init__(self, name: str, owners: list[str]):
        self.name = name
        self.owners = owners
        self.files: list[File] = []
        self.types: list[str] = []
        self.prefer_text = False
        self.prefer_html = False
        self.listener: callable = self.accept

    def accept(self, event: CustomEvent):
        pasted = cast(PastedFiles, event.detail)
        self.types = pasted.types
        if ((self.prefer_text and pasted.has_plain_text)
                or (self.prefer_html and pasted.has_html)):
            return
        self.owners.append(self.name)
        self.files.extend(pasted.files)
        event.preventDefault()


@js
def clipboard(files: list[File], text: str = "") -> ClipboardEvent:
    data = DataTransfer()
    if text:
        data.setData("text/plain", text)
    for file in files:
        data.items.add(file)
    return ClipboardEvent("paste", bubbles=True, cancelable=True, clipboardData=data)


@js
async def test_file_paste_retains_files_but_leaves_text_and_unaccepted_files_alone():
    host = div(textarea())
    mount(host)
    controller = FilePasteController(host)
    controller.connect()
    file = File(["image bytes"], "image.png", type="image/png")
    declined = clipboard([file], "caption")
    assert host.dispatchEvent(declined)
    receiver = Receiver("host", [])
    received = receiver.files
    host.addEventListener("files-paste", receiver.listener)
    text = clipboard([], "ordinary text")
    assert host.dispatchEvent(text)
    assert host.dispatchEvent(ClipboardEvent("paste", cancelable=True))
    assert not received
    paste = clipboard([file, File(["second"], "second.txt")], "caption")
    assert not host.dispatchEvent(paste)
    assert len(received) == 2
    assert received[0].name == "image.png"
    assert received[0].type == "image/png"
    assert received[0].size == 11
    assert received[1].name == "second.txt"
    data = paste.clipboardData
    assert data is not None
    assert cast(DataTransfer, data).getData("text/plain") == "caption"
    cast(DataTransfer, data).items.clear()
    assert "text/plain" in receiver.types and "Files" in receiver.types
    assert await received[0].text() == "image bytes"
    assert await received[1].text() == "second"
    controller.disconnect()


@js
def test_file_paste_consumer_can_choose_plain_text_or_rich_html_policy():
    host = textarea()
    mount(host)
    controller = FilePasteController(host)
    controller.connect()
    receiver = Receiver("editor", [])
    receiver.prefer_text = True
    host.addEventListener("files-paste", receiver.listener)
    file = File(["preview"], "selection.png", type="image/png")
    assert host.dispatchEvent(clipboard([file], "spreadsheet cells"))
    data = DataTransfer()
    data.items.add(file)
    data.setData("text/html", '<img src="about:blank">')
    assert not host.dispatchEvent(ClipboardEvent("paste", cancelable=True, clipboardData=data))
    assert len(receiver.files) == 1
    receiver.files.clear()
    receiver.prefer_html = True
    assert host.dispatchEvent(ClipboardEvent("paste", cancelable=True, clipboardData=data))
    assert not receiver.files
    data.clearData()
    assert not host.dispatchEvent(ClipboardEvent("paste", cancelable=True, clipboardData=data))
    assert len(receiver.files) == 1
    controller.disconnect()


@js
def test_file_paste_nested_ownership_and_reconnection():
    inner = div(textarea())
    outer = div(inner)
    mount(outer)
    first = FilePasteController(inner)
    second = FilePasteController(outer)
    first.connect()
    first.connect()
    second.connect()
    owners: list[str] = []

    inner_receiver = Receiver("inner", owners)
    outer_receiver = Receiver("outer", owners)
    inner.addEventListener("files-paste", inner_receiver.listener)
    outer.addEventListener("files-paste", outer_receiver.listener)
    file = File(["bytes"], "file.txt")
    inner.dispatchEvent(clipboard([file]))
    assert owners == ["inner"]
    first.disconnect()
    first.disconnect()
    inner.dispatchEvent(clipboard([file]))
    assert owners == ["inner", "outer"]
    first.connect()
    inner.dispatchEvent(clipboard([file]))
    assert owners == ["inner", "outer", "inner"]
    prevented = clipboard([file])
    prevented.preventDefault()
    inner.dispatchEvent(prevented)
    inner.dispatchEvent(ClipboardEvent("paste", clipboardData=prevented.clipboardData))
    assert len(owners) == 3
    inner.removeEventListener("files-paste", inner_receiver.listener)
    inner.dispatchEvent(clipboard([file]))
    assert owners == ["inner", "outer", "inner", "outer"]
    first.disconnect()
    second.disconnect()
