import pytest
from pyjs import js
from pyjs.testing.web import assert_render, mount
from pyjs.web.dom import Element
from pyjs.web.dragdrop import DataTransfer, DragEvent
from pyjs.web.events import Event
from pyjs_examples.kanban.kanban import KanbanBoard, KanbanCard, KanbanColumn

pytestmark = pytest.mark.pyjs_web


@js
def mounted_board() -> KanbanBoard:
    board = KanbanBoard()
    mount(board)
    return board


@js
def card_order(column: KanbanColumn) -> str:
    card_ids: list[str] = []
    for card in column.cards.children:
        card_id = card.getAttribute("data-card-id")
        if card_id is not None:
            card_ids.append(card_id)
    return ",".join(card_ids)


@js
def drag_to(source: KanbanCard, target: Element, client_y: int = 0):
    transfer = DataTransfer()
    source.dispatchEvent(
        DragEvent(
            "dragstart",
            bubbles=True,
            cancelable=True,
            dataTransfer=transfer,
        )
    )
    target.dispatchEvent(
        DragEvent(
            "dragover",
            bubbles=True,
            cancelable=True,
            clientY=client_y,
            dataTransfer=transfer,
        )
    )
    target.dispatchEvent(
        DragEvent(
            "drop",
            bubbles=True,
            cancelable=True,
            clientY=client_y,
            dataTransfer=transfer,
        )
    )
    source.dispatchEvent(DragEvent("dragend", bubbles=True, dataTransfer=transfer))


@js
def drop_before(source: KanbanCard, target: KanbanCard):
    bounds = target.getBoundingClientRect()
    drag_to(source, target, round(bounds.top + 1))


@js
def drop_after(source: KanbanCard, target: KanbanCard):
    bounds = target.getBoundingClientRect()
    drag_to(source, target, round(bounds.bottom - 1))


@js
def test_drag_moves_a_card_between_columns_and_updates_counts():
    board = mounted_board()

    drag_to(board.onboarding_card, board.in_progress.cards)

    assert card_order(board.todo) == "launch-checklist,customer-interview"
    assert card_order(board.in_progress) == "drag-drop,empty-states,onboarding-audit"
    assert board.todo.count.textContent == "2"
    assert board.in_progress.count.textContent == "3"
    assert board.onboarding_card.getAttribute("data-dragging") is None
    assert not board.in_progress.cards.hasAttribute("data-drag-over")
    assert board.status.textContent == "Audit onboarding flow moved to In progress"


@js
def test_drop_position_reorders_before_and_after_cards():
    board = mounted_board()

    drop_before(board.interview_card, board.onboarding_card)
    assert card_order(board.todo) == (
        "customer-interview,onboarding-audit,launch-checklist"
    )

    drop_after(board.interview_card, board.checklist_card)
    assert card_order(board.todo) == (
        "onboarding-audit,launch-checklist,customer-interview"
    )


@js
def test_invalid_and_self_drops_leave_the_board_unchanged():
    board = mounted_board()
    initial_todo = card_order(board.todo)
    initial_done = card_order(board.done)

    drag_to(board.onboarding_card, board.onboarding_card)

    invalid = DataTransfer()
    invalid.setData("application/x-pyjs-kanban-card", "missing-card")
    board.done.cards.dispatchEvent(
        DragEvent("drop", bubbles=True, cancelable=True, dataTransfer=invalid)
    )
    board.done.cards.dispatchEvent(DragEvent("drop", bubbles=True, cancelable=True))

    assert card_order(board.todo) == initial_todo
    assert card_order(board.done) == initial_done
    assert board.todo.count.textContent == "3"
    assert board.done.count.textContent == "2"


@js
def test_arrow_controls_move_and_reorder_cards_without_dragging():
    board = mounted_board()

    board.drag_card.move_down_button.dispatchEvent(Event("click"))
    assert card_order(board.in_progress) == "empty-states,drag-drop"
    assert board.drag_card.move_down_button.hasAttribute("disabled")
    assert not board.drag_card.move_up_button.hasAttribute("disabled")

    board.drag_card.move_left_button.dispatchEvent(Event("click"))
    assert card_order(board.todo) == (
        "onboarding-audit,launch-checklist,customer-interview,drag-drop"
    )
    assert card_order(board.in_progress) == "empty-states"
    assert board.todo.count.textContent == "4"
    assert board.in_progress.count.textContent == "1"
    assert board.drag_card.move_left_button.hasAttribute("disabled")


@js
def test_kanban_visual_showcase():
    board = mounted_board()
    drag_to(board.onboarding_card, board.in_progress.cards)

    assert card_order(board.in_progress) == "drag-drop,empty-states,onboarding-audit"
    mount(board.columns)
    assert_render(
        board.columns,
        "kanban-board",
        pixel_threshold=10,
        max_different_pixel_ratio=0.06,
    )
