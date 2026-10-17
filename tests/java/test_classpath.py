import shutil
import subprocess
import zipfile

import pytest

from pyjs.android.api import AndroidAPI, AndroidAvailability, AndroidNullability
from pyjs.java import (
    JVMAnnotation,
    JVMBindingError,
    JVMClassBinding,
    JVMClassFormatError,
    JVMClasspath,
    JVMExternalClass,
    JVMFieldBinding,
    JVMMethod,
    JVMMethodBinding,
    JVMParameter,
    read_jvm_class,
)
from pyjs.java.classfile import (
    Annotation,
    ClassAnnotationValue,
    ClassFile,
    Field,
    Method,
    TypeAnnotation,
)


@pytest.fixture
def generated_class(tmp_path):
    classes = tmp_path / "classes"
    class_file = ClassFile(
        "sample/Generated",
        interfaces=("java/lang/Runnable",),
        source_file="generated.py",
        annotations=(
            Annotation(
                "Lorg/junit/runner/RunWith;",
                (
                    (
                        "value",
                        ClassAnnotationValue("Lsample/GeneratedRunner;"),
                    ),
                ),
            ),
        ),
    )
    nullable = "Lorg/jspecify/annotations/Nullable;"
    class_file.add_field(
        Field(
            0x0001,
            "title",
            "Ljava/lang/String;",
            type_annotations=(TypeAnnotation(nullable, 0x13),),
        )
    )
    class_file.add_method(
        Method(
            0x0001,
            "run",
            "()V",
            b"\xb1",
            0,
            1,
            annotations=(Annotation("Lorg/junit/Test;"),),
        )
    )
    class_file.add_method(
        Method(
            0x0001,
            "optional",
            "(Ljava/lang/String;)Ljava/lang/String;",
            b"\x2b\xb0",
            1,
            2,
            type_annotations=(
                TypeAnnotation(nullable, 0x14),
                TypeAnnotation(nullable, 0x16, target_index=0),
            ),
        )
    )
    output = classes / "sample" / "Generated.class"
    output.parent.mkdir(parents=True)
    output.write_bytes(class_file.render())
    archive = tmp_path / "generated.jar"
    with zipfile.ZipFile(archive, "w") as jar:
        jar.write(output, output.relative_to(classes))
    return classes, archive


JAVA_SOURCE = """
package sample;

import java.io.IOException;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.util.List;

@Retention(RetentionPolicy.RUNTIME)
@interface Label {
    String value();
}

@Deprecated
public class Widget implements AutoCloseable {
    public static final int ANSWER = 42;
    public List<String> names;

    public Widget(String title) {}

    public String render(@Label("count") int count, long total)
            throws IOException {
        return Integer.toString(count) + total;
    }

    public <T extends CharSequence> T identity(T value) {
        return value;
    }

    @Override
    public void close() {}
}
"""


