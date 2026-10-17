from pyjs_examples.notes.android import NotesAdapter


def test_adapter_reorders_note_color_and_stable_id_together():
    notes = ["one", "two", "three", "four"]
    colors = ["red", "green", "blue", "yellow"]
    note_ids = [11, 12, 13, 14]
    adapter = NotesAdapter(notes, colors, note_ids)

    adapter.move(0, 2)

    assert notes == ["two", "three", "one", "four"]
    assert colors == ["green", "blue", "red", "yellow"]
    assert note_ids == [12, 13, 11, 14]

    adapter.move(3, 1)

    assert notes == ["two", "four", "three", "one"]
    assert colors == ["green", "yellow", "blue", "red"]
    assert note_ids == [12, 14, 13, 11]
