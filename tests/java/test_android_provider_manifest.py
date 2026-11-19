from textwrap import dedent
from types import SimpleNamespace

import pytest

from pyjs.java import transpile_jvm
from pyjs.tooling.android_jvm import AndroidJVMApplication, AndroidJVMBuilder


def provider_source(*, retained=True, initialized=False):
    initializer = "def __init__(self):\n        self.value = 1" if initialized else "pass"
    return dedent('''\
        from pyjs.android import Activity
        from pyjs.android.files import FileProvider
        class Screen(Activity):
            pass
        class BaseProvider(FileProvider):
    ''') + "    " + initializer + dedent('''
        class SharingProvider(BaseProvider):
            pass
        def main() -> int:
            screen = Screen()
    ''') + ("    provider = SharingProvider()\n" if retained else "") + "    return 0\n"


def provider_manifest(tmp_path, name):
    manifest = tmp_path / "merged.xml"
    manifest.write_text(
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
        f'<application><provider android:name="{name}" /></application></manifest>'
    )
    return manifest


def application(tmp_path):
    return AndroidJVMApplication(tmp_path / "app.py", "provider_app",
                                 "org.pyjs.files", "Screen", "Files", 35)


@pytest.mark.parametrize("name", [
    ".PyjsAndroid$SharingProvider", "PyjsAndroid$SharingProvider",
    "org.pyjs.files.PyjsAndroid$SharingProvider",
])
@pytest.mark.parametrize("retained", [True, False])
def test_generated_provider_names_require_a_reachable_class(tmp_path, name, retained):
    app = application(tmp_path)
    compiled = transpile_jvm(provider_source(retained=retained), class_name=app.jvm_class)
    manifest = provider_manifest(tmp_path, name)
    if retained:
        AndroidJVMBuilder._validate_manifest_providers(app, compiled, manifest)
    else:
        with pytest.raises(ValueError, match="provider .* is not reachable from main"):
            AndroidJVMBuilder._validate_manifest_providers(app, compiled, manifest)


def test_provider_rejects_inherited_python_initializer(tmp_path):
    app = application(tmp_path)
    compiled = transpile_jvm(provider_source(initialized=True), class_name=app.jvm_class)
    manifest = provider_manifest(tmp_path, ".PyjsAndroid$SharingProvider")
    with pytest.raises(ValueError, match="without calling Python __init__"):
        AndroidJVMBuilder._validate_manifest_providers(app, compiled, manifest)


def test_external_library_provider_does_not_require_a_generated_class(tmp_path):
    app = application(tmp_path)
    compiled = transpile_jvm(provider_source(retained=False), class_name=app.jvm_class)
    manifest = provider_manifest(tmp_path, "androidx.core.content.FileProvider")
    AndroidJVMBuilder._validate_manifest_providers(app, compiled, manifest)


@pytest.mark.parametrize("initialized", [False, True])
def test_packaging_validates_merged_providers_before_linking(tmp_path, monkeypatch, initialized):
    app = application(tmp_path)
    app.source.write_text(provider_source(retained=initialized, initialized=initialized))
    manifest = provider_manifest(tmp_path, ".PyjsAndroid$SharingProvider")
    key = tmp_path / "debug.keystore"
    key.touch()
    builder = AndroidJVMBuilder(SimpleNamespace(java_home=tmp_path, runner=None))
    monkeypatch.setattr(builder, "_platform", lambda api: tmp_path / "android.jar")
    monkeypatch.setattr("pyjs.tooling.android_manifest.merge_android_manifests",
                        lambda *args, **kwargs: manifest)

    def unexpected_link(*args):
        pytest.fail("Invalid provider reached resource linking")

    monkeypatch.setattr(builder, "_link_resources", unexpected_link)
    message = "without calling Python __init__" if initialized else "not reachable from main"
    with pytest.raises(ValueError, match=message):
        builder.build(app, tmp_path / "apk", keystore=key)
