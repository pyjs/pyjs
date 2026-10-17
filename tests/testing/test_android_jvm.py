from pyjs.java import read_jvm_class
from pyjs.testing.android_jvm import AndroidJVMSuiteBuilder
from pyjs.testing.builder import SelectedTest


def test_android_jvm_suite_compiles_selected_tests(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_notes.py").write_text(
        """\
from pyjs.android.testing import by_text


def test_title() -> None:
    by_text("Trip").assert_displayed()
"""
    )
    builder = AndroidJVMSuiteBuilder(project, tmp_path / "cache")

    compilation = builder.build(
        [SelectedTest("test_notes.py::test_title", "test_notes", "test_title")],
        "run-1",
    )

    assert len(compilation.tests) == 1
    compiled = compilation.tests[0]
    assert compiled.nodeid == "test_notes.py::test_title"
    assert "org/pyjs/testing/PyjsView" in compilation.classes
    test_class = read_jvm_class(compilation.classes[compiled.class_name])
    method = test_class.declared_methods(compiled.method_name)[0]
    assert method.annotations[0].descriptor == "Lorg/junit/Test;"
    assert (tmp_path / "cache/android-jvm/run-1/AndroidManifest.xml").read_text() == (
        """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="org.pyjs.testing">
  <application>

  </application>
</manifest>
"""
    )


def test_android_jvm_suite_retains_native_activity_callbacks(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_notes.py").write_text(
        """\
from pyjs.android import Activity, Bundle, TextView
from pyjs.android.testing import by_text, launch, press_back


class NotesActivity(Activity):
    def onCreate(self, state: Bundle) -> None:
        super().onCreate(state)
        title = TextView(self)
        title.setText("Notes")
        self.setContentView(title)


def test_title() -> None:
    launch(NotesActivity)
    by_text("Notes").assert_displayed()
    press_back()
"""
    )
    builder = AndroidJVMSuiteBuilder(project, tmp_path / "cache")

    compilation = builder.build(
        [SelectedTest("test_notes.py::test_title", "test_notes", "test_title")],
        "run-1",
    )

    activity_name = (
        "org/pyjs/testing/PyjsTests$module$test_notes$NotesActivity"
    )
    activity = read_jvm_class(compilation.classes[activity_name])
    assert activity.declared_methods("onCreate")[0].descriptor == (
        "(Landroid/os/Bundle;)V"
    )
    content = compilation.classes[activity_name]
    assert b"android/view/View" in content
    assert b"org/pyjs/testing/PyjsView" not in content
    manifest = (
        tmp_path / "cache/android-jvm/run-1/AndroidManifest.xml"
    ).read_text()
    assert activity_name.replace("/", ".") in manifest


def test_android_device_suite_does_not_emit_robolectric_annotations(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_notes.py").write_text(
        """\
def test_title() -> None:
    assert True
"""
    )
    compilation = AndroidJVMSuiteBuilder(project, tmp_path / "cache").build(
        [SelectedTest("test_notes.py::test_title", "test_notes", "test_title")],
        "run-1",
        robolectric=False,
    )

    test_class = read_jvm_class(compilation.classes[compilation.tests[0].class_name])
    assert [value.descriptor for value in test_class.annotations] == [
        "Lorg/junit/runner/RunWith;"
    ]
    assert "org/pyjs/testing/PyjsDevice" in compilation.classes


def test_android_device_suite_compiles_uiautomator_default_wait_and_drag(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_system.py").write_text(
        """\
from pyjs.android.uiautomator import find_text


def test_permission() -> None:
    source = find_text("Allow")
    source.click()
    source.drag_to(find_text("Settings"))
    source.drag_to(find_text("Settings"), 800, -32, 48)
"""
    )

    compilation = AndroidJVMSuiteBuilder(project, tmp_path / "cache").build(
        [
            SelectedTest(
                "test_system.py::test_permission",
                "test_system",
                "test_permission",
            )
        ],
        "run-1",
        robolectric=False,
    )

    assert "org/pyjs/testing/PyjsDeviceElement" in compilation.classes
