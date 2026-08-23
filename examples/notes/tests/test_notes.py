import pytest
from pyjs.nativescript import EventData, TextField, TextView, View
from pyjs.nativescript.masonry_reorder import (
    MasonryReorderController,
    MasonryReorderResult,
)
from pyjs_examples.notes.notes import NotesApp

pytestmark = pytest.mark.pyjs_python


def event_for(view: View) -> EventData:
    event = EventData()
    event.object = view
    return event


def test_notes_home_uses_masonry_sections_and_material_controls():
    app = NotesApp()

    assert [note.id for note in app.visible_notes()[:2]] == ["launch", "weekend"]
    assert app.root.getViewById("launch") is not None
    assert app.root.getViewById("groceries") is not None
    assert app.root.getViewById("pinned-notes-divider") is not None
    assert app.root.getViewById("toggle-layout").accessibilityLabel == (
        "Show notes as a list"
    )
    assert app.root.getViewById("new-note-plus").accessibilityLabel == "Create note"
    assert isinstance(app.note_reorder, MasonryReorderController)
    assert app.root.getViewById("groceries").accessibilityHint == (
        "Long press and drag to reorder"
    )


def test_notes_apply_the_committed_masonry_order_and_columns():
    app = NotesApp()
    visible = app.visible_notes()
    reordered_ids = [note.id for note in visible]
    reordered_ids[2], reordered_ids[3] = reordered_ids[3], reordered_ids[2]
    columns = [0, 1, 1, 0, 1, 0, 1]

    app.reorder_notes(
        MasonryReorderResult("design", reordered_ids, columns, 2)
    )

    assert [note.id for note in app.visible_notes()] == reordered_ids
    assert [app.note(item_id).grid_column for item_id in reordered_ids] == columns


def test_notes_search_and_list_mode_update_the_collection():
    app = NotesApp()
    search = app.root.getViewById("search-notes")
    assert isinstance(search, TextField)

    search.text = "typography"
    app.search_notes(event_for(search))

    assert [note.id for note in app.visible_notes()] == ["design"]
    assert app.root.getViewById("design") is not None
    assert app.root.getViewById("launch") is None

    app.toggle_layout(event_for(app.root.getViewById("toggle-layout")))

    assert app.layout_mode == "list"
    assert app.root.getViewById("toggle-layout").accessibilityLabel == (
        "Show notes as a grid"
    )


def test_notes_drawer_switches_between_local_views():
    app = NotesApp()
    app.open_navigation_drawer(event_for(app.root.getViewById("open-navigation")))

    drawer = app.root.getViewById("navigation-drawer")
    assert drawer is not None
    app.select_view(event_for(app.root.getViewById("drawer-archive")))

    assert app.view == "archive"
    assert [note.id for note in app.visible_notes()] == ["archive-demo"]
    assert app.root.getViewById("new-note-plus") is None

    app.open_navigation_drawer(event_for(app.root.getViewById("open-navigation")))
    app.select_view(event_for(app.root.getViewById("drawer-trash")))

    assert app.view == "trash"
    assert [note.id for note in app.visible_notes()] == ["trash-demo"]


def test_text_note_editor_updates_pin_color_and_archive_state():
    app = NotesApp()
    app.open_note(event_for(app.root.getViewById("design")))
    title = app.root.getViewById("editor-title")
    body = app.root.getViewById("editor-body")
    assert isinstance(title, TextField)
    assert isinstance(body, TextView)

    title.text = "Interface principles"
    body.text = "Clarity first."
    app.change_title(event_for(title))
    app.change_body(event_for(body))
    app.toggle_pin(event_for(app.root.getViewById("editor-pin")))
    app.toggle_palette(event_for(app.root.getViewById("toggle-colors")))
    app.choose_color(event_for(app.root.getViewById("color-mint")))

    note = app.note("design")
    assert note is not None
    assert (note.title, note.body, note.pinned, note.color) == (
        "Interface principles",
        "Clarity first.",
        True,
        "#ccff90",
    )
    assert app.root.getViewById("color-palette").visibility == "visible"

    app.archive_note(event_for(app.root.getViewById("editor-archive")))

    assert app.editing_id == ""
    assert note.archived
    assert app.root.getViewById("design") is None


def test_note_ellipsis_opens_actions_and_can_make_an_in_memory_copy():
    app = NotesApp()
    app.open_note(event_for(app.root.getViewById("design")))

    app.open_note_actions(event_for(app.root.getViewById("editor-more")))

    assert app.root.getViewById("note-actions") is not None
    assert app.root.getViewById("copy-note") is not None
    assert app.root.getViewById("delete-note") is not None
    app.copy_note(event_for(app.root.getViewById("copy-note")))

    copy = app.current_note()
    original = app.note("design")
    assert copy is not None
    assert original is not None
    assert copy.id != "design"
    assert copy.title == "Design notes (copy)"
    assert copy.body == original.body
    assert app.root.getViewById("note-actions") is None


def test_checklist_editor_toggles_edits_and_adds_items():
    app = NotesApp()
    app.open_note(event_for(app.root.getViewById("groceries")))

    coffee_toggle = app.root.getViewById("toggle-item-coffee")
    app.toggle_checklist_item(event_for(coffee_toggle))
    assert app.checklist_item("coffee").checked

    coffee = app.root.getViewById("coffee")
    assert isinstance(coffee, TextField)
    coffee.text = "Espresso beans"
    app.change_checklist_item(event_for(coffee))
    app.add_checklist_item(event_for(app.root.getViewById("add-checklist-item")))

    note = app.note("groceries")
    assert note is not None
    assert note.items[0].text == "Espresso beans"
    assert len(note.items) == 5
    assert app.root.getViewById("item-10") is not None


def test_creation_menu_opens_new_text_and_checklist_editors():
    app = NotesApp()
    app.toggle_creation_menu(event_for(app.root.getViewById("new-note-plus")))

    assert app.root.getViewById("new-text-note") is not None
    app.create_text_note(event_for(app.root.getViewById("new-text-note")))
    created_text = app.current_note()
    assert created_text is not None
    assert not created_text.is_checklist()
    assert app.root.getViewById("editor-body") is not None

    app.close_editor()
    app.toggle_creation_menu(event_for(app.root.getViewById("new-note-plus")))
    app.create_checklist(event_for(app.root.getViewById("new-checklist")))
    created_list = app.current_note()
    assert created_list is not None
    assert created_list.is_checklist()
    assert app.root.getViewById("add-checklist-item") is not None
