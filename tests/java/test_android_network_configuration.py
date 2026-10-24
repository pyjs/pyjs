import subprocess
from xml.etree import ElementTree

import pytest

from pyjs.tooling.android import AndroidSDK
from pyjs.tooling.android_jvm import (
    AndroidJVMApplication,
    AndroidJVMBuilder,
    AndroidResourceLinker,
)
from tests.java.test_android import android_sdk

ANDROID = "{http://schemas.android.com/apk/res/android}"


def application(tmp_path, **options):
    return AndroidJVMApplication(
        tmp_path / "app.py", "app", "org.pyjs.network", "Screen", "Network", 35, **options,
    )


def test_manifest_does_not_request_network_access_by_default(tmp_path):
    manifest = ElementTree.fromstring(AndroidJVMBuilder._manifest(application(tmp_path), 35))
    assert manifest.findall("uses-permission") == []
    owner = manifest.find("application")
    assert owner.get(ANDROID + "usesCleartextTraffic") == "false"
    assert owner.get(ANDROID + "networkSecurityConfig") is None


def test_manifest_keeps_explicit_network_policy_and_unique_permissions(tmp_path):
    app = application(tmp_path, permissions=(
        "android.permission.INTERNET", "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.INTERNET",
    ), network_security_config="@xml/local_network", application_class="Owner")
    manifest = ElementTree.fromstring(AndroidJVMBuilder._manifest(app, 35))
    assert [value.get(ANDROID + "name") for value in manifest.findall("uses-permission")] == [
        "android.permission.INTERNET", "android.permission.ACCESS_NETWORK_STATE",
    ]
    owner = manifest.find("application")
    assert owner.get(ANDROID + "name") == "org.pyjs.network.PyjsAndroid$Owner"
    assert owner.get(ANDROID + "usesCleartextTraffic") == "false"
    assert owner.get(ANDROID + "networkSecurityConfig") == "@xml/local_network"


@pytest.mark.parametrize("permission", ["", "INTERNET", "android.permission.BAD NAME", 'x.y"/>', "x.y\n"])
def test_invalid_permission_names_fail_before_sdk_work(tmp_path, permission):
    with pytest.raises(ValueError, match="invalid Android permission name"):
        application(tmp_path, permissions=(permission,))


@pytest.mark.parametrize("resource", ["", "config.xml", "@raw/config", "@xml/../config", '@xml/config"', "@xml/config\n"])
def test_invalid_network_policy_references_fail_before_sdk_work(tmp_path, resource):
    with pytest.raises(ValueError, match="must reference an @xml/resource"):
        application(tmp_path, network_security_config=resource)


def test_network_policy_requires_a_supported_compile_sdk(tmp_path):
    with pytest.raises(ValueError, match="requires compile SDK 24 or newer"):
        AndroidJVMApplication(
            tmp_path / "app.py", "app", "org.pyjs.network", "Screen", "Network", 23,
            network_security_config="@xml/local_network",
        )


def test_sdk_links_the_policy_resource_and_permission(tmp_path):
    platform, d8 = android_sdk()
    resources = tmp_path / "res"
    xml = resources / "xml"
    xml.mkdir(parents=True)
    (xml / "local_network.xml").write_text('''<network-security-config>
    <base-config cleartextTrafficPermitted="false" />
    <domain-config cleartextTrafficPermitted="true">
        <domain>10.0.2.2</domain>
    </domain-config>
</network-security-config>''')
    app = application(tmp_path, permissions=("android.permission.INTERNET",),
                      network_security_config="@xml/local_network", resources=(resources,))
    manifest = tmp_path / "AndroidManifest.xml"
    manifest.write_text(AndroidJVMBuilder._manifest(app, 35))
    package = tmp_path / "resources.apk"
    AndroidResourceLinker(AndroidSDK()).link(
        platform, manifest, package, tmp_path, min_sdk=21, target_sdk=35, resources=app.resources,
    )
    def dump(path):
        return subprocess.run(
            [str(d8.with_name("aapt2")), "dump", "xmltree", str(package), "--file", path],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout
    linked = dump("AndroidManifest.xml")
    assert "android.permission.INTERNET" in linked
    assert "networkSecurityConfig" in linked
    assert "@0x7f" in linked
    policy = dump("res/xml/local_network.xml")
    assert "10.0.2.2" in policy
    assert "domain-config" in policy
