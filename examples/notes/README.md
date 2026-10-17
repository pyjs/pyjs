# Notes

Notes demonstrates web and native Android interfaces. The web application
uses DOM-owned ordering and server restoration; Android uses native
RecyclerView and an in-memory adapter.

The web application demonstrates:

- HTML drag-and-drop between Notes, Pinned, and Archive sections;
- precise before/after reordering and accessible arrow controls;
- DOM-owned ordering, server rendering, and hydration;
- per-browser server persistence restored after refresh; and
- browser interaction, native drag, and visual regression tests.

The Android example currently demonstrates variable-height masonry cards,
stable IDs, recycled-holder rebinding, colors, and long-press reordering.
Its search header is decorative. Search, editable notes/checklists,
pinned sections, navigation, and note actions are not implemented in this
example.

## Run

```console
python -m pyjs_examples.notes
python -m pyjs_examples.notes --android
```

The default starts the web server. `--android` builds and launches the JVM
implementation using Android framework classes and RecyclerView. It needs an
Android SDK and JDK, not a JavaScript Android runtime or Gradle project.
Android notes reset to the sample data on launch; no backend is required.

## Test

```console
pytest -q examples/notes/tests
pytest -q examples/notes/tests --pyjs-target=web \
  --pyjs-browser=managed
pytest -q examples/notes/tests/test_android_ui.py \
  --pyjs-target=android --pyjs-android-runtime=robolectric
pytest -q examples/notes/tests/test_android_ui.py \
  --pyjs-target=android --pyjs-android-runtime=device \
  --pyjs-android-avd=YOUR_AVD
```

`test_android_model.py` checks note/color/ID movement in CPython.
`test_android_ui.py` checks the native grid and initial adapter order under
Robolectric or on a device. Its device-only test drags a card in both directions
with UI Automator and checks the exact resulting stable-ID order on Espresso's
UI thread. No separate host-driven APK fixture is needed.