@pytest.fixture
def compiled_java(tmp_path):
    javac = shutil.which("javac")
    if javac is None:
        pytest.skip("javac is not installed")
    source = tmp_path / "src" / "sample" / "Widget.java"
    source.parent.mkdir(parents=True)
    source.write_text(JAVA_SOURCE)
    classes = tmp_path / "classes"
    classes.mkdir()
    subprocess.run(
        [javac, "-g", "-parameters", "-d", str(classes), str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    archive = tmp_path / "sample.jar"
    with zipfile.ZipFile(archive, "w") as output:
        for class_file in classes.rglob("*.class"):
            output.write(class_file, class_file.relative_to(classes))
    return classes, archive


def test_reads_class_declarations_from_directory(compiled_java):
    classes, _ = compiled_java

    with JVMClasspath(classes) as classpath:
        widget = classpath.require_class("sample.Widget")

    assert widget.name == "sample/Widget"
    assert widget.super_name == "java/lang/Object"
    assert widget.interfaces == ("java/lang/AutoCloseable",)
    assert [annotation.descriptor for annotation in widget.annotations] == [
        "Ljava/lang/Deprecated;"
    ]

    answer = widget.declared_field("ANSWER")
    assert answer is not None
    assert answer.descriptor == "I"
    assert answer.constant == 42
    names = widget.declared_field("names")
    assert names is not None
    assert names.signature == "Ljava/util/List<Ljava/lang/String;>;"

    constructor = widget.declared_methods("<init>")[0]
    assert [(value.name, value.descriptor) for value in constructor.parameters] == [
        ("title", "Ljava/lang/String;")
    ]
    render = widget.declared_methods("render")[0]
    assert render.return_descriptor == "Ljava/lang/String;"
    assert render.exceptions == ("java/io/IOException",)
    assert [(value.name, value.descriptor) for value in render.parameters] == [
        ("count", "I"),
        ("total", "J"),
    ]
    assert render.parameters[0].annotations == (
        render.parameters[0].annotations[0],
    )
    label = render.parameters[0].annotations[0]
    assert label.descriptor == "Lsample/Label;"
    assert label.values == (("value", "count"),)
    identity = widget.declared_methods("identity")[0]
    assert identity.signature == "<T::Ljava/lang/CharSequence;>(TT;)TT;"


def test_reads_and_caches_classes_from_archives(compiled_java):
    _, archive = compiled_java

    with JVMClasspath(archive) as classpath:
        first = classpath.require_class("sample/Widget")
        second = classpath.require_class("sample/Widget.class")
        missing = classpath.find_class("sample/Missing")

    assert first is second
    assert missing is None


def test_reads_generated_classes_without_a_java_compiler(generated_class):
    classes, archive = generated_class

    with JVMClasspath(classes, archive) as classpath:
        value = classpath.require_class("sample.Generated")

    assert value.name == "sample/Generated"
    assert value.interfaces == ("java/lang/Runnable",)
    assert value.annotations[0].descriptor == "Lorg/junit/runner/RunWith;"
    assert value.annotations[0].values == (
        ("value", "Lsample/GeneratedRunner;"),
    )
    title = value.declared_field("title")
    assert title.descriptor == "Ljava/lang/String;"
    assert title.type_annotations[0].descriptor == (
        "Lorg/jspecify/annotations/Nullable;"
    )
    assert title.type_annotations[0].path == ()
    method = value.declared_methods("run")[0]
    assert method.return_descriptor == "V"
    assert method.annotations[0].descriptor == "Lorg/junit/Test;"
    optional = value.declared_methods("optional")[0]
    assert optional.type_annotations[0].descriptor.endswith("/Nullable;")
    assert optional.parameters[0].type_annotations == optional.type_annotations


def test_classpath_order_is_deterministic(compiled_java, tmp_path):
    classes, archive = compiled_java
    empty = tmp_path / "empty"
    empty.mkdir()

    with JVMClasspath(empty, archive, classes) as classpath:
        assert classpath.require_class("sample.Widget").name == "sample/Widget"


def test_rejects_invalid_class_files():
    with pytest.raises(JVMClassFormatError, match="magic"):
        read_jvm_class(b"not a class")


def test_android_api_combines_classes_with_availability(generated_class, tmp_path):
    _, archive = generated_class
    platform = tmp_path / "android-35"
    platform.mkdir()
    shutil.copyfile(archive, platform / "android.jar")
    data = platform / "data"
    data.mkdir()
    (data / "api-versions.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<api version="3">
  <class name="sample/Generated" since="3">
    <method name="run()V" deprecated="30"/>
    <field name="title" since="7" removed="34"/>
  </class>
</api>
"""
    )

    with AndroidAPI(platform, 35) as api:
        value = api.require_class("sample.Generated")
        method = value.declared_methods("run")[0]
        field = value.declared_field("title")

        assert api.class_availability(value) == AndroidAvailability(3)
        assert api.method_availability(value, method) == AndroidAvailability(
            3,
            deprecated=30,
        )
        assert api.field_availability(value, field) == AndroidAvailability(
            7,
            removed=34,
        )
        assert api.field_availability(value, field).available_at(33)
        assert not api.field_availability(value, field).available_at(34)


def test_android_binding_generation_enforces_sdk_availability(
    generated_class,
    tmp_path,
):
    _, archive = generated_class
    platform = tmp_path / "android-35"
    platform.mkdir()
    shutil.copyfile(archive, platform / "android.jar")
    data = platform / "data"
    data.mkdir()
    (data / "api-versions.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<api version="3">
  <class name="sample/Generated" since="3">
    <method name="run()V"/>
    <field name="title" since="7" removed="34"/>
  </class>
</api>
"""
    )
    run = JVMClassBinding(
        "sample.Generated",
        methods=(JVMMethodBinding("run", "()V"),),
    )
    title = JVMClassBinding(
        "sample.Generated",
        fields=(JVMFieldBinding("title", "Ljava/lang/String;"),),
    )

    with AndroidAPI(platform, 35) as api:
        assert '@jvm.native("sample/Generated")' in api.render_bindings(
            (run,),
            min_sdk=3,
        )
        with pytest.raises(JVMBindingError, match="requires API 3"):
            api.render_bindings((run,), min_sdk=2)
        with pytest.raises(JVMBindingError, match="unavailable at compile SDK 35"):
            api.render_bindings((title,), min_sdk=21)


def test_android_nullability_reads_common_jvm_annotations():
    nullable = JVMAnnotation("Landroid/annotation/Nullable;")
    non_null = JVMAnnotation("Landroidx/annotation/NonNull;")
    value = JVMMethod(
        "value",
        "(Ljava/lang/String;)Ljava/lang/String;",
        0x0001,
        (JVMParameter("Ljava/lang/String;", annotations=(non_null,)),),
        "Ljava/lang/String;",
        annotations=(nullable,),
    )

    assert AndroidAPI.method_return_nullability(value) is AndroidNullability.NULLABLE
    assert AndroidAPI.parameter_nullability(value, 0) is AndroidNullability.NON_NULL
    with pytest.raises(IndexError, match="out of range"):
        AndroidAPI.parameter_nullability(value, 1)


def test_android_bindings_infer_type_use_nullability_with_overrides(
    generated_class,
    tmp_path,
):
    _, archive = generated_class
    platform = tmp_path / "android-35"
    platform.mkdir()
    shutil.copyfile(archive, platform / "android.jar")
    external_classes = (
        JVMExternalClass("java/lang/Object", "builtins", "object"),
    )
    inferred = JVMClassBinding(
        "sample.Generated",
        methods=(
            JVMMethodBinding(
                "optional",
                "(Ljava/lang/String;)Ljava/lang/String;",
            ),
        ),
        fields=(
            JVMFieldBinding("title", "Ljava/lang/String;"),
        ),
    )
    overridden = JVMClassBinding(
        "sample.Generated",
        methods=(
            JVMMethodBinding(
                "optional",
                "(Ljava/lang/String;)Ljava/lang/String;",
                nullable_return=False,
                nullable_parameters=(),
            ),
        ),
        fields=(
            JVMFieldBinding("title", "Ljava/lang/String;", nullable=False),
        ),
    )

    with AndroidAPI(platform, 35) as api:
        inferred_source = api.render_bindings(
            (inferred,),
            external_classes=external_classes,
        )
        overridden_source = api.render_bindings(
            (overridden,),
            external_classes=external_classes,
        )

    assert "title: Annotated[str | None, jvm.field()]" in inferred_source
    assert "argument_1: str | None" in inferred_source
    assert ") -> str | None:" in inferred_source
    assert "title: Annotated[str, jvm.field()]" in overridden_source
    assert "argument_1: str" in overridden_source
    assert ") -> str:" in overridden_source


def test_reads_installed_android_framework_metadata():
    try:
        api = AndroidAPI.from_sdk(35)
    except (FileNotFoundError, RuntimeError):
        pytest.skip("Android API 35 is not installed")

    with api:
        text_view = api.require_class("android.widget.TextView")
        overloads = text_view.declared_methods("setText")
        character_array = next(
            method for method in overloads if method.descriptor == "([CII)V"
        )

        assert text_view.super_name == "android/view/View"
        assert len(overloads) == 5
        assert [parameter.name for parameter in character_array.parameters] == [
            "text",
            "start",
            "len",
        ]
        assert [
            annotation.descriptor
            for annotation in character_array.parameters[0].annotations
        ] == ["Landroid/annotation/NonNull;"]
        assert (
            api.parameter_nullability(character_array, 0)
            is AndroidNullability.NON_NULL
        )
        activity = api.require_class("android.app.Activity")
        on_create = next(
            method
            for method in activity.declared_methods("onCreate")
            if method.descriptor == "(Landroid/os/Bundle;)V"
        )
        assert (
            api.parameter_nullability(on_create, 0)
            is AndroidNullability.NULLABLE
        )
        assert api.class_availability(text_view) == AndroidAvailability(1)


def test_direct_notes_framework_methods_match_android_api_35():
    try:
        api = AndroidAPI.from_sdk(35)
    except (FileNotFoundError, RuntimeError):
        pytest.skip("Android API 35 is not installed")

    expected = {
        "android.view.View": {
            ("getContext", "()Landroid/content/Context;"),
            ("setBackground", "(Landroid/graphics/drawable/Drawable;)V"),
            ("setElevation", "(F)V"),
        },
        "android.view.ViewGroup$MarginLayoutParams": {
            ("<init>", "(II)V"),
            ("setMargins", "(IIII)V"),
        },
        "android.widget.LinearLayout$LayoutParams": {
            ("<init>", "(IIF)V"),
        },
        "android.graphics.drawable.GradientDrawable": {
            ("<init>", "()V"),
            ("setColor", "(I)V"),
            ("setCornerRadius", "(F)V"),
            ("setStroke", "(II)V"),
        },
    }
    with api:
        for owner, methods in expected.items():
            android_class = api.require_class(owner)
            actual = {
                (method.name, method.descriptor)
                for method in android_class.methods
            }
            assert methods <= actual


def test_application_content_and_storage_methods_match_android_api_35():
    try:
        api = AndroidAPI.from_sdk(35)
    except (FileNotFoundError, RuntimeError):
        pytest.skip("Android API 35 is not installed")

    expected = {
        "android.content.Context": {
            ("getPackageName", "()Ljava/lang/String;"),
            ("getContentResolver", "()Landroid/content/ContentResolver;"),
        },
        "android.content.Intent": {
            ("<init>", "()V"),
            ("setAction", "(Ljava/lang/String;)Landroid/content/Intent;"),
            (
                "setClassName",
                "(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;",
            ),
            ("getData", "()Landroid/net/Uri;"),
            ("getIntArrayExtra", "(Ljava/lang/String;)[I"),
        },
        "android.content.ContentResolver": {
            ("takePersistableUriPermission", "(Landroid/net/Uri;I)V"),
        },
        "android.view.View": {
            ("clearFocus", "()V"),
            ("isEnabled", "()Z"),
            ("isFocused", "()Z"),
            ("requestFocus", "()Z"),
            ("setAlpha", "(F)V"),
            ("setEnabled", "(Z)V"),
            ("setFocusableInTouchMode", "(Z)V"),
            ("setMinimumHeight", "(I)V"),
            ("setMinimumWidth", "(I)V"),
        },
        "android.view.ViewGroup": {
            ("addView", "(Landroid/view/View;I)V"),
            ("removeAllViews", "()V"),
            ("removeView", "(Landroid/view/View;)V"),
            ("removeViewAt", "(I)V"),
        },
        "android.widget.TextView": {
            ("addTextChangedListener", "(Landroid/text/TextWatcher;)V"),
            ("getSelectionEnd", "()I"),
            ("getSelectionStart", "()I"),
            ("getText", "()Ljava/lang/CharSequence;"),
            ("removeTextChangedListener", "(Landroid/text/TextWatcher;)V"),
            ("setHint", "(Ljava/lang/CharSequence;)V"),
            ("setInputType", "(I)V"),
            ("setSingleLine", "(Z)V"),
        },
        "android.app.Activity": {
            ("startActivity", "(Landroid/content/Intent;)V"),
            ("startActivityForResult", "(Landroid/content/Intent;I)V"),
            ("onActivityResult", "(IILandroid/content/Intent;)V"),
        },
        "android.os.BaseBundle": {
            ("getInt", "(Ljava/lang/String;I)I"),
            ("putInt", "(Ljava/lang/String;I)V"),
            ("getString", "(Ljava/lang/String;)Ljava/lang/String;"),
            ("putString", "(Ljava/lang/String;Ljava/lang/String;)V"),
        },
    }
    with api:
        for owner, methods in expected.items():
            actual = {
                (method.name, method.descriptor)
                for method in api.require_class(owner).methods
            }
            assert methods <= actual
