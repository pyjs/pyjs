from typing import Literal

from pyjs.javascript import JSONObject


class ChatMessage(JSONObject):
    id: int
    room: str
    sender: str
    text: str
    time: str


class ChatCommand(JSONObject):
    type: Literal["join", "create_room", "switch_room", "message", "upgrade"]
    name: str
    room: str
    text: str


class ChatSnapshot(JSONObject):
    type: Literal["snapshot", "error"]
    room: str
    rooms: list[str]
    messages: list[ChatMessage]
    users: list[str]
    membership: Literal["free", "pro"]
    message: str
