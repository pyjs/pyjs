import subprocess
from textwrap import dedent

import pytest

from pyjs.java import read_jvm_class, transpile_jvm
from pyjs.testing.android_jvm import AndroidJVMSuiteBuilder
from pyjs.testing.builder import SelectedTest
from pyjs.tooling.android_jvm import (
    AndroidJVMApplication,
    AndroidJVMBuilder,
    validate_android_entrypoint,
)
from tests.java.test_android import android_sdk


@pytest.mark.parametrize("kind", ["Activity", "Application"])
@pytest.mark.parametrize("levels", [0, 1, 2])
@pytest.mark.parametrize("construct", [True, False])
def test_framework_entrypoints_reject_resolved_python_initializers(
    kind, levels, construct,
):
    source = dedent(f'''
        from typing import cast
        from pyjs.android import {kind}
        class Root({kind}):
            def __init__(self):
                self.pending = 42
    ''')
    owner = "Root"
    for index in range(levels):
        child = f"Child{index}"
        source += f"\nclass {child}({owner}):\n    pass\n"
        owner = child
    expression = f"{owner}()" if construct else f"cast({owner}, {kind}())"
    source += f"\ndef main() -> int:\n    value = {expression}\n    return 0\n"
    compilation = transpile_jvm(source)
    name = f"PyjsProgram${owner}"
    assert name in compilation.python_initialized_classes
    if not construct:
        root = read_jvm_class(compilation.classes["PyjsProgram$Root"])
        assert root.declared_methods("pyjs_init") == ()
    with pytest.raises(ValueError, match="including inherited state"):
        validate_android_entrypoint(compilation, name, kind)


def test_application_inherited_on_create_is_a_valid_entrypoint():
    compilation = transpile_jvm('''
from pyjs.android import Application
class Base(Application):
    def onCreate(self) -> None:
        super().onCreate()
        self.pending = 42
class Owner(Base):
    pass
def main() -> int:
    owner = Owner()
    return 0
''')
    validate_android_entrypoint(compilation, "PyjsProgram$Owner", "Application")
    assert compilation.python_initialized_classes == ()
    base = read_jvm_class(compilation.classes["PyjsProgram$Base"])
    assert base.declared_methods("onCreate")[0].descriptor == "()V"


def test_application_manifest_names_the_explicit_owner(tmp_path):
    app = AndroidJVMApplication(
        tmp_path / "app.py", "app", "org.pyjs.notes", "Screen", "Notes", 35,
        application_class="Owner",
    )
    manifest = AndroidJVMBuilder._manifest(app, 35)
    assert '<application android:name="org.pyjs.notes.PyjsAndroid$Owner"' in manifest
    assert 'android:name="org.pyjs.notes.PyjsAndroid$Screen"' in manifest


@pytest.mark.parametrize("name", ["", "bad-name", "package.Owner"])
def test_application_owner_name_must_be_a_source_class(tmp_path, name):
    with pytest.raises(ValueError, match="invalid Android application class"):
        AndroidJVMApplication(
            tmp_path / "app.py", "app", "org.pyjs.notes", "Screen", "Notes", 35,
            application_class=name,
        )


@pytest.mark.parametrize("kind", ["Activity", "Application"])
def test_package_rejects_inherited_initializer_before_sdk_work(tmp_path, kind):
    source = tmp_path / "owner.py"
    source.write_text(dedent(f'''
        from pyjs.android import Activity, Application
        class Base({kind}):
            def __init__(self):
                self.pending = 42
        class Owner(Base):
            pass
        class Screen(Activity):
            pass
        def main() -> int:
            owner = Owner()
            screen = Screen()
            return 0
    '''))
    app = AndroidJVMApplication(
        source, "_android_package_owner", "org.pyjs.notes",
        "Owner" if kind == "Activity" else "Screen", "Notes", 35,
        application_class="Owner" if kind == "Application" else None,
    )
    builder = AndroidJVMBuilder.__new__(AndroidJVMBuilder)
    with pytest.raises(ValueError, match="including inherited state"):
        builder.build(app, tmp_path / "apk")


