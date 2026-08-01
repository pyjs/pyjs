import asyncio
import json

import pytest
from pyjs_examples.chatroom.chat_server import ChatServer

pytestmark = pytest.mark.pyjs_python


class FakeConnection:
    def __init__(self):
        self.messages = []

    async def send(self, message):
        self.messages.append(json.loads(message))


def test_room_creation_presence_and_messages_are_broadcast():
    async def exercise_chat():
        server = ChatServer()
        alice = FakeConnection()
        bob = FakeConnection()

        await server.dispatch(alice, {"type": "join", "name": "Alice", "room": "general"})
        await server.dispatch(bob, {"type": "join", "name": "Bob", "room": "general"})
        await server.dispatch(alice, {"type": "create_room", "room": "Design Team"})
        await server.dispatch(bob, {"type": "switch_room", "room": "design-team"})
        await server.dispatch(alice, {"type": "message", "text": "Welcome to design!"})
        await server.dispatch(bob, {"type": "message", "text": "Glad to be here."})

        return server, alice.messages[-1], bob.messages[-1]

    server, alice_snapshot, bob_snapshot = asyncio.run(exercise_chat())

    assert list(server.rooms) == ["general", "design-team"]
    assert alice_snapshot["room"] == "design-team"
    assert bob_snapshot["room"] == "design-team"
    assert alice_snapshot["users"] == ["Alice", "Bob"]
    assert [message["text"] for message in bob_snapshot["messages"]] == [
        "Welcome to design!",
        "Glad to be here.",
    ]


def test_chat_input_is_validated():
    async def send_invalid_message():
        server = ChatServer()
        connection = FakeConnection()
        await server.dispatch(connection, {"type": "join", "name": "Alice", "room": "general"})
        await server.dispatch(connection, {"type": "message", "text": 42})

    with pytest.raises(ValueError, match="message text must be a string"):
        asyncio.run(send_invalid_message())
