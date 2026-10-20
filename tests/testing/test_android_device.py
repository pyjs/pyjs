import pytest

from pyjs.java import JVMCompilation, JVMCompiledTest
from pyjs.testing.android_device import (
    RUNNER,
    TARGET_PACKAGE,
    AndroidDeviceTestBuilder,
    AndroidDeviceTestRunner,
)
from pyjs.testing.android_runtime import AndroidTestResult


def test_device_runner_maps_instrumentation_status_to_pytest_nodeids():
    compilation = JVMCompilation(
        "Tests",
        {},
        (
            JVMCompiledTest("test_notes.py::test_save", "Tests$Suite", "test_save"),
            JVMCompiledTest("test_notes.py::test_open", "Tests$Suite", "test_open"),
        ),
    )
    output = """\
INSTRUMENTATION_STATUS: class=Tests$Suite
INSTRUMENTATION_STATUS: current=1
INSTRUMENTATION_STATUS: test=test_save
INSTRUMENTATION_STATUS_CODE: 1
INSTRUMENTATION_STATUS: class=Tests$Suite
INSTRUMENTATION_STATUS: current=1
INSTRUMENTATION_STATUS: test=test_save
INSTRUMENTATION_STATUS_CODE: 0
INSTRUMENTATION_STATUS: class=Tests$Suite
INSTRUMENTATION_STATUS: current=2
INSTRUMENTATION_STATUS: test=test_open
INSTRUMENTATION_STATUS_CODE: 1
INSTRUMENTATION_STATUS: class=Tests$Suite
INSTRUMENTATION_STATUS: current=2
INSTRUMENTATION_STATUS: test=test_open
INSTRUMENTATION_STATUS: stack=java.lang.AssertionError: missing note
    at Tests.open(test_notes.py:12)
INSTRUMENTATION_STATUS_CODE: -2
INSTRUMENTATION_CODE: -1
"""

    assert AndroidDeviceTestRunner._results(compilation, output) == {
        "test_notes.py::test_save": AndroidTestResult("passed"),
        "test_notes.py::test_open": AndroidTestResult(
            "failed",
            "java.lang.AssertionError: missing note\n"
            "    at Tests.open(test_notes.py:12)",
        ),
    }


def test_device_manifest_targets_the_empty_test_application():
    builder = AndroidDeviceTestBuilder.__new__(AndroidDeviceTestBuilder)

    manifest = builder._test_manifest()

    assert f'android:name="{RUNNER}"' in manifest
    assert f'android:targetPackage="{TARGET_PACKAGE}"' in manifest


def test_device_packages_split_application_and_test_modules(tmp_path):
    compilation = JVMCompilation(
        "org/pyjs/testing/PyjsTests",
        {
            "org/pyjs/testing/PyjsTests": b"entry",
            "org/pyjs/testing/PyjsTests$Tests": b"junit",
            "org/pyjs/testing/PyjsView": b"bridge",
            "org/pyjs/testing/PyjsTests$module$test_notes": b"test",
            "org/pyjs/testing/PyjsTests$module$notes$NotesActivity": b"app",
        },
        (
            JVMCompiledTest(
                "test_notes.py::test_save",
                "org/pyjs/testing/PyjsTests$Tests",
                "test_save",
            ),
        ),
        test_modules=("test_notes",),
    )

    target = tmp_path / "target"
    tests = tmp_path / "tests"
    AndroidDeviceTestBuilder._write_split_classes(compilation, target, tests)

    assert (
        target
        / "org/pyjs/testing/PyjsTests$module$notes$NotesActivity.class"
    ).read_bytes() == b"app"
    assert (
        tests / "org/pyjs/testing/PyjsTests$module$test_notes.class"
    ).read_bytes() == b"test"
    assert (tests / "org/pyjs/testing/PyjsView.class").read_bytes() == b"bridge"


def test_device_package_rejects_activities_defined_in_test_modules(tmp_path):
    manifest = """\
<manifest>
  <application>
    <activity android:name="org.pyjs.testing.TestActivity" />
  </application>
</manifest>
"""

    with pytest.raises(RuntimeError, match="Move it to an application module"):
        AndroidDeviceTestBuilder._validate_target_activities(
            manifest,
            tmp_path,
        )


def test_device_target_manifest_preserves_application_owner(tmp_path):
    manifest = """\
<manifest package="org.pyjs.testing">
  <application android:name="org.pyjs.testing.App" />
</manifest>
"""
    builder = AndroidDeviceTestBuilder.__new__(AndroidDeviceTestBuilder)
    target = builder._target_manifest(manifest)
    assert f'package="{TARGET_PACKAGE}"' in target
    assert '<application android:debuggable="true" android:name=' in target
    assert 'android:name="org.pyjs.testing.App"' in target
    with pytest.raises(RuntimeError, match="Android application"):
        builder._validate_target_activities(target, tmp_path)
    app = tmp_path / "org/pyjs/testing/App.class"
    app.parent.mkdir(parents=True)
    app.touch()
    builder._validate_target_activities(target, tmp_path)
