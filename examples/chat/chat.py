from typing import cast

from pyjs import effect, js, nojs, state
from pyjs.javascript import JSON
from pyjs.web.dom import Element, location, sessionStorage
from pyjs.web.domx import button, div, form, input, ref, span, tag, tw
from pyjs.web.events import Event, MessageEvent
from pyjs.web.network import WebSocket
from pyjs.web.ui import Widget
from pyjs.web.ui.attachment import (
    Attachment,
    AttachmentAction,
    AttachmentActions,
    AttachmentContent,
    AttachmentDescription,
    AttachmentGroup,
    AttachmentMedia,
    AttachmentTitle,
)
from pyjs.web.ui.avatar import Avatar, AvatarBadge
from pyjs.web.ui.badge import Badge
from pyjs.web.ui.bubble import Bubble, BubbleContent
from pyjs.web.ui.button import Button
from pyjs.web.ui.empty import (
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
)
from pyjs.web.ui.input_group import InputGroup, InputGroupAddon
from pyjs.web.ui.marker import Marker, MarkerContent
from pyjs.web.ui.message import (
    Message,
    MessageAvatar,
    MessageContent,
    MessageFooter,
    MessageHeader,
)
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
from pyjs.web.ui.sheet import (
    Sheet,
    SheetClose,
    SheetContent,
    SheetDescription,
    SheetFooter,
    SheetHeader,
    SheetTitle,
    SheetTrigger,
)

from .protocol import ChatCommand, ChatMessage, ChatSnapshot


@js
def initials(name: str) -> str:
    return name[:2].upper()


@js
def app_mark():
    return div(
        tw(
            "flex size-10 items-center justify-center rounded-xl bg-violet-500 "
            "font-bold text-white shadow-lg shadow-violet-950/30"
        ),
        "P",
    )


@js
def name_input_view():
    return input(
        tw(
            "h-11 w-full rounded-md border border-slate-300 bg-white px-3 text-sm "
            "outline-none placeholder:text-slate-400 focus:border-violet-500 "
            "focus:ring-2 focus:ring-violet-200"
        ),
        {
            "autocomplete": "nickname",
            "data-testid": "name-input",
            "maxlength": "32",
            "placeholder": "How should people know you?",
        },
    )


@js
def name_form_view(name_input: Element):
    submit = Button("Enter workspace", size="lg")
    submit.setAttribute("type", "submit")
    return form(tw("mt-6 grid gap-3"), name_input, submit)


@js
def room_input_view():
    return input(
        tw(
            "min-w-0 flex-1 rounded-lg border border-white/15 bg-white/10 px-3 py-2 "
            "text-sm text-white outline-none placeholder:text-slate-500 "
            "focus:border-violet-400 focus:bg-white/15"
        ),
        {
            "data-testid": "room-input",
            "maxlength": "32",
            "placeholder": "new-room",
        },
    )


@js
def room_form_view(room_input: Element):
    return form(
        tw("flex gap-2 px-3 pb-4"),
        room_input,
        button(
            tw(
                "flex size-9 shrink-0 items-center justify-center rounded-lg bg-violet-500 "
                "text-lg font-medium text-white hover:bg-violet-400 focus:outline-none "
                "focus:ring-2 focus:ring-violet-300"
            ),
            {
                "aria-label": "Create room",
                "data-testid": "create-room",
                "type": "submit",
            },
            "+",
        ),
    )


@js
def sign_out_button_view():
    return button(
        tw(
            "rounded-md px-2 py-1 text-xs text-slate-400 hover:bg-white/10 "
            "hover:text-white focus:outline-none focus:ring-2 focus:ring-violet-400"
        ),
        {"data-testid": "sign-out", "type": "button"},
        "Change",
    )


