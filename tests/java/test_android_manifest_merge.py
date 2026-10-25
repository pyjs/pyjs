"""Exercise the actual Android merger, not an imitation of its XML rules."""

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pyjs.tooling.android import AndroidSDK
from pyjs.tooling.android_manifest import merge_android_manifests

ANDROID = "{http://schemas.android.com/apk/res/android}"


def manifest(content, *, package="org.pyjs.sample", minimum=24):
    return f'''<manifest xmlns:android="http://schemas.android.com/apk/res/android"
        xmlns:tools="http://schemas.android.com/tools" package="{package}">
        <uses-sdk android:minSdkVersion="{minimum}" android:targetSdkVersion="35" />
        {content}</manifest>'''


@pytest.fixture
def merge(tmp_path):
    try:
        java_home = AndroidSDK.find_java_home()
    except RuntimeError as error:
        pytest.skip(str(error))

    def execute(main, libraries=(), overlay=None):
        source = tmp_path / "main.xml"
        source.write_text(main)
        aars = []
        for index, content in enumerate(libraries):
            path = tmp_path / f"library {index}.aar"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("AndroidManifest.xml", content)
            aars.append(path)
        overlays = ()
        if overlay is not None:
            path = tmp_path / "override.xml"
            path.write_text(overlay)
            overlays = (path,)
        result = merge_android_manifests(
            source, tmp_path / "merged.xml", aars=tuple(aars), overlays=overlays,
            java_home=java_home, cache=Path.home() / ".cache/pyjs/android-manifest",
        )
        return ET.fromstring(result.read_text())
    return execute


def test_library_components_metadata_and_application_placeholders(merge):
    root = merge(manifest('<application android:label="App" />'), [manifest('''
        <uses-permission android:name="android.permission.INTERNET" />
        <application>
          <activity android:name=".Chooser" android:exported="false" />
          <service android:name=".Provider" android:exported="false">
            <meta-data android:name="provider" android:value="org.library.Provider" />
          </service>
          <provider android:name=".State" android:authorities="${applicationId}.state"
              android:exported="false" />
        </application>''', package="org.library")])
    assert root.find("uses-permission").get(ANDROID + "name") == "android.permission.INTERNET"
    owner = root.find("application")
    assert owner.get(ANDROID + "label") == "App"
    assert owner.find("activity").get(ANDROID + "name") == "org.library.Chooser"
    assert owner.find("service/meta-data").get(ANDROID + "value") == "org.library.Provider"
    assert owner.find("provider").get(ANDROID + "authorities") == "org.pyjs.sample.state"


def test_incompatible_minimum_sdk_is_not_silently_raised(merge):
    with pytest.raises(RuntimeError, match="minSdkVersion 24 cannot be smaller than version 26"):
        merge(manifest("<application />"), [manifest("<application />", minimum=26)])


def test_conflicts_require_explicit_overlay_resolution(merge):
    main = manifest('<application android:label="App" />')
    library = manifest('<application android:label="Library" />', package="org.library")
    with pytest.raises(RuntimeError, match="application@label"):
        merge(main, [library])
    root = merge(main, [library], manifest('''
        <application android:label="Chosen" tools:replace="android:label" />'''))
    assert root.find("application").get(ANDROID + "label") == "Chosen"
    assert all(not key.startswith("{http://schemas.android.com/tools}")
               for element in root.iter() for key in element.attrib)


def test_unresolved_library_placeholders_fail_the_build(merge):
    with pytest.raises(RuntimeError, match="placeholder substitution"):
        merge(manifest("<application />"), [manifest('''<application>
            <meta-data android:name="key" android:value="${unconfigured}" />
            </application>''', package="org.library")])


def test_no_libraries_needs_no_java_or_download(tmp_path):
    main = tmp_path / "main.xml"
    main.write_text(manifest("<application />"))
    assert merge_android_manifests(main, tmp_path / "merged.xml",
        java_home=tmp_path / "missing", cache=tmp_path / "cache") == main
    assert not (tmp_path / "cache").exists()
