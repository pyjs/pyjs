# NativeScript Counter

A minimal native Android application written in Python and styled with Tailwind CSS. PyJS
transpiles the application and manages its private Node and NativeScript toolchain outside the
source tree.

With an Android SDK and at least one virtual device installed:

```bash
python -m pyjs_examples.nativescript_counter
```

The first run downloads the managed Node and NativeScript tools and creates a generated native
build workspace under `~/.cache/pyjs/`.

Run the host-side unit test normally:

```bash
python -m pytest -q examples/nativescript_counter/tests
```

Run the Android UI test on an existing emulator, or name an AVD for PyJS to start:

```bash
python -m pytest -q examples/nativescript_counter/tests \
  --pyjs-target=android --pyjs-android-avd=Routine_Test
```

The UI test launches the generated app, finds controls by NativeScript `testID`, taps the real
button, and waits for the native label to update. It retains a screenshot, Android UI hierarchy,
app-scoped logcat, and JSON artifact manifest under `.pytest_cache/pyjs/artifacts/android/`.
