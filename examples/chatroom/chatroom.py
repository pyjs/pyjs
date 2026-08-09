from typing import TypedDict

from pyjs import effect, js, nojs, state
from pyjs.javascript import JSON
from pyjs.web.dom import location, sessionStorage
from pyjs.web.domx import button, form, input, ref, tag, tw
from pyjs.web.events import Event, MessageEvent
from pyjs.web.network import WebSocket
from pyjs.web.ui import Widget


class ChatMessage(TypedDict):
    id: int
    room: str
    sender: str
    text: str
    time: str


class ChatSnapshot(TypedDict):
    type: str
    room: str
    rooms: list[str]
    messages: list[ChatMessage]
    users: list[str]
    message: str


@js
class OutgoingChatMessage:
    def __init__(self, message_type: str, name: str, room: str, text: str):
        self.type = message_type
        self.name = name
        self.room = room
        self.text = text


@js
class NameSubmitListener:
    def __init__(self, app: ChatRoomApp):
        self.app = app

    @js(include=True)
    def handleEvent(self, event: Event):
        event.preventDefault()
        self.app.submit_name()


@js
class RoomCreateListener:
    def __init__(self, app: ChatRoomApp):
        self.app = app

    @js(include=True)
    def handleEvent(self, event: Event):
        event.preventDefault()
        self.app.create_room()


@js
class MessageSubmitListener:
    def __init__(self, app: ChatRoomApp):
        self.app = app

    @js(include=True)
    def handleEvent(self, event: Event):
        event.preventDefault()
        self.app.submit_message()


@js
class RoomClickListener:
    def __init__(self, app: ChatRoomApp, room: str):
        self.app = app
        self.room = room

    @js(include=True)
    def handleEvent(self, event: Event):
        self.app.switch_room(self.room)


@js
class ReconnectClickListener:
    def __init__(self, app: ChatRoomApp):
        self.app = app

    @js(include=True)
    def handleEvent(self, event: Event):
        self.app.connect()


@js
class SignOutClickListener:
    def __init__(self, app: ChatRoomApp):
        self.app = app

    @js(include=True)
    def handleEvent(self, event: Event):
        self.app.sign_out()


@js
class SocketOpenListener:
    def __init__(self, app: ChatRoomApp):
        self.app = app

    @js(include=True)
    def handleEvent(self, event: Event):
        self.app.socket_opened()


@js
class SocketMessageListener:
    def __init__(self, app: ChatRoomApp):
        self.app = app

    @js(include=True)
    def handleEvent(self, event: MessageEvent):
        message: ChatSnapshot = JSON.parse(event.data)
        self.app.receive(message)


@js
class SocketCloseListener:
    def __init__(self, app: ChatRoomApp):
        self.app = app

    @js(include=True)
    def handleEvent(self, event: Event):
        self.app.socket_closed()


@js
class SocketErrorListener:
    def __init__(self, app: ChatRoomApp):
        self.app = app

    @js(include=True)
    def handleEvent(self, event: Event):
        self.app.show_error("The chat server could not be reached.")


