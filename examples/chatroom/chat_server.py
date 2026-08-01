import json
from datetime import datetime

from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

MAX_MESSAGES_PER_ROOM = 200
MAX_ROOMS = 50


class ChatClient:
    def __init__(self, name: str, room: str):
        self.name = name
        self.room = room


class ChatServer:
    def __init__(self):
        self.rooms: dict[str, list[dict[str, object]]] = {"general": []}
        self.clients: dict[ServerConnection, ChatClient] = {}
        self.next_message_id = 1

    async def handle(self, connection: ServerConnection):
        try:
            async for raw_message in connection:
                try:
                    message = json.loads(raw_message)
                    if not isinstance(message, dict):
                        raise ValueError("messages must be JSON objects")
                    await self.dispatch(connection, message)
                except (json.JSONDecodeError, ValueError) as error:
                    await self.send_error(connection, str(error))
        finally:
            if connection in self.clients:
                self.clients.pop(connection)
                await self.broadcast_snapshots()

    async def dispatch(self, connection: ServerConnection, message: dict[str, object]):
        message_type = message.get("type")
        if message_type == "join":
            await self.join(connection, message)
            return

        client = self.clients.get(connection)
        if client is None:
            raise ValueError("join the chatroom before sending messages")
        if message_type == "create_room":
            await self.create_room(client, message)
        elif message_type == "switch_room":
            await self.switch_room(client, message)
        elif message_type == "message":
            await self.add_message(client, message)
        else:
            raise ValueError("unknown chat message type")

    async def join(self, connection: ServerConnection, message: dict[str, object]):
        name = self.valid_name(message.get("name"))
        if any(client.name == name for client in self.clients.values()):
            raise ValueError("that display name is already in use")
        requested_room = self.normalize_room(message.get("room", "general"))
        room = requested_room if requested_room in self.rooms else "general"
        self.clients[connection] = ChatClient(name, room)
        await self.broadcast_snapshots()

    async def create_room(self, client: ChatClient, message: dict[str, object]):
        room = self.normalize_room(message.get("room"))
        if room not in self.rooms:
            if len(self.rooms) >= MAX_ROOMS:
                raise ValueError("the room limit has been reached")
            self.rooms[room] = []
        client.room = room
        await self.broadcast_snapshots()

    async def switch_room(self, client: ChatClient, message: dict[str, object]):
        room = self.normalize_room(message.get("room"))
        if room not in self.rooms:
            raise ValueError("that room does not exist")
        client.room = room
        await self.broadcast_snapshots()

    async def add_message(self, client: ChatClient, message: dict[str, object]):
        text = message.get("text")
        if not isinstance(text, str):
            raise ValueError("message text must be a string")
        text = text.strip()
        if not text:
            return
        if len(text) > 2000:
            raise ValueError("messages cannot exceed 2000 characters")
        room_messages = self.rooms[client.room]
        room_messages.append(
            {
                "id": self.next_message_id,
                "room": client.room,
                "sender": client.name,
                "text": text,
                "time": datetime.now().strftime("%H:%M"),
            }
        )
        self.next_message_id += 1
        if len(room_messages) > MAX_MESSAGES_PER_ROOM:
            del room_messages[:-MAX_MESSAGES_PER_ROOM]
        await self.broadcast_snapshots()

    def snapshot(self, client: ChatClient):
        users = sorted(
            candidate.name for candidate in self.clients.values() if candidate.room == client.room
        )
        return {
            "type": "snapshot",
            "room": client.room,
            "rooms": list(self.rooms),
            "messages": self.rooms[client.room],
            "users": users,
        }

    async def broadcast_snapshots(self):
        disconnected = []
        for connection, client in list(self.clients.items()):
            try:
                await connection.send(json.dumps(self.snapshot(client)))
            except ConnectionClosed:
                disconnected.append(connection)
        for connection in disconnected:
            self.clients.pop(connection, None)

        if disconnected:
            for connection, client in list(self.clients.items()):
                try:
                    await connection.send(json.dumps(self.snapshot(client)))
                except ConnectionClosed:
                    self.clients.pop(connection, None)

    async def send_error(self, connection: ServerConnection, message: str):
        await connection.send(json.dumps({"type": "error", "message": message}))

    def valid_name(self, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("display name must be a string")
        name = value.strip()
        if not name or len(name) > 32:
            raise ValueError("display name must contain 1 to 32 characters")
        return name

    def normalize_room(self, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("room name must be a string")
        room = value.strip().lower().replace(" ", "-")
        if not room or len(room) > 32:
            raise ValueError("room name must contain 1 to 32 characters")
        if not all(character.isalnum() or character in "-_" for character in room):
            raise ValueError("room names may contain letters, numbers, hyphens, and underscores")
        return room


chat_server = ChatServer()
