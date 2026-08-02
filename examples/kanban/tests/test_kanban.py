import pytest
from pyjs.web.ssr import render_html
from pyjs_examples.kanban.kanban import KanbanBoard, KanbanCard, main


@pytest.mark.pyjs_python
def test_board_renders_dom_owned_columns_and_cards():
    board = main()

    assert isinstance(board, KanbanBoard)
    assert [len(column.cards.children) for column in (board.todo, board.in_progress, board.done)] == [
        3,
        2,
        2,
    ]
    count_html = render_html(board.todo.count)
    assert 'data-column-count=""' in count_html
    assert 'aria-label="Todo card count"' in count_html
    assert count_html.endswith(">3</span>")

    first = board.todo.cards.children[0]
    assert isinstance(first, KanbanCard)
    assert first.getAttribute("data-card-id") == "onboarding-audit"
    assert first.getAttribute("draggable") == "true"
    assert first.move_left_button.hasAttribute("disabled")
    assert first.move_up_button.hasAttribute("disabled")
    assert not first.move_right_button.hasAttribute("disabled")


@pytest.mark.pyjs_python
def test_main_board_contains_accessible_drag_alternatives():
    board = KanbanBoard()

    assert board.drag_card.move_left_button.getAttribute("aria-label") == (
        "Move Build drag-and-drop left"
    )
    assert board.drag_card.move_up_button.getAttribute("title") == "Move up"
    assert board.status.getAttribute("aria-live") == "polite"