@js
def membership_plan_card(
    name: str,
    price: str,
    description: str,
    featured: bool = False,
):
    plan = div(
        tw(
            "rounded-xl border border-slate-200 bg-white p-4 "
            "data-[current=true]:border-violet-500 data-[current=true]:ring-2 "
            "data-[current=true]:ring-violet-100"
        ),
        {
            "data-current": "false",
            "data-featured": "true" if featured else "false",
            "data-membership-plan": name.lower(),
        },
        div(
            tw("flex items-start justify-between gap-4"),
            div(
                tag("h3", tw("font-semibold text-slate-950"), name),
                tag("p", tw("mt-1 text-xs leading-5 text-slate-500"), description),
            ),
            tag("strong", tw("shrink-0 text-sm text-slate-950"), price),
        ),
    )
    if featured:
        plan.append(
            div(
                tw("mt-3 flex flex-wrap gap-2 text-xs text-violet-700"),
                span("Unlimited history"),
                span("·"),
                span("File uploads"),
                span("·"),
                span("Priority support"),
            )
        )
    return plan


@js
def membership_sheet_view(
    free_plan: Element,
    pro_plan: Element,
    status: Element,
    upgrade_button: Button,
):
    return Sheet(
        SheetTrigger("Upgrade"),
        SheetContent(
            "Workspace membership",
            SheetHeader(
                SheetTitle("Workspace membership"),
                SheetDescription(
                    "Choose the plan for this workspace. Billing is shared by every room."
                ),
            ),
            div(tw("grid gap-3"), free_plan, pro_plan),
            div(
                tw("rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-500"),
                "This example simulates a successful Stripe Checkout webhook. A "
                "production app would activate the plan only after server confirmation.",
            ),
            status,
            SheetFooter(SheetClose("Close"), upgrade_button),
            side="right",
        ),
    )


@js
def assistant_button_view():
    return button(
        tw(
            "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm "
            "font-medium text-slate-300 outline-none hover:bg-white/10 hover:text-white "
            "focus-visible:ring-2 focus-visible:ring-violet-400 "
            "data-[active=true]:bg-violet-500/20 data-[active=true]:font-semibold "
            "data-[active=true]:text-white"
        ),
        {
            "data-active": "false",
            "data-testid": "assistant-destination",
            "type": "button",
        },
        span(
            tw(
                "flex size-7 items-center justify-center rounded-lg bg-gradient-to-br "
                "from-violet-400 to-fuchsia-500 text-sm text-white shadow-sm"
            ),
            "✦",
        ),
        div(
            tw("min-w-0 flex-1"),
            tag("span", tw("block truncate"), "PyJS Assistant"),
            tag("span", tw("block truncate text-[0.68rem] text-slate-500"), "Ask and build"),
        ),
    )


@js
def error_banner_view():
    return div(
        tw(
            "hidden border-b border-red-200 bg-red-50 px-5 py-3 text-sm font-medium "
            "text-red-700"
        ),
        {"data-testid": "chat-error", "role": "alert"},
    )


@js
def message_input_view():
    return input(
        tw(
            "h-11 min-w-0 flex-1 border-0 bg-transparent px-3 text-sm text-slate-950 "
            "outline-none placeholder:text-slate-400"
        ),
        {
            "autocomplete": "off",
            "data-testid": "message-input",
            "maxlength": "2000",
            "placeholder": "Message #general",
        },
    )


@js
def message_form_view(message_input: Element):
    send = Button("↑", size="icon")
    send.setAttribute("aria-label", "Send message")
    send.setAttribute("data-testid", "send-message")
    send.setAttribute("type", "submit")
    return form(InputGroup(message_input, InputGroupAddon(send, align="inline-end")))


