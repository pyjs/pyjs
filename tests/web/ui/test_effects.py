import pytest

from pyjs.web.ui.button import Button
from pyjs.web.ui.command import CommandDialog, CommandItem
from pyjs.web.ui.field import Field, FieldError, FieldSeparator
from pyjs.web.ui.sonner import Toaster
from pyjs.web.ui.typeset import Typeset

pytestmark = pytest.mark.pyjs_python


def test_typeset_and_field_separator_expose_slots():
    block = Typeset("Hello", preset="chat")
    assert block.getAttribute("data-slot") == "typeset"
    assert block.getAttribute("data-preset") == "chat"
    separator = FieldSeparator("or")
    assert separator.getAttribute("data-slot") == "field-separator"
    error = FieldError(errors=["Required", "Required", "Too short"])
    assert error.getAttribute("role") == "alert"
    assert error.querySelector("ul") is not None
    field = Field("Name", orientation="responsive")
    assert field.getAttribute("data-orientation") == "responsive"


def test_command_dialog_and_keywords_live_on_the_dom():
    item = CommandItem("Source Control", "Source Control", keywords="git scm")
    assert item.getAttribute("data-keywords") == "git scm"
    dialog = CommandDialog(item, title="Run command")
    assert dialog.getAttribute("data-slot") == "command-dialog"
    assert dialog.command.input.getAttribute("placeholder") == "Type a command..."


def test_toaster_typed_helpers_and_action_and_link_button():
    toaster = Toaster(position="top-left")
    assert toaster.getAttribute("data-position") == "top-left"
    toast_id = toaster.notify("Saved", "Done", variant="success", duration=0, action_label="Undo")
    assert toaster.childElementCount == 1
    toast = toaster.children[0]
    assert toast.getAttribute("data-toast-id") == toast_id
    assert toast.getAttribute("data-variant") == "success"
    assert toast.getAttribute("data-slot") == "toast"
    link = Button("Docs", href="/docs", variant="link")
    assert link.element.tagName == "A"
    assert link.getAttribute("href") == "/docs"
