from typing import cast

import pytest
from pyjs import js
from pyjs.testing.web import mount
from pyjs.web.dom import sessionStorage
from pyjs.web.domx import require_element
from pyjs.web.events import Event
from pyjs.web.html import HTMLButtonElement
from pyjs_examples.chat.chat import ChatApp
from pyjs_examples.chat.protocol import ChatMessage, ChatSnapshot

pytestmark = pytest.mark.pyjs_web


@js
def mounted_chat() -> ChatApp:
    app = ChatApp()
    mount(app)
    return app


@js
def test_chat_prompts_for_a_per_tab_display_name():
    sessionStorage.removeItem("pyjs-chat-display-name")
    app = mounted_chat()

    assert not app.sign_in.classList.contains("hidden")
    assert app.workspace.classList.contains("hidden")

    app.name_input.value = "Alice"
    app.name_form.dispatchEvent(Event("submit"))

    assert sessionStorage.getItem("pyjs-chat-display-name") == "Alice"
    assert app.getAttribute("name") == "Alice"
    assert app.sign_in.classList.contains("hidden")
    assert not app.workspace.classList.contains("hidden")
    assert app.reconnect_button.element.hasAttribute("hidden")


@js
def test_chat_renders_rooms_messages_and_presence_from_a_snapshot():
    sessionStorage.setItem("pyjs-chat-display-name", "Alice")
    app = mounted_chat()
    message = ChatMessage(
        id=1,
        room="design",
        sender="Bob",
        text="The new navigation is ready.",
        time="09:42",
    )
    reply = ChatMessage(
        id=2,
        room="design",
        sender="Alice",
        text="I will review it now.",
        time="09:43",
    )
    snapshot = ChatSnapshot(
        type="snapshot",
        room="design",
        rooms=["general", "design"],
        messages=[message, reply],
        users=["Alice", "Bob"],
        membership="free",
        message="",
    )

    app.receive(snapshot)

    assert app.current_room.textContent == "# design"
    assert len(app.room_list.querySelectorAll("[data-room]")) == 2
    assert app.message_scroller.getAttribute("data-slot") == "message-scroller"
    assert len(app.message_scroller.querySelectorAll("[data-message-id]")) == 2
    assert (
        require_element(app.message_scroller, "[data-message-text]").textContent
        == "The new navigation is ready."
    )
    assert (
        require_element(
            app.message_scroller,
            '[data-message-id="1"] [data-slot="message"]',
        ).getAttribute("data-align")
        == "start"
    )
    assert (
        require_element(
            app.message_scroller,
            '[data-message-id="2"] [data-slot="message"]',
        ).getAttribute("data-align")
        == "end"
    )
    assert len(app.member_list.querySelectorAll("[data-user]")) == 2
    assert app.member_count.textContent == "2 people"


@js
def test_chat_combines_human_rooms_with_an_assistant_conversation():
    sessionStorage.setItem("pyjs-chat-display-name", "Alice")
    app = mounted_chat()
    snapshot = ChatSnapshot(
        type="snapshot",
        room="general",
        rooms=["general", "design"],
        messages=[],
        users=["Alice"],
        membership="free",
        message="",
    )
    app.receive(snapshot)

    app.assistant_button.dispatchEvent(Event("click"))

    assert app.getAttribute("active-view") == "assistant"
    assert app.assistant_button.getAttribute("data-active") == "true"
    assert app.current_room.textContent == "PyJS Assistant"
    assert app.member_count.textContent == "3 ready"
    assert app.message_scroller.querySelector("[data-slot=questionnaire]") is not None
    assert app.message_scroller.querySelector("[data-slot=attachment]") is not None

    app.message_input.value = "Help me build a customer portal."
    app.message_form.dispatchEvent(Event("submit"))

    assert len(app.message_scroller.querySelectorAll("[data-assistant-message]")) == 2
    assert (
        require_element(
            app.message_scroller,
            '[data-assistant-message="user"] [data-message-text]',
        ).textContent
        == "Help me build a customer portal."
    )


@js
def test_chat_membership_tracks_the_workspace_plan():
    sessionStorage.setItem("pyjs-chat-display-name", "Alice")
    app = mounted_chat()
    upgrade_button = app.membership_button.element
    assert isinstance(upgrade_button, HTMLButtonElement)

    assert app.membership == "free"
    assert not upgrade_button.disabled
    assert app.free_plan.getAttribute("data-current") == "true"
    assert app.pro_plan.getAttribute("data-current") == "false"
    assert app.membership_sheet.trigger.element.textContent == "Upgrade"

    app.membership_sheet.open()
    cast(HTMLButtonElement, app.membership_button.element).click()

    assert app.membership == "pro"
    assert app.free_plan.getAttribute("data-current") == "false"
    assert app.pro_plan.getAttribute("data-current") == "true"
    assert app.membership_sheet.trigger.element.textContent == "Pro plan"
    assert upgrade_button.disabled
    assert "Pro plan" in app.membership_status.textContent

    app.membership = "free"

    assert not upgrade_button.disabled
    assert upgrade_button.textContent == "Upgrade to Pro"
    assert app.free_plan.getAttribute("data-current") == "true"
    assert app.pro_plan.getAttribute("data-current") == "false"
    upgrade_button.click()
    assert app.membership == "pro"
    assert upgrade_button.disabled