@js
def sign_in_view(name_form: Element):
    return tag(
        "section",
        tw(
            "fixed inset-0 z-50 flex items-center justify-center bg-slate-950 p-6 "
            "font-sans text-slate-950"
        ),
        {"data-testid": "sign-in"},
        div(
            tw(
                "pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,"
                "rgba(139,92,246,0.28),transparent_42%)]"
            )
        ),
        div(
            tw(
                "relative w-full max-w-md rounded-3xl border border-white/10 bg-white p-8 "
                "shadow-2xl shadow-black/40"
            ),
            app_mark(),
            tag(
                "h1",
                tw("mt-6 text-2xl font-bold tracking-tight"),
                "Join PyJS Chat",
            ),
            tag(
                "p",
                tw("mt-2 text-sm leading-6 text-slate-500"),
                "Pick a display name for this tab. Rooms and messages reset when the "
                "server stops.",
            ),
            name_form,
        ),
    )


@js
def room_sidebar(
    room_form: Element,
    room_list: Element,
    assistant_button: Element,
    profile_avatar: Element,
    profile_name: Element,
    membership_sheet: Element,
    sign_out_button: Element,
):
    return tag(
        "aside",
        tw("flex min-h-0 flex-col border-r border-white/10 bg-slate-950 text-white"),
        tag(
            "header",
            tw("flex h-[4.75rem] items-center gap-3 border-b border-white/10 px-4"),
            app_mark(),
            div(
                tag("h1", tw("font-semibold tracking-tight"), "PyJS Chat"),
                tag("p", tw("text-xs text-slate-400"), "A real-time workspace"),
            ),
        ),
        div(
            tw("px-2 pb-3 pt-4"),
            tag(
                "h2",
                tw(
                    "mb-2 px-2 text-xs font-semibold uppercase tracking-[0.16em] "
                    "text-slate-400"
                ),
                "Assistant",
            ),
            assistant_button,
        ),
        div(
            tw("flex items-center justify-between px-4 pb-2 pt-2"),
            tag(
                "h2",
                tw("text-xs font-semibold uppercase tracking-[0.16em] text-slate-400"),
                "Rooms",
            ),
            tag("span", tw("text-xs text-slate-500"), "PUBLIC"),
        ),
        room_form,
        room_list,
        tag(
            "footer",
            tw(
                "flex flex-col gap-3 border-t border-white/10 px-4 py-3 text-sm"
            ),
            div(
                tw("flex items-center justify-between gap-3"),
                div(
                    tw("flex min-w-0 items-center gap-2.5"),
                    profile_avatar,
                    div(
                        profile_name,
                        tag("p", tw("text-xs text-emerald-400"), "Online"),
                    ),
                ),
                sign_out_button,
            ),
            membership_sheet,
        ),
    )


@js
def chat_header(
    current_room: Element,
    current_description: Element,
    connection_status: Element,
    reconnect_button: Element,
):
    return tag(
        "header",
        tw(
            "flex h-[4.75rem] shrink-0 items-center justify-between border-b "
            "border-slate-200 bg-white px-5"
        ),
        div(
            tw("min-w-0"),
            current_room,
            current_description,
        ),
        div(tw("flex items-center gap-2"), connection_status, reconnect_button),
    )


@js
def composer_view(message_form: Element, composer_hint: Element):
    return div(
        tw("shrink-0 border-t border-slate-200 bg-white p-4"),
        message_form,
        composer_hint,
    )


@js
def people_sidebar(
    people_title: Element,
    member_count: Element,
    member_list: Element,
):
    return tag(
        "aside",
        tw("hidden min-h-0 flex-col border-l border-slate-200 bg-white xl:flex"),
        tag(
            "header",
            tw(
                "flex h-[4.75rem] shrink-0 items-center justify-between border-b "
                "border-slate-200 px-4"
            ),
            people_title,
            member_count,
        ),
        member_list,
        div(
            tw("border-t border-slate-200 p-4"),
            Marker(MarkerContent("Built with PyJS components"), variant="separator"),
        ),
    )


