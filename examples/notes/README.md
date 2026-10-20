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
Android card content is sample data. Its process-owned session retains pending
card order across activity recreation; successfully saved order also survives
process restarts. No backend is required.

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
`NotesApplication` owns the session and one status observer. Only the most
recently attached Activity receives automatic status updates; another live
Activity can retain an older status. Destruction detaches its observer without
removing a newer subscriber. Activity recreation or relaunch in that same
process restores pending order, dirty state, and the failure report without
reloading the old file. Only a new
process loads the saved snapshot, or initial samples if no snapshot exists.
Unsaved edits are not durable across process termination.

Unreadable or invalid snapshots leave the sample board usable but block
automatic saving. Repair or remove the snapshot and restart the app process;
dragging cannot overwrite it. Validation rejects unknown, duplicate,
noncanonical, incomplete and oversized saved orders.

`android_saves.py` runs writes on native Java threads. The main-thread session
serializes detached snapshots and coalesces completed drops while a write is
running. An acknowledgement only marks its own revision saved; later edits
remain dirty. Movement during an unfinished drag is not submitted until drop.
Failed writes stop automatic progression and expose a retry of the latest
order. Stale or duplicate acknowledgements cannot complete a newer attempt.

Results return through the main Handler. An atomic completion flag also
allows reattachment or retry to recover a result if posting was rejected.
The worker never updates views or the session directly. Initial bounded
loading remains synchronous. Native threads are not durable Android jobs.

This is a bounded, single-writer example. It does not implement multi-window
status synchronization, concurrent process writers, general note storage,
orphan recovery after process termination, or directory syncing for power-loss
durability.
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
cleanup failures to check preservation and retry. Save-queue tests control
completion explicitly to cover coalescing, detached snapshots, failed starts,
late acknowledgements and observer lifetimes. Native-driver tests cover
rejected callback recovery. `test_android_ui.py` checks
the native grid, restored order, retry controls and invalid-file protection
under Robolectric or on a device. Retained-session tests recreate the Activity
after failed saves, then replace the process-owned session to distinguish
in-memory recovery from disk restoration. That replacement is not a real OS
process-death test. Background tests use a bounded latch to keep a real worker
in flight during recreation, then verify completion or failure and retry.
Other injected-storage tests use the synchronous driver for precise outcomes.
Its device-only test drags a card, recreates
the activity to verify the saved order, then drags back with UI Automator.
Assertions inspect stable IDs on Espresso's UI thread.
