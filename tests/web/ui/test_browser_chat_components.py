from typing import cast

import pytest

from pyjs import js
from pyjs.web.dom import document
from pyjs.web.domx import div, input, ref
from pyjs.web.events import Event, KeyboardEvent
from pyjs.web.html import HTMLInputElement
from pyjs.web.ui import Widget
from pyjs.web.ui.message_scroller import MessageScroller, MessageScrollerItem
from pyjs.web.ui.questionnaire import (
    Questionnaire,
    QuestionnaireChoice,
    QuestionnaireChoices,
    QuestionnaireError,
    QuestionnaireInput,
    QuestionnaireItem,
    QuestionnaireTitle,
)
from pyjs.web.ui.streaming_list import StreamingList
from tests.web.ui.browser import bubbling_click, mount

pytestmark = pytest.mark.pyjs_web


@js
def test_questionnaire_validates_required_answers_and_navigates_items():
    first = QuestionnaireItem(
        "goal",
        QuestionnaireTitle("Choose a goal"),
        QuestionnaireChoices(
            QuestionnaireChoice("learn", "Learn PyJS", shortcut="A"),
            QuestionnaireChoice("ship", "Ship an app"),
        ),
        QuestionnaireError("Choose a goal."),
        required=True,
    )
    second = QuestionnaireItem(
        "detail",
        QuestionnaireTitle("Add details"),
        QuestionnaireInput("Optional"),
    )
    survey = Questionnaire(first, second)
    mount(survey)

    submit = Event("submit", bubbles=True, cancelable=True)
    survey.form.dispatchEvent(submit)
    assert submit.defaultPrevented

    bubbling_click(survey.next)
    assert survey.current_index() == 0
    assert first.fieldset.getAttribute("aria-invalid") == "true"
    assert not first.find_slots("questionnaire-error")[0].hasAttribute("hidden")

    first_choice = cast(
        HTMLInputElement,
        first.find_slots("questionnaire-choice-input")[0],
    )
    survey.form.dispatchEvent(KeyboardEvent("keydown", key="a", bubbles=True))
    assert first_choice.checked
    bubbling_click(survey.next)

    assert survey.current_index() == 1
    assert survey.progress.textContent == "Question 2 of 2"
    assert first.hasAttribute("hidden")
    assert not second.hasAttribute("hidden")
    assert not survey.submit.hasAttribute("hidden")
    assert document.activeElement is second.fieldset

    valid_submit = Event("submit", bubbles=True, cancelable=True)
    survey.form.dispatchEvent(valid_submit)
    assert valid_submit.defaultPrevented

    bubbling_click(survey.previous)
    assert survey.current_index() == 0
    assert first_choice.checked
    assert document.activeElement is first.fieldset


@js
def test_message_scroller_follows_latest_and_reveals_jump_control():
    scroller = MessageScroller(
        MessageScrollerItem(div("First")),
        MessageScrollerItem(div("Second")),
    )
    scroller.setAttribute("style", "height: 80px")
    scroller.viewport.setAttribute("style", "height: 80px; max-height: 80px")
    scroller.content.setAttribute("style", "height: 400px; min-height: 400px")
    mount(scroller)

    assert scroller.viewport.scrollHeight > scroller.viewport.clientHeight
    assert scroller.is_at_latest()
    assert scroller.scroll_button.getAttribute("data-active") == "false"

    scroller.viewport.scrollTop = 0
    scroller.update_scroll_button()
    assert not scroller.is_at_latest()
    assert scroller.scroll_button.getAttribute("data-active") == "true"
    assert scroller.scroll_button.getAttribute("tabindex") is None

    bubbling_click(scroller.scroll_button)
    assert scroller.is_at_latest()
    assert scroller.scroll_button.getAttribute("data-active") == "false"
    assert scroller.scroll_button.getAttribute("tabindex") == "-1"


@js
def test_streaming_list_pauses_bounds_and_preserves_manual_scroll():
    first = div({"style": "height: 60px"}, "First")
    second = div({"style": "height: 60px"}, "Second")
    stream = StreamingList(first, second, max_items=3)
    stream.setAttribute("style", "height: 100px")
    stream.scroller.viewport.setAttribute(
        "style",
        "height: 70px; max-height: 70px",
    )
    mount(stream)

    stream.scroller.scroll_to_latest()
    stream.append_live(div({"style": "height: 60px"}, "Third"))
    assert stream.scroller.is_at_latest()

    stream.scroller.viewport.scrollTop = 0
    stream.append_live(div({"style": "height: 60px"}, "Fourth"))
    assert stream.scroller.viewport.scrollTop == 0
    assert len(stream.scroller.item_elements()) == 3

    bubbling_click(stream.pause_button)
    stream.append_live(div({"style": "height: 60px"}, "Fifth"))
    assert len(stream.scroller.item_elements()) == 3
    assert stream.status.textContent == "1 waiting"

    bubbling_click(stream.pause_button)
    assert len(stream.scroller.item_elements()) == 3
    items = stream.scroller.item_elements()
    assert items[len(items) - 1].textContent == "Fifth"