@js
def workspace_view(
    sidebar: Element,
    header: Element,
    error_banner: Element,
    message_scroller: Element,
    composer: Element,
    people: Element,
):
    return div(
        tw(
            "hidden h-screen min-h-[36rem] overflow-hidden bg-slate-100 font-sans "
            "text-slate-950"
        ),
        {"data-testid": "workspace"},
        div(
            tw(
                "grid h-full grid-cols-[15rem_minmax(0,1fr)] "
                "xl:grid-cols-[15rem_minmax(0,1fr)_17rem]"
            ),
            sidebar,
            tag(
                "main",
                tw("flex min-h-0 min-w-0 flex-col bg-slate-50"),
                header,
                error_banner,
                message_scroller,
                composer,
            ),
            people,
        ),
    )


@js
def empty_message_view(room: str):
    return MessageScrollerItem(
        Empty(
            EmptyHeader(
                EmptyMedia("#", variant="icon"),
                EmptyTitle("This is the start of #" + room),
                EmptyDescription(
                    "Invite someone into the room or send the first message."
                ),
            )
        )
    )


@js
def chat_message_view(message: ChatMessage, current_name: str):
    sent = message["sender"] == current_name
    align = "end" if sent else "start"
    item = MessageScrollerItem(
        Message(
            MessageAvatar(initials(message["sender"])),
            MessageContent(
                MessageHeader(
                    tag("strong", message["sender"]),
                    tag("time", message["time"]),
                ),
                Bubble(
                    BubbleContent(
                        tag(
                            "p",
                            {"data-message-text": "true"},
                            message["text"],
                        )
                    ),
                    align=align,
                    variant="default" if sent else "secondary",
                ),
            ),
            align=align,
        ),
        scroll_anchor=sent,
    )
    item.setAttribute("data-message-id", str(message["id"]))
    return item


@js
def member_view(user: str):
    return div(
        tw("flex items-center gap-3 rounded-lg px-2 py-2 text-sm hover:bg-slate-50"),
        {"data-user": user},
        Avatar(AvatarBadge(), fallback=initials(user), size="sm"),
        div(
            tag("p", tw("truncate font-medium text-slate-800"), user),
            tag("p", tw("text-xs text-slate-400"), "Available"),
        ),
    )


@js
def assistant_questionnaire():
    return Questionnaire(
        QuestionnaireItem(
            "project-kind",
            QuestionnaireTitle("What are we building together?"),
            QuestionnaireDescription(
                "Choose a starting point and I will tailor the implementation plan."
            ),
            QuestionnaireChoices(
                QuestionnaireChoice(
                    "web",
                    "Web application",
                    QuestionnaireChoiceDescription(
                        "Server-rendered custom elements with an optional Python backend."
                    ),
                    shortcut="W",
                ),
                QuestionnaireChoice(
                    "mobile",
                    "Mobile application",
                    QuestionnaireChoiceDescription(
                        "A direct-JVM application using native Android APIs."
                    ),
                    shortcut="M",
                ),
                QuestionnaireChoice(
                    "universal",
                    "Universal application",
                    QuestionnaireChoiceDescription(
                        "Shared Python logic with web and mobile entry points."
                    ),
                    shortcut="U",
                ),
            ),
            QuestionnaireError("Choose a project type before continuing."),
            required=True,
        ),
        QuestionnaireItem(
            "project-goal",
            QuestionnaireTitle("What should the first milestone accomplish?"),
            QuestionnaireDescription(
                "A short outcome helps keep generated code focused and reviewable."
            ),
            QuestionnaireInput(placeholder="For example: let customers track an order"),
            QuestionnaireError("Describe the first milestone."),
            required=True,
        ),
    )


@js
def assistant_attachment():
    return Attachment(
        AttachmentMedia("MD"),
        AttachmentContent(
            AttachmentTitle("implementation-plan.md"),
            AttachmentDescription("4.2 KB · Ready to review"),
        ),
        AttachmentActions(AttachmentAction("Download implementation plan", "↓")),
    )


