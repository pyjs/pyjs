from pyjs import js
from pyjs.web.dom import Element, Node, document
from pyjs.web.domx import CustomElement, button, ref, tag, tw
from pyjs.web.dragdrop import DragEvent
from pyjs.web.events import Event
from pyjs.web.ui import Widget


@js
def set_disabled(element: Element | None, disabled: bool):
    if element is None:
        return
    if disabled:
        element.setAttribute("disabled", "")
    else:
        element.removeAttribute("disabled")


@js
def refresh_column(cards: Element):
    column = cards.parentElement
    if column is None:
        return
    count = column.querySelector("[data-column-count]")
    if count is not None:
        count.textContent = str(len(cards.children))

    column_index_value = cards.getAttribute("data-column-index")
    if column_index_value is None:
        return
    column_index = int(column_index_value)
    card_count = len(cards.children)
    index = 0
    for card in cards.children:
        set_disabled(card.querySelector("[data-move-left]"), column_index == 0)
        set_disabled(
            card.querySelector("[data-move-right]"),
            column_index == 2,
        )
        set_disabled(card.querySelector("[data-move-up]"), index == 0)
        set_disabled(card.querySelector("[data-move-down]"), index == card_count - 1)
        index += 1


@js
def announce_move(card: Element, cards: Element):
    board = cards.closest("[data-kanban-board]")
    column = cards.parentElement
    if board is None or column is None:
        return
    status = board.querySelector("[data-board-status]")
    card_title = card.getAttribute("data-card-title")
    column_title = column.getAttribute("data-column-title")
    if status is not None and card_title is not None and column_title is not None:
        status.textContent = card_title + " moved to " + column_title


@js
def finish_move(card: Element, source: Element, destination: Element):
    refresh_column(source)
    if destination is not source:
        refresh_column(destination)
    announce_move(card, destination)


@js
def transferred_card(event: DragEvent) -> Element | None:
    transfer = event.dataTransfer
    if transfer is None:
        return None
    card_id = transfer.getData("application/x-pyjs-kanban-card")
    if card_id == "":
        return None
    return document.querySelector('[data-card-id="' + card_id + '"]')


