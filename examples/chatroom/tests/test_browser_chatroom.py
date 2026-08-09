import pytest
from pyjs import js
from pyjs.testing.web import mount
from pyjs.web.dom import sessionStorage
from pyjs.web.domx import require_element
from pyjs.web.events import Event
from pyjs_examples.chatroom.chatroom import ChatMessage, ChatRoomApp, ChatSnapshot

pytestmark = pytest.mark.pyjs_web


@js
def mounted_chatroom() -> ChatRoomApp:
    app = ChatRoomApp()
    mount(app)
    return app


@js
def test_chatroom_prompts_for_a_per_tab_display_name():
    sessionStorage.removeItem("pyjs-chatroom-display-name")
    app = mounted_chatroom()

    assert not app.sign_in.classList.contains("hidden")
    assert app.workspace.classList.contains("hidden")

    app.name_input.value = "Alice"
    app.name_form.dispatchEvent(Event("submit"))

    assert sessionStorage.getItem("pyjs-chatroom-display-name") == "Alice"
    assert app.getAttribute("name") == "Alice"
    assert app.sign_in.classList.contains("hidden")
    assert not app.workspace.classList.contains("hidden")


@js
def test_chatroom_renders_rooms_messages_and_presence_from_a_snapshot():
    sessionStorage.setItem("pyjs-chatroom-display-name", "Alice")
    app = mounted_chatroom()
    message = ChatMessage(
        id=1,
        room="design",
        sender="Bob",
        text="The new navigation is ready.",
        time="09:42",
    )
    snapshot = ChatSnapshot(
        type="snapshot",
        room="design",
        rooms=["general", "design"],
        messages=[message],
        users=["Alice", "Bob"],
        message="",
    )

    app.receive(snapshot)

    assert app.current_room.textContent == "# design"
    assert len(app.room_list.querySelectorAll("[data-room]")) == 2
    assert len(app.message_list.querySelectorAll("[data-message-id]")) == 1
    assert require_element(app.message_list, "p").textContent == "The new navigation is ready."
    assert len(app.member_list.querySelectorAll("[data-user]")) == 2
    assert app.member_count.textContent == "2 people"