@js
def test_streaming_list_compensates_when_trimming_above_the_viewport():
    rows = [div({"style": "height: 20px; flex: none"}, "Row 0")]
    for index in range(1, 120):
        rows.append(
            div(
                {"style": "height: 20px; flex: none"},
                "Row " + str(index),
            )
        )
    stream = StreamingList(*rows, max_items=120)
    stream.setAttribute("style", "height: 100px")
    stream.scroller.viewport.setAttribute(
        "style",
        "height: 100px; max-height: 100px",
    )
    stream.scroller.content.setAttribute(
        "style",
        "gap: 0; min-height: 0; padding: 0",
    )
    mount(stream)

    stream.scroller.viewport.scrollTop = 1200
    anchor = rows[60]
    previous_top = anchor.getBoundingClientRect().top
    incoming = [div({"style": "height: 20px; flex: none"}, "Row 120")]
    for index in range(121, 160):
        incoming.append(
            div(
                {"style": "height: 20px; flex: none"},
                "Row " + str(index),
            )
        )
    stream.append_live(*incoming)

    assert rows[0].parentElement is None
    assert rows[39].parentElement is None
    assert rows[40].parentElement is stream.scroller.content
    assert anchor.getBoundingClientRect().top == previous_top
    assert stream.scroller.viewport.scrollTop == 400


@js
class FocusRow(Widget):
    def __init__(self, name: str):
        super().__init__()
        self.field = ref(
            input(
                {
                    "data-slot": "focus-row-input",
                    "value": name,
                }
            )
        )
        self.add({"data-row": name, "data-slot": "focus-row"}, self.field)


@js
def test_streaming_list_keeps_focus_on_a_retained_custom_element_row():
    row = FocusRow("keep")
    stream = StreamingList(row, div("two"), max_items=5)
    mount(stream)
    row.field.focus()
    stream.append_live(div("three"))
    assert document.activeElement is row.field
    assert row.parentElement is stream.scroller.content


@js
def test_streaming_list_preserves_read_position_across_flex_gap():
    rows = [
        div({"style": "height:40px;flex:none;margin:0;padding:0"}, "R0"),
        div({"style": "height:40px;flex:none;margin:0;padding:0"}, "R1"),
        div({"style": "height:40px;flex:none;margin:0;padding:0"}, "R2"),
        div({"style": "height:40px;flex:none;margin:0;padding:0"}, "R3"),
        div({"style": "height:40px;flex:none;margin:0;padding:0"}, "R4"),
    ]
    stream = StreamingList(*rows, max_items=5)
    stream.setAttribute("style", "height:80px")
    stream.scroller.setAttribute("style", "height:80px")
    stream.scroller.viewport.setAttribute("style", "height:80px;max-height:80px")
    stream.scroller.content.setAttribute("style", "padding:0;min-height:0")
    mount(stream)

    stream.scroller.viewport.scrollTop = 100
    anchor = rows[2]
    previous_top = anchor.getBoundingClientRect().top
    stream.append_live(
        div({"style": "height:40px;flex:none;margin:0;padding:0"}, "R5")
    )

    assert rows[0].parentElement is None
    assert anchor.parentElement is stream.scroller.content
    assert abs(anchor.getBoundingClientRect().top - previous_top) < 2


@js
def test_streaming_list_newest_first_prepend_keeps_read_position():
    rows = [
        div({"style": "height:40px;flex:none"}, "R0"),
        div({"style": "height:40px;flex:none"}, "R1"),
        div({"style": "height:40px;flex:none"}, "R2"),
        div({"style": "height:40px;flex:none"}, "R3"),
        div({"style": "height:40px;flex:none"}, "R4"),
    ]
    stream = StreamingList(*rows, max_items=5, newest_first=True)
    stream.setAttribute("style", "height:80px")
    stream.scroller.setAttribute("style", "height:80px")
    stream.scroller.viewport.setAttribute("style", "height:80px;max-height:80px")
    stream.scroller.content.setAttribute("style", "padding:0;min-height:0")
    mount(stream)

    stream.scroller.viewport.scrollTop = 100
    anchor = rows[0]
    previous_top = anchor.getBoundingClientRect().top
    stream.append_live(div({"style": "height:40px;flex:none"}, "new"))
    assert abs(anchor.getBoundingClientRect().top - previous_top) < 2
