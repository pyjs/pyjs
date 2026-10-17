import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from examples.homescreen_widget.android_build import build_android_widget
from pyjs.android.api import AndroidAPI
from pyjs.java import read_jvm_class, transpile_jvm
from pyjs.java.classfile import Bytecode, ClassFile, Field, Method
from pyjs.tooling.android import AndroidSDK
from pyjs.tooling.android_artifacts import AndroidArtifactClasspath
from pyjs.tooling.android_jvm import (
    AndroidJVMApplication,
    AndroidJVMBuilder,
    AndroidManifestComponent,
)

ANDROID_CALCULATOR = (
    Path(__file__).parents[2] / "examples" / "calculator" / "android.py"
)
ANDROID_NOTES = (
    Path(__file__).parents[2] / "examples" / "notes" / "android.py"
)
ANDROID_WIDGETS = (
    Path(__file__).parents[2] / "examples" / "homescreen_widget" / "android.py"
)


def android_sdk() -> tuple[Path, Path]:
    configured = os.environ.get("ANDROID_HOME") or os.environ.get(
        "ANDROID_SDK_ROOT"
    )
    root = Path(configured) if configured else Path.home() / "Android" / "Sdk"
    platforms = list((root / "platforms").glob("android-*/android.jar"))
    build_tools = list((root / "build-tools").glob("*/d8"))
    if not platforms or not build_tools:
        pytest.skip("an Android SDK platform and d8 are required")
    platform = max(
        platforms,
        key=lambda path: int(path.parent.name.removeprefix("android-")),
    )
    build_tool = max(build_tools, key=AndroidSDK._build_tools_version)
    return platform, build_tool


def javap():
    executable = shutil.which("java")
    if executable is None:
        pytest.skip("a Java runtime is required for JVM backend tests")
    return executable


