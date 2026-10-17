import pytest

from pyjs.web.ui.attachment import (
    Attachment,
    AttachmentAction,
    AttachmentActions,
    AttachmentContent,
    AttachmentDescription,
    AttachmentGroup,
    AttachmentMedia,
    AttachmentTitle,
    AttachmentTrigger,
)
from pyjs.web.ui.bubble import Bubble, BubbleContent, BubbleReactions
from pyjs.web.ui.marker import Marker, MarkerContent
from pyjs.web.ui.message import Message, MessageContent, MessageFooter, MessageHeader
from pyjs.web.ui.message_scroller import MessageScroller, MessageScrollerItem
from pyjs.web.ui.questionnaire import (
    Questionnaire,
    QuestionnaireChoice,
    QuestionnaireChoiceDescription,
    QuestionnaireChoices,
    QuestionnaireDescription,
    QuestionnaireError,
    QuestionnaireInput,
    QuestionnaireItem,
    QuestionnaireTitle,
)

pytestmark = pytest.mark.pyjs_python


def questionnaire():
    return Questionnaire(
        QuestionnaireItem(
            "scope",
            QuestionnaireTitle("What should the assistant do?"),
            QuestionnaireDescription("Choose one response."),
            QuestionnaireChoices(
                QuestionnaireChoice(
                    "explain",
                    "Explain the code",
                    QuestionnaireChoiceDescription("Focus on the design."),
                    shortcut="A",
                ),
                QuestionnaireChoice("test", "Write tests"),
            ),
            QuestionnaireError("Choose an answer to continue."),
            required=True,
        ),
        QuestionnaireItem(
            "context",
            QuestionnaireTitle("Add context"),
            QuestionnaireInput("Optional details"),
        ),
    )


def test_chat_content_primitives_expose_complete_state_and_semantics():
    trigger = AttachmentTrigger("Open report")
    attachment = Attachment(
        AttachmentMedia("PDF"),
        AttachmentContent(
            AttachmentTitle("report.pdf"),
            AttachmentDescription("240 KB"),
        ),
        AttachmentActions(AttachmentAction("Remove report", "×")),
        trigger,
        state="uploading",
        size="sm",
        orientation="vertical",
    )
    group = AttachmentGroup(attachment)
    bubble = Bubble(
        BubbleContent("Deployment complete."),
        BubbleReactions("👍", side="top", align="start"),
        align="end",
        variant="tinted",
    )
    message = Message(
        MessageContent(
            MessageHeader("Ada", "10:42"),
            bubble,
            MessageFooter("Delivered"),
        ),
        align="end",
    )
    marker = Marker(MarkerContent("Today"), variant="separator")

    assert group.getAttribute("role") == "list"
    assert attachment.getAttribute("data-state") == "uploading"
    assert attachment.getAttribute("data-size") == "sm"
    assert attachment.getAttribute("data-orientation") == "vertical"
    assert trigger.getAttribute("aria-label") == "Open report"
    assert bubble.getAttribute("data-align") == "end"
    assert bubble.children[1].getAttribute("data-side") == "top"
    assert message.getAttribute("data-align") == "end"
    assert marker.getAttribute("data-variant") == "separator"

    detail = QuestionnaireInput("Optional details")
    assert detail.getAttribute("aria-label") == "Optional details"


def test_message_scroller_has_accessible_composable_structure():
    first = MessageScrollerItem("First", scroll_anchor=True)
    scroller = MessageScroller(first, MessageScrollerItem("Second"))

    assert scroller.viewport.getAttribute("role") == "region"
    assert scroller.content.getAttribute("role") == "log"
    assert scroller.content.getAttribute("data-slot") == "message-scroller-content"
    assert first.getAttribute("data-scroll-anchor") == "true"
    assert scroller.getAttribute("data-pending-scroll") == "true"
    assert scroller.scroll_button.getAttribute("data-direction") == "end"
    assert scroller.scroll_button.getAttribute("data-active") == "false"
    assert scroller.scroll_button.getAttribute("tabindex") == "-1"


def test_questionnaire_owns_progress_validation_and_native_controls():
    survey = questionnaire()
    first, second = survey.get_items()
    choices = first.find_slots("questionnaire-choice-input")

    assert survey.progress.getAttribute("aria-valuenow") == "1"
    assert survey.progress.getAttribute("aria-valuetext") == "Question 1 of 2"
    assert not first.hasAttribute("hidden")
    assert second.hasAttribute("hidden")
    assert choices[0].getAttribute("name") == "scope"
    assert choices[0].getAttribute("type") == "radio"
    assert choices[0].getAttribute("data-shortcut") == "A"
    assert survey.skip.hasAttribute("hidden")
    assert survey.submit.hasAttribute("hidden")

    assert not first.validate()
    assert first.fieldset.getAttribute("aria-invalid") == "true"
    assert not first.find_slots("questionnaire-error")[0].hasAttribute("hidden")

    choices[0].checked = True
    assert first.validate()
    survey.advance(True)

    assert survey.progress.getAttribute("aria-valuenow") == "2"
    assert survey.progress.getAttribute("aria-valuetext") == "Question 2 of 2"
    assert first.hasAttribute("hidden")
    assert not second.hasAttribute("hidden")
    assert not survey.skip.hasAttribute("hidden")
    assert not survey.submit.hasAttribute("hidden")
    assert survey.next.hasAttribute("hidden")


def test_questionnaire_multiple_choices_use_checkbox_semantics():
    survey = Questionnaire(
        QuestionnaireItem(
            "features",
            QuestionnaireChoices(
                QuestionnaireChoice("chat", "Chat"),
                QuestionnaireChoice("files", "Files"),
            ),
            multiple=True,
        )
    )
    controls = survey.get_items()[0].find_slots("questionnaire-choice-input")

    assert controls[0].getAttribute("type") == "checkbox"
    assert controls[1].getAttribute("type") == "checkbox"
    assert controls[0].getAttribute("name") == "features"
