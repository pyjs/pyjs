import pytest

from pyjs import js
from pyjs.web.domx import div, p
from pyjs.web.events import Event
from pyjs.web.ui.command import Command, CommandDialog, CommandGroup, CommandItem
from pyjs.web.ui.effects import sync_scroll_fade
from pyjs.web.ui.scroll_area import ScrollArea
from pyjs.web.ui.sonner import Toaster
from pyjs.web.ui.typeset import Typeset
from tests.web.ui.browser import bubbling_click, mount, require_element

pytestmark = pytest.mark.pyjs_web


@js
def test_scroll_fade_tracks_overflow_edges():
    scroller = ScrollArea(
        div({"style": "height:400px"}, "Long"),
        height="80px",
    )
    mount(scroller)
    assert scroller.getAttribute("data-scroll-fade") == "y"
    sync_scroll_fade(scroller, 40)
    start = scroller.style.getPropertyValue("--scroll-fade-start")
    end = scroller.style.getPropertyValue("--scroll-fade-end")
    assert start == "0px" or start == "40px"
    assert end == "0px" or end == "40px"


@js
def test_typeset_chat_preset_and_shimmer_marker():
    article = Typeset(p("Hello"), p("There"), preset="chat")
    shimmer = p({"data-shimmer": ""}, "Thinking")
    mount(article, shimmer)
    assert article.getAttribute("data-preset") == "chat"
    assert article.getAttribute("data-slot") == "typeset"
    assert shimmer.getAttribute("data-shimmer") == ""


@js
def test_command_skips_disabled_items_and_matches_keywords():
    open_item = CommandItem("Open file", "Open file")
    hidden = CommandItem("Hidden", "Hidden", disabled=True)
    scm = CommandItem("Source Control", "Source Control", keywords="git scm")
    command = Command(open_item, hidden, scm)
    mount(command)

    visible = command.visible_items()
    assert len(visible) == 2
    command.highlight(0)
    command.highlight(1)
    assert command.highlighted_item() is scm.element

    command.input.value = "scm"
    command.input.dispatchEvent(Event("input"))
    assert scm.getAttribute("hidden") is None
    assert open_item.getAttribute("hidden") == ""


@js
def test_command_hides_empty_groups():
    files_item = CommandItem("Open file", "Open file")
    other_item = CommandItem("Zap", "Zap")
    command = Command()
    command.list.append(CommandGroup("Files", files_item))
    command.list.append(CommandGroup("Other", other_item))
    mount(command)
    command.input.value = "open"
    command.input.dispatchEvent(Event("input"))
    files = command.querySelector("[data-slot=command-group][aria-label='Files']")
    other = command.querySelector("[data-slot=command-group][aria-label='Other']")
    if files is None or other is None:
        raise RuntimeError("expected command groups")
    assert files.getAttribute("hidden") is None
    assert other.getAttribute("hidden") == ""


@js
def test_toaster_action_and_manual_dismiss():
    toaster = Toaster()
    mount(toaster)
    toast_id = toaster.notify("Saved", "Keep going", duration=0, action_label="Undo")
    toast = require_element(toaster, "[data-slot=toast]")
    assert toast.getAttribute("data-toast-id") == toast_id
    bubbling_click(require_element(toaster, "[data-toast-close]"))
    assert toaster.querySelector("[data-slot=toast]") is None


@js
def test_command_dialog_opens_a_modal_command():
    dialog = CommandDialog(CommandItem("Save", "Save"), title="Run command")
    mount(dialog)
    dialog.open()
    assert dialog.panel.dialog_element.open
    dialog.close()
    assert not dialog.panel.dialog_element.open