def test_android_calculator_surface_compiles_to_framework_valid_dex(tmp_path):
    android_jar, d8 = android_sdk()
    classes = tmp_path / "classes"
    source = ANDROID_CALCULATOR.read_text()
    compilation = transpile_jvm(
        source,
        filename=str(ANDROID_CALCULATOR),
        module_name="pyjs_examples.calculator.android",
        class_name="PyjsAndroid",
    )
    compilation.write(classes)

    listener = subprocess.run(
        [
            javap(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-p",
            str(classes / "PyjsAndroid$CalculatorClickListener.class"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "implements android.view.View$OnClickListener" in listener
    assert "public void onClick(android.view.View)" in listener

    activity = subprocess.run(
        [
            javap(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-p",
            str(classes / "PyjsAndroid$CalculatorActivity.class"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "extends android.app.Activity" in activity
    assert "public void onCreate(android.os.Bundle)" in activity

    dex = tmp_path / "dex"
    dex.mkdir()
    result = subprocess.run(
        [
            str(d8),
            "--lib",
            str(android_jar),
            "--min-api",
            "21",
            "--output",
            str(dex),
            *(str(path) for path in classes.glob("*.class")),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (dex / "classes.dex").is_file()

    dump = subprocess.run(
        [str(d8.with_name("dexdump")), "-d", str(dex / "classes.dex")],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "source_file_idx" in dump
    assert "(android.py)" in dump
    assert "positions" in dump
    super_line = next(
        index
        for index, line in enumerate(source.splitlines(), 1)
        if "super().onCreate(state)" in line
    )
    assert f"line={super_line}" in dump


def test_android_shared_preferences_bindings_compile():
    source = """\
from pyjs.android import Activity, Bundle, LinearLayout, dp
from pyjs.java import i32


class PreferencesActivity(Activity):
    def onCreate(self, state: Bundle) -> None:
        super().onCreate(state)
        preferences = self.get_shared_preferences("notes", i32(0))
        editor = preferences.edit()
        editor.put_string("title", "Example")
        editor.put_long("updated", 42)
        editor.put_boolean("pinned", True)
        editor.apply()
        title = preferences.get_string("title", "")
        if title is not None:
            self.setTitle(title)
        content = LinearLayout(self)
        inset = dp(self, 16)
        content.setPadding(inset, inset, inset, inset)
        self.setContentView(content)


def main() -> int:
    PreferencesActivity().onCreate(Bundle())
    return 0
"""
    compilation = transpile_jvm(source, class_name="Preferences")
    activity = read_jvm_class(compilation.classes["Preferences$PreferencesActivity"])

    assert activity.declared_methods("onCreate")[0].descriptor == (
        "(Landroid/os/Bundle;)V"
    )
    assert any(
        b"android/util/TypedValue" in content
        for content in compilation.classes.values()
    )


def test_android_notes_compiles_recycler_view_callbacks(tmp_path):
    compilation = transpile_jvm(
        ANDROID_NOTES.read_text(),
        filename=str(ANDROID_NOTES),
        module_name="pyjs_examples.notes.android",
        class_name="org/pyjs/notes/jvm/PyjsAndroid",
    )

    adapter_name = "org/pyjs/notes/jvm/PyjsAndroid$NotesAdapter"
    holder_name = "org/pyjs/notes/jvm/PyjsAndroid$NoteHolder"
    adapter = compilation.classes[adapter_name]
    classes = tmp_path / "classes"
    compilation.write(classes)
    bytecode = subprocess.run(
        [
            javap(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-c",
            "-p",
            str(classes / f"{adapter_name}.class"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert bytecode.count('RecyclerView$Adapter."<init>":()V') == 1
    assert "RecyclerView$Adapter.__init__" not in bytecode
    assert "checkcast     #" in bytecode
    assert "class org/pyjs/notes/jvm/PyjsAndroid$NoteHolder" in bytecode

    holder = read_jvm_class(compilation.classes[holder_name])
    assert holder.declared_methods("<init>")[0].descriptor == (
        "(Landroid/widget/TextView;)V"
    )
    holder_bytecode = subprocess.run(
        [
            javap(),
            "-m",
            "jdk.jdeps/com.sun.tools.javap.Main",
            "-c",
            "-p",
            str(classes / f"{holder_name}.class"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert (
        'RecyclerView$ViewHolder."<init>":(Landroid/view/View;)V'
        in holder_bytecode
    )
    assert "RecyclerView$ViewHolder.itemView:Landroid/view/View;" in holder_bytecode

    parsed = read_jvm_class(adapter)
    string_list = "Lorg/pyjs/notes/jvm/PyjsAndroid$list$Ljava_lang_String_;"
    integer_list = "Lorg/pyjs/notes/jvm/PyjsAndroid$list$J;"
    assert parsed.declared_methods("<init>")[0].descriptor == (
        f"({string_list}{string_list}{integer_list})V"
    )
    assert {
        (method.name, method.descriptor)
        for method in parsed.methods
        if method.name != "<init>"
    } >= {
        ("getItemCount", "()I"),
        ("getItemId", "(I)J"),
        (
            "onBindViewHolder",
            "(Landroidx/recyclerview/widget/RecyclerView$ViewHolder;I)V",
        ),
        (
            "onCreateViewHolder",
            "(Landroid/view/ViewGroup;I)"
            "Landroidx/recyclerview/widget/RecyclerView$ViewHolder;",
        ),
    }
    touch = read_jvm_class(
        compilation.classes["org/pyjs/notes/jvm/PyjsAndroid$NotesTouch"]
    )
    assert touch.declared_methods("getMoveThreshold")[0].descriptor == (
        "(Landroidx/recyclerview/widget/RecyclerView$ViewHolder;)F"
    )
    assert touch.declared_methods("isLongPressDragEnabled")[0].descriptor == "()Z"


def test_android_widget_compiles_provider_callbacks_and_resource_references():
    compilation = transpile_jvm(
        ANDROID_WIDGETS.read_text(),
        filename=str(ANDROID_WIDGETS),
        module_name="pyjs_examples.homescreen_widget.android",
        class_name="org/pyjs/widgets/PyjsAndroid",
    )

    provider = read_jvm_class(
        compilation.classes["org/pyjs/widgets/PyjsAndroid$NotesWidgetProvider"]
    )
    factory = read_jvm_class(
        compilation.classes[
            "org/pyjs/widgets/PyjsAndroid$NotesRemoteViewsFactory"
        ]
    )
    service = read_jvm_class(
        compilation.classes[
            "org/pyjs/widgets/PyjsAndroid$NotesRemoteViewsService"
        ]
    )

    assert provider.super_name == "android/appwidget/AppWidgetProvider"
    assert provider.declared_methods("onUpdate")[0].descriptor == (
        "(Landroid/content/Context;Landroid/appwidget/AppWidgetManager;[I)V"
    )
    assert factory.declared_methods("getViewAt")[0].descriptor == (
        "(I)Landroid/widget/RemoteViews;"
    )
    assert service.declared_methods("onGetViewFactory")[0].descriptor == (
        "(Landroid/content/Intent;)"
        "Landroid/widget/RemoteViewsService$RemoteViewsFactory;"
    )


@pytest.mark.parametrize("sdk", [21, 30, 31, 35])
def test_widget_flags_do_not_link_new_fields_on_old_android(tmp_path, sdk):
    compilation = transpile_jvm('''
from pyjs_examples.homescreen_widget.android import widget_pending_intent_flags

def main() -> str:
    return str(widget_pending_intent_flags())
''')
    compilation.write(tmp_path)
    flags = {"FLAG_UPDATE_CURRENT": 134217728}
    if sdk >= 31:
        flags["FLAG_MUTABLE"] = 33554432
    for owner, fields in (
        ("android/os/Build$VERSION", {"SDK_INT": sdk}),
        ("android/app/PendingIntent", flags),
    ):
        # Deliberately omit the newer field, so an unguarded getstatic raises
        # NoSuchFieldError rather than passing against the API 35 compile jar.
        cls = ClassFile(owner)
        code = Bytecode()
        for name, value in fields.items():
            cls.add_field(Field(0x0019, name, "I"))
            constant = cls.constants.integer(value)
            code.emit(0x13, constant.to_bytes(2, "big"))
            field = cls.field_reference(owner, name, "I")
            code.emit(0xB3, field.to_bytes(2, "big"))
        code.emit(0xB1)
        cls.add_method(Method(0x0008, "<clinit>", "()V", code.render(), 1, 0))
        path = tmp_path / f"{owner}.class"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(cls.render())
    result = subprocess.run(
        [javap(), "-Xmx128m", "-Xverify:all", "-cp", str(tmp_path), "PyjsProgram"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == str(134217728 | (33554432 if sdk >= 31 else 0))


def test_widget_flag_guards_match_android_field_availability():
    try:
        api = AndroidAPI.from_sdk(35)
    except (FileNotFoundError, RuntimeError):
        pytest.skip("Android API 35 availability metadata is not installed")
    with api:
        for owner, name, since in (
            ("android/os/Build$VERSION", "SDK_INT", 21),
            ("android/app/PendingIntent", "FLAG_UPDATE_CURRENT", 21),
            ("android/app/PendingIntent", "FLAG_MUTABLE", 31),
        ):
            cls = api.require_class(owner)
            field = cls.declared_field(name)
            assert field is not None
            assert field.descriptor == "I"
            availability = api.field_availability(cls, field)
            assert availability is not None
            assert availability.available_at(since)
            if since == 31:
                assert not availability.available_at(30)


def test_android_editor_controls_compile_callbacks_and_framework_calls(tmp_path):
    source = """
from pyjs.android import (
    Activity,
    Bundle,
    Editable,
    JavaCharSequence,
    LinearLayout,
    TextWatcher,
    View,
)
from pyjs.android.controls import (
    CheckBox,
    CompoundButton,
    EditText,
    ImageButton,
    InputType,
    OnCheckedChangeListener,
    ScrollView,
)
from pyjs.java import i32


class ChangeWatcher(TextWatcher):
    def before_text_changed(
        self,
        text: JavaCharSequence,
        start: i32,
        count: i32,
        after: i32,
    ) -> None:
        pass

    def on_text_changed(
        self,
        text: JavaCharSequence,
        start: i32,
        before: i32,
        count: i32,
    ) -> None:
        pass

    def after_text_changed(self, text: Editable) -> None:
        pass


class CheckedListener(OnCheckedChangeListener):
    def on_checked_changed(
        self,
        button: CompoundButton,
        checked: bool,
    ) -> None:
        button.setEnabled(checked)


class EditorActivity(Activity):
    def onCreate(self, state: Bundle) -> None:
        super().onCreate(state)
        editor = EditText(self)
        editor.setHint("Write a note")
        editor.setInputType(
            InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE
        )
        editor.addTextChangedListener(ChangeWatcher())
        editor.set_selection_range(0, 0)
        checkbox = CheckBox(self)
        checkbox.set_on_checked_change_listener(CheckedListener())
        image = ImageButton(self)
        image.setContentDescription("Note actions")
        layout = LinearLayout(self)
        layout.addView(editor)
        layout.addView(checkbox)
        layout.addView(image)
        scroll = ScrollView(self)
        scroll.set_fill_viewport(True)
        scroll.addView(layout)
        self.setContentView(scroll)


def main() -> int:
    activity = EditorActivity()
    activity.onCreate(Bundle())
    return 0
"""
    compilation = transpile_jvm(source, class_name="ExampleEditor")
    classes = tmp_path / "classes"
    compilation.write(classes)
    watcher = read_jvm_class(compilation.classes["ExampleEditor$ChangeWatcher"])
    listener = read_jvm_class(compilation.classes["ExampleEditor$CheckedListener"])

    assert watcher.declared_methods("afterTextChanged")[0].descriptor == (
        "(Landroid/text/Editable;)V"
    )
    assert listener.declared_methods("onCheckedChanged")[0].descriptor == (
        "(Landroid/widget/CompoundButton;Z)V"
    )

    android_jar, d8 = android_sdk()
    dex = tmp_path / "dex"
    dex.mkdir()
    result = subprocess.run(
        [
            str(d8),
            "--lib",
            str(android_jar),
            "--min-api",
            "21",
            "--output",
            str(dex),
            *(str(path) for path in classes.rglob("*.class")),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_android_widget_packages_resources_manifest_and_generated_r(tmp_path):
    keystore = Path.home() / ".android" / "debug.keystore"
    if not keystore.is_file():
        pytest.skip("an Android debug keystore is required")

    package = build_android_widget(tmp_path / "apk")
    assert package.name == "org.pyjs.widgets-debug.apk"
    _, build_tool = android_sdk()
    manifest = subprocess.run(
        [
            str(build_tool.with_name("aapt2")),
            "dump",
            "xmltree",
            str(package),
            "--file",
            "AndroidManifest.xml",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    with zipfile.ZipFile(package) as archive:
        dex = tmp_path / "widget.dex"
        dex.write_bytes(archive.read("classes.dex"))
    bytecode = subprocess.run(
        [str(build_tool.with_name("dexdump")), "-d", str(dex)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert "PyJS Home Screen Widget" in manifest
    assert "PyjsAndroid$NotesWidgetProvider" in manifest
    assert "PyjsAndroid$NotesRemoteViewsService" in manifest
    assert "android.appwidget.action.APPWIDGET_UPDATE" in manifest
    assert "@0x7f" in manifest
    assert "PyjsAndroid$NotesWidgetProvider.onUpdate" in bytecode
    assert "Lorg/pyjs/widgets/R$layout;.notes_widget:I" in bytecode
    assert "Lorg/pyjs/widgets/R$id;.widget_list:I" in bytecode
    assert "Lorg/pyjs/widgets/R$id;.widget_item:I" in bytecode


def test_android_calculator_builds_a_signed_installable_apk(tmp_path):
    keystore = Path.home() / ".android" / "debug.keystore"
    if not keystore.is_file():
        pytest.skip("an Android debug keystore is required")
    sdk = AndroidSDK()
    application = AndroidJVMApplication(
        ANDROID_CALCULATOR,
        "pyjs_examples.calculator.android",
        "org.pyjs.calculator",
        "CalculatorActivity",
        "PyJS Calculator",
        35,
    )

    package = AndroidJVMBuilder(sdk).build(application, tmp_path)

    with zipfile.ZipFile(package) as archive:
        assert "AndroidManifest.xml" in archive.namelist()
        assert "classes.dex" in archive.namelist()
    badging = subprocess.run(
        [
            str(android_sdk()[1].with_name("aapt2")),
            "dump",
            "badging",
            str(package),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "package: name='org.pyjs.calculator'" in badging
    assert "application-debuggable" in badging
    assert (
        "launchable-activity: name="
        "'org.pyjs.calculator.PyjsAndroid$CalculatorActivity'" in badging
    )


def test_android_package_compiles_aar_resources_and_resource_classes(tmp_path):
    keystore = Path.home() / ".android" / "debug.keystore"
    if not keystore.is_file():
        pytest.skip("an Android debug keystore is required")
    aar = tmp_path / "widget.aar"
    with zipfile.ZipFile(aar, "w") as archive:
        archive.writestr(
            "AndroidManifest.xml",
            '<manifest package="org.pyjs.widget" />',
        )
        archive.writestr(
            "res/values/attrs.xml",
            '<resources><attr name="cardSpacing" format="dimension" /></resources>',
        )
    resources = tmp_path / "res"
    values = resources / "values"
    values.mkdir(parents=True)
    (values / "strings.xml").write_text(
        '<resources><string name="widget_title">Example</string></resources>'
    )
    application = AndroidJVMApplication(
        ANDROID_CALCULATOR,
        "pyjs_examples.calculator.android",
        "org.pyjs.calculator.resources",
        "CalculatorActivity",
        "PyJS Resources",
        35,
        resources=(resources,),
    )

    package = AndroidJVMBuilder().build(
        application,
        tmp_path / "apk",
        dependencies=AndroidArtifactClasspath((), (aar,)),
    )

    with zipfile.ZipFile(package) as archive:
        dex = tmp_path / "classes.dex"
        dex.write_bytes(archive.read("classes.dex"))
    dump = subprocess.run(
        [str(android_sdk()[1].with_name("dexdump")), "-d", str(dex)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "Lorg/pyjs/widget/R$attr;" in dump
    assert "Lorg/pyjs/calculator/resources/R$string;" in dump


def test_android_manifest_renders_widget_receivers_and_services():
    application = AndroidJVMApplication(
        ANDROID_CALCULATOR,
        "pyjs_examples.calculator.android",
        "org.pyjs.widgets",
        "CalculatorActivity",
        "PyJS Home Screen Widget",
        35,
        components=(
            AndroidManifestComponent(
                "receiver",
                "NotesWidgetProvider",
                actions=("android.appwidget.action.APPWIDGET_UPDATE",),
                metadata=(("android.appwidget.provider", "@xml/notes_widget"),),
            ),
            AndroidManifestComponent(
                "service",
                "NotesRemoteViewsService",
                permission="android.permission.BIND_REMOTEVIEWS",
            ),
        ),
    )

    manifest = AndroidJVMBuilder._manifest(application, 35)

    assert (
        'android:name="org.pyjs.widgets.PyjsAndroid$NotesWidgetProvider"'
        in manifest
    )
    assert (
        '<action android:name="android.appwidget.action.APPWIDGET_UPDATE" />' in manifest
    )
    assert 'android:resource="@xml/notes_widget"' in manifest
    assert (
        'android:name="org.pyjs.widgets.PyjsAndroid$NotesRemoteViewsService"' in manifest
    )
    assert 'android:permission="android.permission.BIND_REMOTEVIEWS"' in manifest


def test_android_package_rejects_an_unreachable_manifest_activity(tmp_path):
    source = tmp_path / "unreachable.py"
    source.write_text(
        """
from pyjs.android import Activity, Bundle


class UnreachedActivity(Activity):
    def onCreate(self, state: Bundle) -> None:
        super().onCreate(state)


def main() -> int:
    return 0
"""
    )
    application = AndroidJVMApplication(
        source,
        "unreachable",
        "org.pyjs.unreachable",
        "UnreachedActivity",
        "Unreachable",
        35,
    )

    with pytest.raises(RuntimeError, match="is not reachable from main"):
        AndroidJVMBuilder().build(application, tmp_path / "apk")