@js
class ChatRoomApp(Widget):
    name = state("")
    room = state("general")
    connection = state("signed-out")
    socket_path = state("")

    def __init__(self, socket_path: str = ""):
        super().__init__()
        self.socket_path = socket_path

        self.name_input = ref(
            input(
                tw(
                    "w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-base "
                    "text-slate-950 outline-none placeholder:text-slate-400 "
                    "focus:border-violet-500 focus:ring-4 focus:ring-violet-100"
                ),
                {
                    "autocomplete": "nickname",
                    "data-testid": "name-input",
                    "maxlength": "32",
                    "placeholder": "How should people know you?",
                },
            )
        )
        self.name_form = ref(
            form(
                tw("mt-6 space-y-3"),
                self.name_input,
                button(
                    tw(
                        "w-full rounded-xl bg-violet-600 px-4 py-3 font-semibold text-white "
                        "shadow-sm hover:bg-violet-700 focus:outline-none focus:ring-4 "
                        "focus:ring-violet-200"
                    ),
                    {"type": "submit"},
                    "Enter workspace",
                ),
            )
        )
        self.name_form.addEventListener("submit", NameSubmitListener(self))
        self.sign_in = ref(
            tag(
                "section",
                tw(
                    "fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-6 "
                    "backdrop-blur-sm"
                ),
                {"data-testid": "sign-in"},
                tag(
                    "div",
                    tw("w-full max-w-md rounded-3xl bg-white p-8 shadow-2xl"),
                    tag(
                        "div",
                        tw(
                            "mb-5 flex h-12 w-12 items-center justify-center rounded-2xl "
                            "bg-violet-600 text-xl font-bold text-white"
                        ),
                        "P",
                    ),
                    tag(
                        "h1",
                        tw("text-2xl font-bold tracking-tight text-slate-950"),
                        "Join PyJS Workspace",
                    ),
                    tag(
                        "p",
                        tw("mt-2 text-sm leading-6 text-slate-500"),
                        "Choose a display name for this tab. Nothing is saved when the "
                        "server stops.",
                    ),
                    self.name_form,
                ),
            )
        )

        self.room_input = ref(
            input(
                tw(
                    "min-w-0 flex-1 rounded-lg border border-white/15 bg-white/10 px-3 py-2 "
                    "text-sm text-white outline-none placeholder:text-violet-200/70 "
                    "focus:border-white/40 focus:bg-white/15"
                ),
                {
                    "data-testid": "room-input",
                    "maxlength": "32",
                    "placeholder": "new-room",
                },
            )
        )
        self.room_form = ref(
            form(
                tw("flex gap-2 px-3 pb-4"),
                self.room_input,
                button(
                    tw(
                        "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/15 "
                        "text-lg font-medium text-white hover:bg-white/25 focus:outline-none "
                        "focus:ring-2 focus:ring-white/50"
                    ),
                    {"aria-label": "Create room", "data-testid": "create-room", "type": "submit"},
                    "+",
                ),
            )
        )
        self.room_form.addEventListener("submit", RoomCreateListener(self))
        self.room_list = ref(
            tag(
                "nav",
                tw("min-h-0 flex-1 space-y-1 overflow-y-auto px-2 pb-4"),
                {"aria-label": "Rooms", "data-testid": "room-list"},
            )
        )
        self.profile_name = ref(tag("span", tw("truncate font-medium"), "Guest"))
        self.sign_out_button = ref(
            button(
                tw(
                    "rounded-md px-2 py-1 text-xs text-violet-200 hover:bg-white/10 "
                    "hover:text-white focus:outline-none focus:ring-2 focus:ring-white/40"
                ),
                {"data-testid": "sign-out", "type": "button"},
                "Change",
            )
        )
        self.sign_out_button.addEventListener("click", SignOutClickListener(self))

        self.current_room = ref(tag("h2", tw("text-lg font-bold text-slate-950"), "# general"))
        self.connection_status = ref(
            tag("span", tw("text-xs font-medium text-slate-500"), "Not connected")
        )
        self.reconnect_button = ref(
            button(
                tw(
                    "hidden rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold "
                    "text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 "
                    "focus:ring-violet-300"
                ),
                {"data-testid": "reconnect", "type": "button"},
                "Reconnect",
            )
        )
        self.reconnect_button.addEventListener("click", ReconnectClickListener(self))
        self.error_banner = ref(
            tag(
                "div",
                tw(
                    "hidden border-b border-red-200 bg-red-50 px-5 py-3 text-sm font-medium "
                    "text-red-700"
                ),
                {"data-testid": "chat-error", "role": "alert"},
            )
        )
        self.message_list = ref(
            tag(
                "section",
                tw("min-h-0 flex-1 space-y-1 overflow-y-auto px-5 py-6"),
                {"aria-label": "Messages", "data-testid": "message-list"},
            )
        )
        self.message_input = ref(
            input(
                tw(
                    "min-w-0 flex-1 bg-transparent px-4 py-3 text-sm text-slate-950 outline-none "
                    "placeholder:text-slate-400"
                ),
                {
                    "autocomplete": "off",
                    "data-testid": "message-input",
                    "maxlength": "2000",
                    "placeholder": "Message #general",
                },
            )
        )
        self.message_form = ref(
            form(
                tw(
                    "flex items-center rounded-xl border border-slate-300 bg-white shadow-sm "
                    "focus-within:border-violet-500 focus-within:ring-4 "
                    "focus-within:ring-violet-100"
                ),
                self.message_input,
                button(
                    tw(
                        "mr-2 rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold text-white "
                        "hover:bg-violet-700 focus:outline-none focus:ring-2 focus:ring-violet-300"
                    ),
                    {"data-testid": "send-message", "type": "submit"},
                    "Send",
                ),
            )
        )
        self.message_form.addEventListener("submit", MessageSubmitListener(self))

        self.member_count = ref(
            tag(
                "span",
                tw("text-xs text-slate-500"),
                {"data-testid": "member-count"},
                "0 people",
            )
        )
        self.member_list = ref(
            tag(
                "div",
                tw("min-h-0 flex-1 space-y-1 overflow-y-auto p-3"),
                {"data-testid": "member-list"},
            )
        )

        self.workspace = ref(
            tag(
                "div",
                tw("hidden h-screen min-h-[36rem] overflow-hidden bg-slate-100 text-slate-950"),
                {"data-testid": "workspace"},
                tag(
                    "div",
                    tw(
                        "grid h-full grid-cols-[16rem_minmax(0,1fr)] "
                        "lg:grid-cols-[16rem_minmax(0,1fr)_15rem]"
                    ),
                    tag(
                        "aside",
                        tw("flex min-h-0 flex-col bg-violet-950 text-white"),
                        tag(
                            "header",
                            tw("border-b border-white/10 px-5 py-4"),
                            tag("p", tw("text-xs font-medium text-violet-300"), "WORKSPACE"),
                            tag(
                                "h1", tw("mt-1 text-xl font-bold tracking-tight"), "PyJS Community"
                            ),
                        ),
                        tag(
                            "div",
                            tw("flex items-center justify-between px-4 pb-2 pt-5"),
                            tag(
                                "h2",
                                tw(
                                    "text-xs font-semibold uppercase tracking-wider text-violet-300"
                                ),
                                "Rooms",
                            ),
                            tag("span", tw("text-violet-300"), "+"),
                        ),
                        self.room_form,
                        self.room_list,
                        tag(
                            "footer",
                            tw(
                                "flex items-center justify-between border-t border-white/10 "
                                "px-4 py-3 text-sm"
                            ),
                            tag(
                                "div",
                                tw("flex min-w-0 items-center gap-2"),
                                tag("span", tw("h-2.5 w-2.5 shrink-0 rounded-full bg-emerald-400")),
                                self.profile_name,
                            ),
                            self.sign_out_button,
                        ),
                    ),
                    tag(
                        "main",
                        tw("flex min-h-0 min-w-0 flex-col bg-white"),
                        tag(
                            "header",
                            tw(
                                "flex h-[4.5rem] shrink-0 items-center justify-between border-b "
                                "border-slate-200 px-5 shadow-sm"
                            ),
                            tag("div", self.current_room, self.connection_status),
                            self.reconnect_button,
                        ),
                        self.error_banner,
                        self.message_list,
                        tag("div", tw("shrink-0 border-t border-slate-100 p-4"), self.message_form),
                    ),
                    tag(
                        "aside",
                        tw("hidden min-h-0 flex-col border-l border-slate-200 bg-slate-50 lg:flex"),
                        tag(
                            "header",
                            tw(
                                "flex h-[4.5rem] shrink-0 items-center justify-between "
                                "border-b border-slate-200 px-4"
                            ),
                            tag("h2", tw("font-bold text-slate-900"), "People"),
                            self.member_count,
                        ),
                        self.member_list,
                    ),
                ),
            )
        )
        self.add(self.workspace, self.sign_in)

    def initialize(self):
        self.socket: WebSocket | None = None
        name = sessionStorage.getItem("pyjs-chatroom-display-name")
        if name is None or name == "":
            self.show_sign_in()
            return
        self.name = name
        self.show_workspace()
        self.connect()

    @effect(name)
    def render_name(self):
        self.profile_name.textContent = self.name if self.name != "" else "Guest"

    @effect(room)
    def render_room(self):
        self.current_room.textContent = "# " + self.room
        self.message_input.setAttribute("placeholder", "Message #" + self.room)

    @effect(connection)
    def render_connection(self):
        if self.connection == "connecting":
            self.connection_status.textContent = "Connecting…"
        elif self.connection == "connected":
            self.connection_status.textContent = "Connected"
        elif self.connection == "disconnected":
            self.connection_status.textContent = "Disconnected"
        elif self.connection == "preview":
            self.connection_status.textContent = "Preview mode"
        else:
            self.connection_status.textContent = "Not connected"
        if self.connection == "disconnected":
            self.reconnect_button.classList.remove("hidden")
        else:
            self.reconnect_button.classList.add("hidden")

    def show_sign_in(self):
        self.workspace.classList.add("hidden")
        self.sign_in.classList.remove("hidden")
        self.connection = "signed-out"
        self.name_input.focus()

    def show_workspace(self):
        self.sign_in.classList.add("hidden")
        self.workspace.classList.remove("hidden")

    def submit_name(self):
        name = self.name_input.value.strip()
        if name == "":
            self.show_error("Enter a display name to join the workspace.")
            return
        sessionStorage.setItem("pyjs-chatroom-display-name", name)
        self.name = name
        self.show_workspace()
        self.connect()

    def sign_out(self):
        sessionStorage.removeItem("pyjs-chatroom-display-name")
        socket = self.socket
        if self.connection == "connected":
            if socket is not None:
                socket.close()
        self.name = ""
        self.name_input.value = ""
        self.show_sign_in()

    def connect(self):
        if self.socket_path == "":
            self.connection = "preview"
            return
        self.connection = "connecting"
        socket = WebSocket("ws://" + location.host + self.socket_path)
        self.socket = socket
        socket.addEventListener("open", SocketOpenListener(self))
        socket.addEventListener("message", SocketMessageListener(self))
        socket.addEventListener("close", SocketCloseListener(self))
        socket.addEventListener("error", SocketErrorListener(self))

    def socket_opened(self):
        self.connection = "connected"
        self.send(OutgoingChatMessage("join", self.name, self.room, ""))

    def socket_closed(self):
        if self.connection == "signed-out":
            return
        self.connection = "disconnected"

    def send(self, message: OutgoingChatMessage):
        socket = self.socket
        if self.connection == "connected":
            if socket is not None:
                socket.send(JSON.stringify(message))

    def receive(self, message: ChatSnapshot):
        if message["type"] == "error":
            self.show_error(message["message"])
            return
        self.hide_error()
        self.room = message["room"]
        self.render_rooms(message["rooms"])
        self.render_messages(message["messages"])
        self.render_members(message["users"])

    def render_rooms(self, rooms: list[str]):
        self.room_list.replaceChildren()
        current_room = self.room
        for room in rooms:
            if room == current_room:
                room_button = button(
                    tw(
                        "flex w-full items-center gap-2 rounded-lg bg-white/15 px-3 py-2 "
                        "text-left text-sm font-semibold text-white"
                    ),
                    {"data-room": room, "type": "button"},
                    tag("span", tw("text-violet-300"), "#"),
                    room,
                )
            else:
                room_button = button(
                    tw(
                        "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm "
                        "font-medium text-violet-100 hover:bg-white/10 hover:text-white"
                    ),
                    {"data-room": room, "type": "button"},
                    tag("span", tw("text-violet-400"), "#"),
                    room,
                )
            room_button.addEventListener("click", RoomClickListener(self, room))
            self.room_list.append(room_button)

    def render_messages(self, messages: list[ChatMessage]):
        self.message_list.replaceChildren()
        if len(messages) == 0:
            self.message_list.append(
                tag(
                    "div",
                    tw("flex h-full min-h-64 flex-col items-center justify-center text-center"),
                    tag(
                        "div",
                        tw(
                            "flex h-14 w-14 items-center justify-center rounded-2xl bg-violet-100 "
                            "text-2xl font-bold text-violet-700"
                        ),
                        "#",
                    ),
                    tag(
                        "h3",
                        tw("mt-4 text-lg font-bold text-slate-900"),
                        "This is the start of #" + self.room,
                    ),
                    tag(
                        "p",
                        tw("mt-1 max-w-sm text-sm text-slate-500"),
                        "Say hello and start the conversation.",
                    ),
                )
            )
            return
        for message in messages:
            self.message_list.append(
                tag(
                    "article",
                    tw("group flex gap-3 rounded-lg px-2 py-2 hover:bg-slate-50"),
                    {"data-message-id": str(message["id"])},
                    tag(
                        "div",
                        tw(
                            "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg "
                            "bg-violet-100 text-sm font-bold text-violet-700"
                        ),
                        "●",
                    ),
                    tag(
                        "div",
                        tw("min-w-0 flex-1"),
                        tag(
                            "div",
                            tw("flex items-baseline gap-2"),
                            tag(
                                "strong",
                                tw("text-sm font-bold text-slate-900"),
                                message["sender"],
                            ),
                            tag(
                                "time",
                                tw("text-[0.7rem] text-slate-400"),
                                message["time"],
                            ),
                        ),
                        tag(
                            "p",
                            tw(
                                "mt-0.5 whitespace-pre-wrap break-words text-sm leading-6 "
                                "text-slate-700"
                            ),
                            message["text"],
                        ),
                    ),
                )
            )
        self.message_list.scrollTop = self.message_list.scrollHeight

    def render_members(self, users: list[str]):
        self.member_list.replaceChildren()
        count = len(users)
        self.member_count.textContent = str(count) + (" person" if count == 1 else " people")
        for user in users:
            self.member_list.append(
                tag(
                    "div",
                    tw("flex items-center gap-3 rounded-lg px-2 py-2 text-sm hover:bg-white"),
                    {"data-user": user},
                    tag("span", tw("h-2.5 w-2.5 rounded-full bg-emerald-500")),
                    tag("span", tw("truncate font-medium text-slate-700"), user),
                )
            )

    def switch_room(self, room: str):
        self.send(OutgoingChatMessage("switch_room", self.name, room, ""))

    def create_room(self):
        room = self.room_input.value.strip()
        if room == "":
            return
        self.room_input.value = ""
        self.send(OutgoingChatMessage("create_room", self.name, room, ""))

    def submit_message(self):
        text = self.message_input.value.strip()
        if text == "":
            return
        self.message_input.value = ""
        self.send(OutgoingChatMessage("message", self.name, self.room, text))

    def show_error(self, message: str):
        self.error_banner.textContent = message
        self.error_banner.classList.remove("hidden")

    def hide_error(self):
        self.error_banner.classList.add("hidden")


def main(socket_path: str = ""):
    return ChatRoomApp(socket_path=socket_path)


@nojs
def render(request):
    return main(socket_path="/ws")


@nojs
async def websocket(connection):
    from .chat_server import chat_server

    await chat_server.handle(connection)


if __name__ == "__main__":
    import os

    from pyjs.server import serve

    serve(
        "chatroom",
        render=render,
        websocket_routes={"/ws": websocket},
        port=int(os.environ.get("PYJS_PORT", "8000")),
    )
