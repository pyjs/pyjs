# Android home-screen widget

This example packages a direct-JVM `AppWidgetProvider`, collection service,
application resources, generated `R` classes, and manifest components without
Gradle. The notes widget renders note rows through a
`RemoteViewsFactory` and opens its Activity when a row is tapped.

The minimum Android API remains 21. On API 31 and newer, the widget explicitly
requests a mutable pending intent for row fill-in intents. Older runtimes
retain their default mutable behavior without reading the API 31 flag field.

Build it with:

```console
python -c 'from examples.homescreen_widget.android_build import \
build_android_widget; print(build_android_widget())'
```

After installation, add “PyJS Home Screen Widget” from the launcher's widget
picker.