@js
def assistant_message(*children, footer: str = ""):
    content = MessageContent(
        MessageHeader(
            tag("strong", "PyJS Assistant"),
            Badge("AI", variant="secondary"),
        ),
        *children,
    )
    if footer != "":
        content.append(MessageFooter(footer))
    return MessageScrollerItem(
        Message(MessageAvatar("✦"), content),
    )


@js
def assistant_conversation_view():
    return [
        MessageScrollerItem(Marker(MarkerContent("Assistant session"), variant="separator")),
        assistant_message(
            Bubble(
                BubbleContent(
                    "Hi! I can help plan and build a PyJS application. Answer two quick "
                    "questions so I can prepare a focused starting point."
                ),
                variant="secondary",
            ),
            AttachmentGroup(assistant_attachment()),
            footer="Generated just now",
        ),
        assistant_message(assistant_questionnaire()),
    ]


@js
def assistant_user_message(text: str, name: str):
    item = MessageScrollerItem(
        Message(
            MessageAvatar(initials(name)),
            MessageContent(
                MessageHeader(tag("strong", name)),
                Bubble(
                    BubbleContent(tag("p", {"data-message-text": "true"}, text)),
                    align="end",
                ),
            ),
            align="end",
        ),
        scroll_anchor=True,
    )
    item.setAttribute("data-assistant-message", "user")
    return item


@js
def assistant_reply():
    item = assistant_message(
        Bubble(
            BubbleContent(
                "That makes sense. I would start with a small vertical slice, verify it in "
                "the browser, and then grow the application from working Python."
            ),
            variant="secondary",
        ),
        footer="Ready for the next instruction",
    )
    item.setAttribute("data-assistant-message", "assistant")
    return item


@js
def assistant_capabilities_view():
    return [
        div(
            tw("rounded-xl border border-violet-100 bg-violet-50 p-3"),
            tag("p", tw("text-sm font-semibold text-violet-950"), "Project context"),
            tag(
                "p",
                tw("mt-1 text-xs leading-5 text-violet-700"),
                "The assistant can ask structured questions and return reviewable artifacts.",
            ),
        ),
        div(
            tw("grid gap-2 px-1 text-xs text-slate-500"),
            tag("p", "✓ Understands PyJS components"),
            tag("p", "✓ Keeps generated work typed"),
            tag("p", "✓ Produces focused implementation plans"),
        ),
    ]


@js
class RoomClickListener:
    def __init__(self, app: ChatApp, room: str):
        self.app = app
        self.room = room

    def handleEvent(self, event: Event):
        self.app.switch_room(self.room)