def test_application_owner_must_reach_the_native_application_base():
    compilation = transpile_jvm('''
class Owner:
    pass
def main() -> int:
    owner = Owner()
    return 0
''')
    with pytest.raises(ValueError, match="must extend Application"):
        validate_android_entrypoint(compilation, "PyjsProgram$Owner", "Application")
    with pytest.raises(ValueError, match="not reachable"):
        validate_android_entrypoint(compilation, "PyjsProgram$Missing", "Application")


def test_test_manifest_selects_the_leaf_application_and_retains_callbacks(tmp_path):
    compilation = transpile_jvm('''
from pyjs.android import Application
class Base(Application):
    def onCreate(self) -> None:
        super().onCreate()
class Owner(Base):
    pass
def main() -> int:
    owner = Owner()
    return 0
''')
    path = tmp_path / "AndroidManifest.xml"
    AndroidJVMSuiteBuilder.write_manifest(compilation, path)
    assert '<application android:name="PyjsProgram$Owner">' in path.read_text()
    base = read_jvm_class(compilation.classes["PyjsProgram$Base"])
    assert base.declared_methods("onCreate")[0].descriptor == "()V"


def test_test_manifest_rejects_ambiguous_application_owners(tmp_path):
    compilation = transpile_jvm('''
from pyjs.android import Application
class First(Application):
    pass
class Second(Application):
    pass
def main() -> int:
    first = First()
    second = Second()
    return 0
''')
    with pytest.raises(ValueError, match="at most one Application"):
        AndroidJVMSuiteBuilder.write_manifest(
            compilation, tmp_path / "AndroidManifest.xml",
        )


@pytest.mark.parametrize("kind", ["Activity", "Application"])
def test_test_manifest_rejects_initializers_from_imported_bases(tmp_path, kind):
    project = tmp_path / "project"
    project.mkdir()
    (project / "owner.py").write_text(dedent(f'''
        from pyjs.android import {kind}
        class Base({kind}):
            def __init__(self):
                self.pending = 42
        class Child(Base):
            pass
    '''))
    (project / "test_owner.py").write_text(dedent('''
        from owner import Child
        def test_owner() -> None:
            child = Child()
            assert child.pending == 42
    '''))
    builder = AndroidJVMSuiteBuilder(project, tmp_path / "cache")
    with pytest.raises(ValueError, match="including inherited state"):
        builder.build(
            [SelectedTest("test_owner.py::test_owner", "test_owner", "test_owner")],
            "owner",
        )


def test_application_and_dispatch_bindings_compile_to_android_dex(tmp_path):
    android_jar, d8 = android_sdk()
    compilation = transpile_jvm('''
from pyjs.android import Activity, Application, Bundle
from pyjs.android.dispatch import Handler, main_looper
from pyjs.java.concurrent import Runnable, Thread
class Task(Runnable):
    def run(self) -> None:
        pass
class Owner(Application):
    def onCreate(self) -> None:
        super().onCreate()
        task = Task()
        worker = Thread(task)
        worker.start()
        worker.join()
        Handler(main_looper()).post(task)
class Screen(Activity):
    def onCreate(self, state: Bundle) -> None:
        super().onCreate(state)
        context = self.getApplicationContext()
        editor = context.get_shared_preferences("snapshot", 0).edit()
        editor.put_string("value", "saved")
        editor.commit()
    def onDestroy(self) -> None:
        super().onDestroy()
def main() -> int:
    owner = Owner()
    screen = Screen()
    return 0
''')
    owner = read_jvm_class(compilation.classes["PyjsProgram$Owner"])
    screen = read_jvm_class(compilation.classes["PyjsProgram$Screen"])
    assert owner.declared_methods("onCreate")[0].descriptor == "()V"
    assert screen.declared_methods("onDestroy")[0].descriptor == "()V"
    classes = tmp_path / "classes"
    compilation.write(classes)
    dex = tmp_path / "dex"
    dex.mkdir()
    result = subprocess.run(
        [str(d8), "-JXmx256m", "--lib", str(android_jar), "--min-api", "21",
         "--output", str(dex), *(str(path) for path in classes.rglob("*.class"))],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert (dex / "classes.dex").is_file()
