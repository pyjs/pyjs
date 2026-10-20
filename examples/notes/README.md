# Notes

Notes demonstrates web and native Android interfaces. The web application
uses DOM-owned ordering and server restoration; Android uses native
RecyclerView with sample cards and a locally saved card order.

The web application demonstrates:

- HTML drag-and-drop between Notes, Pinned, and Archive sections;
- precise before/after reordering and accessible arrow controls;
- DOM-owned ordering, server rendering, and hydration;
- per-browser server persistence restored after refresh; and
- browser interaction, native drag, and visual regression tests.

The Android example currently demonstrates variable-height masonry cards,
stable IDs, recycled-holder rebinding, colors, long-press reordering, and
recoverable local storage failures.
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
Android card content is sample data; card order survives activity recreation
and app launches. No backend is required.

## Android storage recovery

`android_storage.py` saves the seven card IDs in the app-private
`notes-order.txt`. A completed drag writes a unique sibling temporary file,
syncs and closes it, then checks replacement of the saved file. A failed
attempt cleans up its own temporary file without deleting the old snapshot.
An I/O failure during close does not replace an earlier body failure;
unsuccessful temporary-file cleanup is reported alongside the save failure.

`StorageError` retains destination and operation fields, the original I/O
exception as its cause/context, and its message in `.args`.
`OrderSession.failure_report` retains the full formatted chain independently
of the short status message. Successful load/save clears that report.

A failed save keeps the on-screen order and displays a tap-to-retry message.
Unreadable or invalid snapshots leave the sample board usable but block
automatic saving. Repair or remove the snapshot before relaunching; dragging
cannot overwrite it. Validation rejects unknown, duplicate, noncanonical,
incomplete and oversized saved orders.

This is a bounded, single-writer example. It saves only IDs, synchronously
after a drag, not during movement. It does not implement concurrent writers,
general note storage, orphan recovery after process termination, or directory
syncing for power-loss durability. Larger saves need a coordinated worker.
Replacement uses Android's `File.renameTo` behavior, not a portable desktop
storage abstraction. Hosts that refuse replacement of an existing destination
(such as OpenJDK on Windows) report failure and retain the old snapshot.

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
`test_android_storage.py` injects read, write, sync, close, replacement and
cleanup failures to check preservation and retry. `test_android_ui.py` checks
the native grid, restored order, retry controls and invalid-file protection
under Robolectric or on a device. Its device-only test drags a card, recreates
the activity to verify the saved order, then drags back with UI Automator.
Assertions inspect stable IDs on Espresso's UI thread.