@js
class ChatApp(Widget):
    name = state("")
    room = state("general")
    connection = state("signed-out")
    socket_path = state("")
    active_view = state("room")
    membership = state("free")

    def __init__(self, socket_path: str = ""):
        super().__init__()
        self.socket_path = socket_path

        self.name_input = ref(name_input_view())
        self.name_form = ref(name_form_view(self.name_input))
        self.name_form.addEventListener("submit", self.submit_name)
        self.sign_in = ref(sign_in_view(self.name_form))

        self.room_input = ref(room_input_view())
        self.room_form = ref(room_form_view(self.room_input))
        self.room_form.addEventListener("submit", self.create_room)
        self.room_list = ref(
            tag(
                "nav",
                tw("min-h-0 flex-1 space-y-1 overflow-y-auto px-2 pb-4"),
                {"aria-label": "Rooms", "data-testid": "room-list"},
            )
        )
        self.assistant_button = ref(assistant_button_view())
        self.assistant_button.addEventListener("click", self.open_assistant)
        self.profile_avatar = ref(Avatar(AvatarBadge(), fallback="ME", size="sm"))
        self.profile_name = ref(tag("span", tw("block truncate font-medium"), "Guest"))
        self.sign_out_button = ref(sign_out_button_view())
        self.sign_out_button.addEventListener("click", self.sign_out)
        self.free_plan = ref(
            membership_plan_card(
                "Free",
                "$0",
                "Five rooms, seven days of history, and live team messaging.",
            )
        )
        self.pro_plan = ref(
            membership_plan_card(
                "Pro",
                "$12 / member",
                "Long-lived workspaces for teams building with PyJS.",
                featured=True,
            )
        )
        self.membership_status = ref(
            tag(
                "p",
                tw("min-h-5 text-sm font-medium text-slate-600"),
                {"aria-live": "polite", "data-testid": "membership-status"},
            )
        )
        self.membership_button = ref(Button("Upgrade to Pro"))
        self.membership_button.setAttribute("data-testid", "upgrade-membership")
        self.membership_button.on_click(self.upgrade_membership)
        self.membership_sheet = ref(
            membership_sheet_view(
                self.free_plan,
                self.pro_plan,
                self.membership_status,
                self.membership_button,
            )
        )
        self.membership_sheet.trigger.setAttribute("data-testid", "membership-trigger")

        self.current_room = ref(
            tag("h2", tw("truncate text-lg font-semibold text-slate-950"), "# general")
        )
        self.current_description = ref(
            tag(
                "p",
                tw("truncate text-xs text-slate-500"),
                "A public room for the PyJS community",
            )
        )
        self.connection_status = ref(Badge("Not connected", variant="outline"))
        self.connection_status.setAttribute("data-testid", "connection-status")
        self.reconnect_button = ref(Button("Reconnect", variant="outline", size="sm"))
        self.reconnect_button.setAttribute("data-testid", "reconnect")
        self.reconnect_button.element.setAttribute("hidden", "")
        self.reconnect_button.element.addEventListener("click", self.reconnect)
        self.error_banner = ref(error_banner_view())

        self.message_scroller = ref(MessageScroller(label="Room messages"))
        self.message_scroller.add(tw("min-h-0 flex-1 bg-slate-50"))
        self.message_scroller.setAttribute("data-testid", "message-list")
        self.message_input = ref(message_input_view())
        self.message_form = ref(message_form_view(self.message_input))
        self.message_form.addEventListener("submit", self.submit_message)
        self.composer_hint = ref(
            tag(
                "p",
                tw("mt-2 px-1 text-[0.7rem] text-slate-400"),
                "Messages are shared live with everyone in this room.",
            )
        )

        self.member_count = ref(Badge("0 people", variant="secondary"))
        self.member_count.setAttribute("data-testid", "member-count")
        self.member_list = ref(
            div(
                tw("min-h-0 flex-1 space-y-1 overflow-y-auto p-3"),
                {"data-testid": "member-list"},
            )
        )
        self.people_title = ref(
            tag("h2", tw("font-semibold text-slate-900"), "In this room")
        )

        sidebar = room_sidebar(
            self.room_form,
            self.room_list,
            self.assistant_button,
            self.profile_avatar,
            self.profile_name,
            self.membership_sheet,
            self.sign_out_button,
        )
        header = chat_header(
            self.current_room,
            self.current_description,
            self.connection_status,
            self.reconnect_button.element,
        )
        composer = composer_view(self.message_form, self.composer_hint)
        people = people_sidebar(self.people_title, self.member_count, self.member_list)
        self.workspace = ref(
            workspace_view(
                sidebar,
                header,
                self.error_banner,
                self.message_scroller,
                composer,
                people,
            )
        )
        self.add(self.workspace, self.sign_in)

    def initialize(self):
        self.socket: WebSocket | None = None
        name = sessionStorage.getItem("pyjs-chat-display-name")
        if name is None or name == "":
            self.show_sign_in()
            return
        self.name = name
        self.show_workspace()
        self.connect()

    @effect(name)
    def render_name(self):
        self.profile_name.textContent = self.name if self.name != "" else "Guest"
        self.profile_avatar.fallback.textContent = (
            initials(self.name) if self.name != "" else "ME"
        )

    @effect(room)
    def render_room(self):
        if self.active_view == "assistant":
            return
        self.current_room.textContent = "# " + self.room
        self.message_input.setAttribute("placeholder", "Message #" + self.room)

    @effect(active_view)
    def render_active_view(self):
        assistant = self.active_view == "assistant"
        self.assistant_button.setAttribute("data-active", "true" if assistant else "false")
        if assistant:
            self.current_room.textContent = "PyJS Assistant"
            self.current_description.textContent = "Plan, build, and review a PyJS application"
            self.message_input.setAttribute("placeholder", "Ask the assistant anything")
            self.composer_hint.textContent = (
                "This local assistant preview uses deterministic responses—no API key needed."
            )
            self.people_title.textContent = "Assistant tools"
            self.member_count.textContent = "3 ready"
            self.member_list.replaceChildren(*assistant_capabilities_view())
            self.message_scroller.replace_messages(*assistant_conversation_view())
        else:
            self.current_description.textContent = "A public room for the PyJS community"
            self.composer_hint.textContent = (
                "Messages are shared live with everyone in this room."
            )
            self.people_title.textContent = "In this room"
            self.render_room()

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
            self.reconnect_button.element.removeAttribute("hidden")
        else:
            self.reconnect_button.element.setAttribute("hidden", "")

    @effect(membership)
    def render_membership(self):
        pro = self.membership == "pro"
        self.free_plan.setAttribute("data-current", "false" if pro else "true")
        self.pro_plan.setAttribute("data-current", "true" if pro else "false")
        self.membership_sheet.trigger.element.textContent = "Pro plan" if pro else "Upgrade"
        if pro:
            self.membership_status.textContent = "This workspace is on the Pro plan."
            self.membership_button.element.textContent = "Pro is active"
            self.membership_button.setAttribute("disabled", "")
        else:
            self.membership_status.textContent = "This workspace is currently on Free."
            self.membership_button.element.textContent = "Upgrade to Pro"
            self.membership_button.removeAttribute("disabled")

    def upgrade_membership(self, event: Event):
        if self.connection == "preview":
            self.membership = "pro"
            return
        self.send(
            ChatCommand(
                type="upgrade",
                name=self.name,
                room=self.room,
                text="",
            )
        )

    def show_sign_in(self):
        self.workspace.classList.add("hidden")
        self.sign_in.classList.remove("hidden")
        self.connection = "signed-out"
        self.name_input.focus()

    def show_workspace(self):
        self.sign_in.classList.add("hidden")
        self.workspace.classList.remove("hidden")

    def submit_name(self, event: Event):
        event.preventDefault()
        name = self.name_input.value.strip()
        if name == "":
            self.show_error("Enter a display name to join the workspace.")
            return
        sessionStorage.setItem("pyjs-chat-display-name", name)
        self.name = name
        self.show_workspace()
        self.connect()

    def sign_out(self, event: Event):
        sessionStorage.removeItem("pyjs-chat-display-name")
        if self.connection == "connected" and self.socket is not None:
            self.socket.close()
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
        socket.addEventListener("open", self.socket_opened)
        socket.addEventListener("message", self.socket_message)
        socket.addEventListener("close", self.socket_closed)
        socket.addEventListener("error", self.socket_error)

    def reconnect(self, event: Event):
        self.connect()

    def socket_opened(self, event: Event):
        self.connection = "connected"
        self.send(
            ChatCommand(type="join", name=self.name, room=self.room, text="")
        )

    def socket_message(self, event: MessageEvent):
        message: ChatSnapshot = JSON.parse(cast(str, event.data))
        self.receive(message)

    def socket_closed(self, event: Event):
        if self.connection != "signed-out":
            self.connection = "disconnected"

    def socket_error(self, event: Event):
        self.show_error("The chat server could not be reached.")

    def send(self, message: ChatCommand):
        if self.connection == "connected" and self.socket is not None:
            self.socket.send(JSON.stringify(message))

    def receive(self, message: ChatSnapshot):
        if message["type"] == "error":
            self.show_error(message["message"])
            return
        self.hide_error()
        self.room = message["room"]
        self.membership = message["membership"]
        self.render_rooms(message["rooms"])
        if self.active_view != "assistant":
            self.render_messages(message["messages"])
            self.render_members(message["users"])

    def render_rooms(self, rooms: list[str]):
        self.room_list.replaceChildren()
        for room in rooms:
            room_button = self.room_button(
                room,
                room == self.room and self.active_view == "room",
            )
            room_button.addEventListener("click", RoomClickListener(self, room))
            self.room_list.append(room_button)

    def room_button(self, room: str, active: bool):
        if active:
            style = tw(
                "flex w-full items-center gap-2 rounded-lg bg-violet-500/20 px-3 py-2 "
                "text-left text-sm font-semibold text-white"
            )
        else:
            style = tw(
                "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm "
                "font-medium text-slate-300 hover:bg-white/10 hover:text-white"
            )
        return button(
            style,
            {"data-room": room, "type": "button"},
            tag("span", tw("text-violet-400"), "#"),
            room,
        )

    def render_messages(self, messages: list[ChatMessage]):
        if len(messages) == 0:
            self.message_scroller.replace_messages(empty_message_view(self.room))
            return
        items: list[Element] = [
            MessageScrollerItem(Marker(MarkerContent("Today"), variant="separator"))
        ]
        for message in messages:
            items.append(chat_message_view(message, self.name))
        self.message_scroller.replace_messages(*items)

    def render_members(self, users: list[str]):
        self.member_list.replaceChildren()
        count = len(users)
        self.member_count.textContent = str(count) + (
            " person" if count == 1 else " people"
        )
        for user in users:
            self.member_list.append(member_view(user))

    def switch_room(self, room: str):
        self.active_view = "room"
        self.send(
            ChatCommand(
                type="switch_room",
                name=self.name,
                room=room,
                text="",
            )
        )

    def open_assistant(self, event: Event):
        self.active_view = "assistant"
        self.render_rooms_from_dom()

    def render_rooms_from_dom(self):
        rooms: list[str] = []
        for element in self.room_list.querySelectorAll("[data-room]"):
            room = element.getAttribute("data-room")
            if room is not None:
                rooms.append(room)
        self.render_rooms(rooms)

    def create_room(self, event: Event):
        event.preventDefault()
        room = self.room_input.value.strip()
        if room == "":
            return
        self.room_input.value = ""
        self.send(
            ChatCommand(
                type="create_room",
                name=self.name,
                room=room,
                text="",
            )
        )

    def submit_message(self, event: Event):
        event.preventDefault()
        text = self.message_input.value.strip()
        if text == "":
            return
        self.message_input.value = ""
        if self.active_view == "assistant":
            self.message_scroller.content.append(
                assistant_user_message(text, self.name),
                assistant_reply(),
            )
            self.message_scroller.scroll_to_latest()
            return
        self.send(
            ChatCommand(
                type="message",
                name=self.name,
                room=self.room,
                text=text,
            )
        )

    def show_error(self, message: str):
        self.error_banner.textContent = message
        self.error_banner.classList.remove("hidden")

    def hide_error(self):
        self.error_banner.classList.add("hidden")


def main(socket_path: str = ""):
    return ChatApp(socket_path=socket_path)


@nojs
def render(request):
    return main(socket_path="/ws")


@nojs
async def websocket(connection):
    from .chat_server import chat_server

    await chat_server.handle(connection)


if __name__ == "__main__":
    import os

    from pyjs.server.dev import serve

    serve(
        "chat",
        render=render,
        websocket_routes={"/ws": websocket},
        port=int(os.environ.get("PYJS_PORT", "8000")),
    )
