"""Compile selected pytest functions into Android-compatible JUnit classes."""

import sys
from dataclasses import replace
from html import escape
from pathlib import Path

from pyjs.java import JVMCompilation, JVMTest, read_jvm_class, transpile_jvm
from pyjs.tooling.android_jvm import validate_android_entrypoint

from .builder import SelectedTest, fresh_project_imports
from .espresso import espresso_android_class, espresso_view_class
from .uiautomator import uiautomator_device_class, uiautomator_element_class

ENTRYPOINT_MODULE = "__pyjs_android_test_entrypoint__"


class AndroidJVMSuiteBuilder:
    def __init__(self, project_root: Path, cache_dir: Path) -> None:
        self.project_root = project_root.resolve()
        self.cache_dir = cache_dir.resolve()

    @property
    def entrypoint_path(self) -> Path:
        return self.cache_dir / f"{ENTRYPOINT_MODULE}.py"

    def build(
        self,
        selected_tests: list[SelectedTest],
        run_id: str,
        *,
        class_name: str = "org/pyjs/testing/PyjsTests",
        api: int = 35,
        robolectric: bool = True,
    ) -> JVMCompilation:
        source = generate_android_entrypoint_source(selected_tests)
        aliases = tuple(
            f"__pyjs_test_{index}" for index in range(len(selected_tests))
        )
        tests = tuple(
            JVMTest(
                selected.nodeid,
                selected.module_name,
                selected.function_name,
            )
            for selected in selected_tests
        )
        module_names = [selected.module_name for selected in selected_tests]
        manifest = self.cache_dir / "android-jvm" / run_id / "AndroidManifest.xml"
        with fresh_project_imports(
            self.project_root,
            self.cache_dir,
            run_id,
            module_names,
        ):
            try:
                compilation = transpile_jvm(
                    source,
                    filename=str(self.entrypoint_path),
                    module_name=ENTRYPOINT_MODULE,
                    class_name=class_name,
                    root_names=aliases,
                    tests=tests,
                    test_sdk=api if robolectric else None,
                    test_manifest=manifest.name if robolectric else None,
                )
                factories = [espresso_view_class, espresso_android_class]
                if not robolectric:
                    factories.extend(
                        [uiautomator_device_class, uiautomator_element_class]
                    )
                bridges = dict(factory() for factory in factories)
                compilation = replace(
                    compilation,
                    classes={**compilation.classes, **bridges},
                    resources=(manifest.parent,),
                )
                self.write_manifest(compilation, manifest)
                return compilation
            finally:
                sys.modules.pop(ENTRYPOINT_MODULE, None)

    @staticmethod
    def write_manifest(compilation: JVMCompilation, path: Path) -> None:
        metadata = {
            name: read_jvm_class(content)
            for name, content in compilation.classes.items()
        }
        activities = []
        applications = []
        for name, value in metadata.items():
            current = value
            while current.super_name in metadata:
                current = metadata[current.super_name]
            if current.super_name == "android/app/Activity":
                validate_android_entrypoint(compilation, name, "Activity")
                activities.append(name.replace("/", "."))
            if current.super_name == "android/app/Application":
                applications.append(name)
        bases = {value.super_name for value in metadata.values()}
        applications = [name for name in applications if name not in bases]
        if len(applications) > 1:
            raise ValueError("Android tests require at most one Application subclass")
        owner = ""
        if applications:
            validate_android_entrypoint(compilation, applications[0], "Application")
            owner = ' android:name="' + escape(
                applications[0].replace("/", "."), quote=True,
            ) + '"'
        declarations = "\n".join(
            f'    <activity android:name="{escape(name, quote=True)}" '
            'android:exported="false" />'
            for name in sorted(activities)
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="org.pyjs.testing">
"""
            + "  <application" + owner + ">\n"
            + declarations
            + "\n  </application>\n</manifest>\n"
        )


def generate_android_entrypoint_source(
    selected_tests: list[SelectedTest],
) -> str:
    lines = []
    for index, selected in enumerate(selected_tests):
        lines.append(
            f"from {selected.module_name} import "
            f"{selected.function_name} as __pyjs_test_{index}"
        )
    lines.extend(["", "", "def main() -> int:", "    return 0", ""])
    return "\n".join(lines)


__all__ = ["AndroidJVMSuiteBuilder"]
