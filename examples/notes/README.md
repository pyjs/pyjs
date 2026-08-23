# Notes

Notes is a polished, Google Keep-inspired application with web and native
Android interfaces. Both targets use DOM- or platform-owned state rather than
maintaining a second UI data store.

The web application demonstrates:

- native HTML drag-and-drop between Notes, Pinned, and Archive sections;
- precise before/after reordering and accessible arrow controls;
- DOM-owned note ordering;
- server-side rendering and hydration;
- per-browser server persistence restored after refresh; and
- browser interaction, native drag, and visual regression tests.

The Android application demonstrates a responsive masonry grid, pinned-note
sections, list and grid modes, search, navigation, note colors, editable text
and checklists, native drag reordering, and common note actions.

## Run the web application

```console
python -m pyjs_examples.notes
```

Open the printed URL. Move notes between sections and refresh the page to see
the server restore their order.

## Run the Android application

With an Android SDK and a running virtual device:

```console
python -m pyjs_examples.notes --android
```

## Run the tests

```console
pytest -q examples/notes/tests
pytest -q examples/notes/tests --pyjs-target=web \
  --pyjs-browser=managed
pytest -q examples/notes/tests/test_android_notes.py \
  --pyjs-target=android --pyjs-android-avd=Routine_Test
```

The Material Icons font is distributed under Apache License 2.0. Its license
is included beside the font in `mobile_assets/fonts/`.