@js
class KanbanCard(CustomElement):
    def __init__(self, card_id: str, title: str, description: str, priority: str):
        super().__init__()
        self.setAttribute("data-card-id", card_id)
        self.setAttribute("data-card-title", title)
        self.setAttribute("draggable", "true")
        self.setAttribute("tabindex", "0")

        self.move_left_button = ref(
            button(
                tw(
                    "rounded-md p-1 text-slate-500 hover:bg-slate-200 hover:text-slate-900 "
                    "focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-25"
                ),
                {
                    "aria-label": "Move " + title + " left",
                    "data-move-left": "",
                    "title": "Move left",
                    "type": "button",
                },
                "←",
            )
        )
        self.move_up_button = ref(
            button(
                tw(
                    "rounded-md p-1 text-slate-500 hover:bg-slate-200 hover:text-slate-900 "
                    "focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-25"
                ),
                {
                    "aria-label": "Move " + title + " up",
                    "data-move-up": "",
                    "title": "Move up",
                    "type": "button",
                },
                "↑",
            )
        )
        self.move_down_button = ref(
            button(
                tw(
                    "rounded-md p-1 text-slate-500 hover:bg-slate-200 hover:text-slate-900 "
                    "focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-25"
                ),
                {
                    "aria-label": "Move " + title + " down",
                    "data-move-down": "",
                    "title": "Move down",
                    "type": "button",
                },
                "↓",
            )
        )
        self.move_right_button = ref(
            button(
                tw(
                    "rounded-md p-1 text-slate-500 hover:bg-slate-200 hover:text-slate-900 "
                    "focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-25"
                ),
                {
                    "aria-label": "Move " + title + " right",
                    "data-move-right": "",
                    "title": "Move right",
                    "type": "button",
                },
                "→",
            )
        )

        self.addEventListener("dragstart", self.start_drag)
        self.addEventListener("dragend", self.end_drag)
        self.addEventListener("dragover", self.allow_card_drop)
        self.addEventListener("dragleave", self.leave_card)
        self.addEventListener("drop", self.drop_on_card)
        self.move_left_button.addEventListener("click", self.move_left)
        self.move_up_button.addEventListener("click", self.move_up)
        self.move_down_button.addEventListener("click", self.move_down)
        self.move_right_button.addEventListener("click", self.move_right)

        tag(
            self,
            tw(
                "group block cursor-grab rounded-xl border border-slate-200 bg-white p-4 "
                "shadow-sm transition hover:-translate-y-0.5 hover:border-indigo-300 "
                "hover:shadow-md focus:outline-none focus:ring-2 focus:ring-indigo-500 "
                "data-[dragging=true]:cursor-grabbing data-[dragging=true]:opacity-40 "
                "data-[drop-edge=before]:border-t-4 data-[drop-edge=before]:border-t-indigo-500 "
                "data-[drop-edge=after]:border-b-4 data-[drop-edge=after]:border-b-indigo-500"
            ),
            tag(
                "div",
                tw("mb-3 flex items-start justify-between gap-3"),
                tag(
                    "span",
                    tw(
                        "rounded-full bg-indigo-50 px-2.5 py-1 text-[11px] font-semibold "
                        "uppercase tracking-wide text-indigo-700"
                    ),
                    priority,
                ),
                tag(
                    "span",
                    tw("select-none text-lg leading-none text-slate-300"),
                    {"aria-hidden": "true", "title": "Drag card"},
                    "⠿",
                ),
            ),
            tag("h3", tw("text-sm font-semibold text-slate-950"), title),
            tag(
                "p",
                tw("mt-1.5 text-sm leading-5 text-slate-500"),
                description,
            ),
            tag(
                "div",
                tw(
                    "mt-4 flex items-center justify-end gap-0.5 border-t border-slate-100 pt-2 "
                    "opacity-70 transition group-hover:opacity-100 group-focus:opacity-100"
                ),
                self.move_left_button,
                self.move_up_button,
                self.move_down_button,
                self.move_right_button,
            ),
        )

    def sync_controls(self, column_index: int, index: int, card_count: int):
        set_disabled(self.move_left_button, column_index == 0)
        set_disabled(self.move_right_button, column_index == 2)
        set_disabled(self.move_up_button, index == 0)
        set_disabled(self.move_down_button, index == card_count - 1)

    def start_drag(self, event: DragEvent):
        transfer = event.dataTransfer
        card_id = self.getAttribute("data-card-id")
        if transfer is None or card_id is None:
            return
        transfer.effectAllowed = "move"
        transfer.setData("application/x-pyjs-kanban-card", card_id)
        transfer.setData("text/plain", card_id)
        self.setAttribute("data-dragging", "true")

    def end_drag(self, event: DragEvent):
        self.removeAttribute("data-dragging")
        self.removeAttribute("data-drop-edge")

    def allow_card_drop(self, event: DragEvent):
        event.preventDefault()
        transfer = event.dataTransfer
        if transfer is not None:
            transfer.dropEffect = "move"
        bounds = self.getBoundingClientRect()
        if float(event.clientY) < bounds.top + bounds.height / 2:
            self.setAttribute("data-drop-edge", "before")
        else:
            self.setAttribute("data-drop-edge", "after")

    def leave_card(self, event: DragEvent):
        self.removeAttribute("data-drop-edge")

    def drop_on_card(self, event: DragEvent):
        event.preventDefault()
        event.stopPropagation()
        self.removeAttribute("data-drop-edge")
        card = transferred_card(event)
        destination = self.parentElement
        if card is None or card is self or destination is None:
            return
        source = card.parentElement
        if source is None:
            return
        bounds = self.getBoundingClientRect()
        before: Node | None = self
        if float(event.clientY) >= bounds.top + bounds.height / 2:
            before = self.nextSibling
        destination.insertBefore(card, before)
        destination.removeAttribute("data-drag-over")
        finish_move(card, source, destination)

    def move_horizontal(self, offset: int):
        source = self.parentElement
        board = self.closest("[data-kanban-board]")
        if source is None or board is None:
            return
        column_index_value = source.getAttribute("data-column-index")
        if column_index_value is None:
            return
        destination_index = int(column_index_value) + offset
        if destination_index < 0 or destination_index >= 3:
            return
        destination = board.querySelector(
            '[data-column-cards][data-column-index="' + str(destination_index) + '"]'
        )
        if destination is None:
            return
        destination.append(self)
        finish_move(self, source, destination)

    def move_vertical(self, offset: int):
        cards = self.parentElement
        if cards is None:
            return
        current_index = -1
        index = 0
        for card in cards.children:
            if card is self:
                current_index = index
            index += 1
        destination_index = current_index + offset
        if current_index < 0 or destination_index < 0 or destination_index >= len(cards.children):
            return
        target = cards.children[destination_index]
        before: Node | None = target
        if offset > 0:
            before = target.nextSibling
        cards.insertBefore(self, before)
        finish_move(self, cards, cards)

    def move_left(self, event: Event):
        self.move_horizontal(-1)

    def move_up(self, event: Event):
        self.move_vertical(-1)

    def move_down(self, event: Event):
        self.move_vertical(1)

    def move_right(self, event: Event):
        self.move_horizontal(1)


