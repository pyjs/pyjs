import pytest
from pyjs.web.ssr import render_html
from pyjs_examples.notes.web import WebNoteCard, WebNotesApp, main


@pytest.mark.pyjs_python
def test_web_notes_renders_dom_owned_sections_and_notes():
    board = main()

    assert isinstance(board, WebNotesApp)
    assert [len(column.cards.children) for column in (board.notes, board.pinned, board.archive)] == [
        3,
        2,
        2,
    ]
    count_html = render_html(board.notes.count)
    assert 'data-column-count=""' in count_html
    assert 'aria-label="Notes card count"' in count_html
    assert count_html.endswith(">3</span>")

    first = board.notes.cards.children[0]
    assert isinstance(first, WebNoteCard)
    assert first.getAttribute("data-card-id") == "groceries"
    assert first.getAttribute("draggable") == "true"
    assert first.move_left_button.hasAttribute("disabled")
    assert first.move_up_button.hasAttribute("disabled")
    assert not first.move_right_button.hasAttribute("disabled")


@pytest.mark.pyjs_python
def test_web_notes_contains_accessible_drag_alternatives():
    board = WebNotesApp()

    assert board.launch_card.move_left_button.getAttribute("aria-label") == (
        "Move Launch checklist left"
    )
    assert board.launch_card.move_up_button.getAttribute("title") == "Move up"
    assert board.status.getAttribute("aria-live") == "polite"


@pytest.mark.pyjs_python
def test_web_notes_restores_its_dom_owned_order_from_the_server_snapshot():
    board = WebNotesApp()
    snapshot = board.snapshot()

    assert snapshot == (
        "notes:groceries,design,reading;pinned:launch,weekend;"
        "archive:recipe,quote"
    )
    restored = WebNotesApp(
        "notes:design,reading;pinned:launch,weekend,groceries;"
        "archive:recipe,quote"
    )
    assert [
        note.getAttribute("data-card-id") for note in restored.pinned.cards.children
    ] == ["launch", "weekend", "groceries"]
