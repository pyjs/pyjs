import pytest
from pyjs import js
from pyjs.testing.web import assert_render, mount
from pyjs.web.dom import Element
from pyjs.web.dragdrop import DataTransfer, DragEvent
from pyjs.web.events import Event
from pyjs_examples.notes.web import NoteSection, WebNoteCard, WebNotesApp

pytestmark = pytest.mark.pyjs_web


@js
def mounted_notes() -> WebNotesApp:
    board = WebNotesApp()
    mount(board)
    return board


@js
def note_order(column: NoteSection) -> str:
    card_ids: list[str] = []
    for card in column.cards.children:
        card_id = card.getAttribute("data-card-id")
        if card_id is not None:
            card_ids.append(card_id)
    return ",".join(card_ids)


@js
def drag_to(source: WebNoteCard, target: Element, client_y: int = 0):
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
def drop_before(source: WebNoteCard, target: WebNoteCard):
    bounds = target.getBoundingClientRect()
    drag_to(source, target, round(bounds.top + 1))


@js
def drop_after(source: WebNoteCard, target: WebNoteCard):
    bounds = target.getBoundingClientRect()
    drag_to(source, target, round(bounds.bottom - 1))


@js
def test_drag_moves_a_card_between_columns_and_updates_counts():
    board = mounted_notes()

    drag_to(board.groceries_card, board.pinned.cards)

    assert note_order(board.notes) == "design,reading"
    assert note_order(board.pinned) == "launch,weekend,groceries"
    assert board.notes.count.textContent == "2"
    assert board.pinned.count.textContent == "3"
    assert board.groceries_card.getAttribute("data-dragging") is None
    assert not board.pinned.cards.hasAttribute("data-drag-over")
    assert board.status.textContent == "Groceries moved to Pinned"


@js
def test_drop_position_reorders_before_and_after_cards():
    board = mounted_notes()

    drop_before(board.reading_card, board.groceries_card)
    assert note_order(board.notes) == "reading,groceries,design"

    drop_after(board.reading_card, board.design_card)
    assert note_order(board.notes) == "groceries,design,reading"


@js
def test_invalid_and_self_drops_leave_the_board_unchanged():
    board = mounted_notes()
    initial_notes = note_order(board.notes)
    initial_archive = note_order(board.archive)

    drag_to(board.groceries_card, board.groceries_card)

    invalid = DataTransfer()
    invalid.setData("application/x-pyjs-note-card", "missing-card")
    board.archive.cards.dispatchEvent(
        DragEvent("drop", bubbles=True, cancelable=True, dataTransfer=invalid)
    )
    board.archive.cards.dispatchEvent(DragEvent("drop", bubbles=True, cancelable=True))

    assert note_order(board.notes) == initial_notes
    assert note_order(board.archive) == initial_archive
    assert board.notes.count.textContent == "3"
    assert board.archive.count.textContent == "2"


@js
def test_arrow_controls_move_and_reorder_cards_without_dragging():
    board = mounted_notes()

    board.launch_card.move_down_button.dispatchEvent(Event("click"))
    assert note_order(board.pinned) == "weekend,launch"
    assert board.launch_card.move_down_button.hasAttribute("disabled")
    assert not board.launch_card.move_up_button.hasAttribute("disabled")

    board.launch_card.move_left_button.dispatchEvent(Event("click"))
    assert note_order(board.notes) == "groceries,design,reading,launch"
    assert note_order(board.pinned) == "weekend"
    assert board.notes.count.textContent == "4"
    assert board.pinned.count.textContent == "1"
    assert board.launch_card.move_left_button.hasAttribute("disabled")


@js
def test_web_notes_visual_showcase():
    board = mounted_notes()
    drag_to(board.groceries_card, board.pinned.cards)

    assert note_order(board.pinned) == "launch,weekend,groceries"
    mount(board.columns)
    assert_render(
        board.columns,
        "notes-board",
        pixel_threshold=10,
        max_different_pixel_ratio=0.06,
    )