@js
class KanbanColumn(CustomElement):
    def __init__(
        self,
        column_id: str,
        title: str,
        description: str,
        column_index: int,
        *cards: KanbanCard,
    ):
        super().__init__()
        self.setAttribute("data-column-id", column_id)
        self.setAttribute("data-column-title", title)
        self.cards = ref(
            tag(
                "div",
                tw(
                    "min-h-40 flex-1 space-y-3 rounded-xl border border-dashed "
                    "border-transparent transition data-[drag-over=true]:border-indigo-400 "
                    "data-[drag-over=true]:bg-indigo-50/70"
                ),
                {
                    "data-column-cards": "",
                    "data-column-index": str(column_index),
                    "data-testid": column_id + "-cards",
                },
                *cards,
            )
        )
        self.count = ref(
            tag(
                "span",
                tw(
                    "inline-flex min-w-6 items-center justify-center rounded-full bg-slate-200 "
                    "px-2 py-0.5 text-xs font-semibold text-slate-600"
                ),
                {"data-column-count": "", "aria-label": title + " card count"},
                str(len(cards)),
            )
        )
        self.cards.addEventListener("dragover", self.allow_drop)
        self.cards.addEventListener("dragleave", self.leave_drop_zone)
        self.cards.addEventListener("drop", self.drop_at_end)
        index = 0
        for card in cards:
            card.sync_controls(column_index, index, len(cards))
            index += 1
        tag(
            self,
            tw(
                "flex min-w-[18rem] flex-1 flex-col rounded-2xl border border-slate-200/80 "
                "bg-slate-100/90 p-3 shadow-sm"
            ),
            tag(
                "header",
                tw("mb-3 flex items-start justify-between gap-3 px-1 py-1"),
                tag(
                    "div",
                    tag("h2", tw("text-sm font-semibold text-slate-900"), title),
                    tag("p", tw("mt-0.5 text-xs text-slate-500"), description),
                ),
                self.count,
            ),
            self.cards,
        )

    def initialize(self):
        refresh_column(self.cards)

    def allow_drop(self, event: DragEvent):
        event.preventDefault()
        transfer = event.dataTransfer
        if transfer is not None:
            transfer.dropEffect = "move"
        self.cards.setAttribute("data-drag-over", "true")

    def leave_drop_zone(self, event: DragEvent):
        self.cards.removeAttribute("data-drag-over")

    def drop_at_end(self, event: DragEvent):
        event.preventDefault()
        self.cards.removeAttribute("data-drag-over")
        card = transferred_card(event)
        if card is None:
            return
        source = card.parentElement
        if source is None:
            return
        self.cards.append(card)
        finish_move(card, source, self.cards)


@js
class KanbanBoard(Widget):
    def __init__(self):
        super().__init__()
        self.setAttribute("data-kanban-board", "")

        self.scope_card = ref(
            KanbanCard(
                "scope-release",
                "Define release scope",
                "Agree on the smallest honest Python subset for the first public build.",
                "Done",
            )
        )
        self.runner_card = ref(
            KanbanCard(
                "browser-runner",
                "Ship browser test runner",
                "Capture screenshots and structured diagnostics for every failed UI test.",
                "Done",
            )
        )
        self.drag_card = ref(
            KanbanCard(
                "drag-drop",
                "Build drag-and-drop",
                "Move and reorder DOM-owned cards with native browser events.",
                "High",
            )
        )
        self.empty_states_card = ref(
            KanbanCard(
                "empty-states",
                "Polish empty states",
                "Keep each workflow stage inviting when it has no cards.",
                "Medium",
            )
        )
        self.onboarding_card = ref(
            KanbanCard(
                "onboarding-audit",
                "Audit onboarding flow",
                "Review the first five minutes from installation to a working browser app.",
                "High",
            )
        )
        self.checklist_card = ref(
            KanbanCard(
                "launch-checklist",
                "Write launch checklist",
                "Turn shakedown findings into focused fixes and regression tests.",
                "Medium",
            )
        )
        self.interview_card = ref(
            KanbanCard(
                "customer-interview",
                "Plan customer interview",
                "Collect feedback on Python ergonomics and generated JavaScript.",
                "Low",
            )
        )

        self.todo = ref(
            KanbanColumn(
                "todo",
                "Todo",
                "Ready to be picked up",
                0,
                self.onboarding_card,
                self.checklist_card,
                self.interview_card,
            )
        )
        self.in_progress = ref(
            KanbanColumn(
                "in-progress",
                "In progress",
                "Actively being shaped",
                1,
                self.drag_card,
                self.empty_states_card,
            )
        )
        self.done = ref(
            KanbanColumn(
                "done",
                "Done",
                "Completed this cycle",
                2,
                self.scope_card,
                self.runner_card,
            )
        )
        self.status = ref(
            tag(
                "p",
                tw("sr-only"),
                {"aria-live": "polite", "data-board-status": ""},
            )
        )
        self.columns = ref(
            tag(
                "section",
                tw(
                    "flex gap-4 overflow-x-auto rounded-3xl border border-slate-800 "
                    "bg-slate-900/70 p-4 shadow-2xl sm:p-5"
                ),
                {"aria-label": "Release workflow"},
                self.todo,
                self.in_progress,
                self.done,
            )
        )

        self.add(
            tw("block min-h-screen bg-slate-950 px-4 py-8 text-slate-950 sm:px-6 lg:px-8"),
            tag(
                "main",
                tw("mx-auto max-w-7xl"),
                tag(
                    "header",
                    tw(
                        "mb-8 flex flex-col gap-5 text-white sm:flex-row sm:items-end "
                        "sm:justify-between"
                    ),
                    tag(
                        "div",
                        tag(
                            "p",
                            tw(
                                "mb-2 text-xs font-semibold uppercase tracking-[0.24em] "
                                "text-indigo-300"
                            ),
                            "PyJS example",
                        ),
                        tag(
                            "h1",
                            tw("text-3xl font-bold tracking-tight sm:text-4xl"),
                            "Release board",
                        ),
                        tag(
                            "p",
                            tw("mt-2 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base"),
                            "Drag cards between columns, reorder them, or use the arrow controls.",
                        ),
                    ),
                    tag(
                        "div",
                        tw(
                            "inline-flex items-center gap-3 self-start rounded-xl border "
                            "border-slate-700 bg-slate-900 px-4 py-3 shadow-lg sm:self-auto"
                        ),
                        tag(
                            "span",
                            tw("h-2.5 w-2.5 rounded-full bg-emerald-400"),
                            {"aria-hidden": "true"},
                        ),
                        tag(
                            "span",
                            tw("text-sm font-medium text-slate-200"),
                            "7 cards · DOM state",
                        ),
                    ),
                ),
                self.columns,
                self.status,
            ),
        )


def main():
    return KanbanBoard()


if __name__ == "__main__":
    import os

    from pyjs.server import serve

    serve(__file__, port=int(os.environ.get("PYJS_PORT", "8000")))
