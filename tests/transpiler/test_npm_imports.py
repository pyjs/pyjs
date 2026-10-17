from pyjs.analysis.analyzer import from_entry_point, release_compilation
from pyjs.analysis.source import create_module
from pyjs.javascript.transpiler import (
    bundle_with_source_map,
    transpile_module_with_source_map,
)
from pyjs.tooling.npm import NpmImport, NpmPackage


def external_module():
    module = create_module(
        """
from pyjs import js

@js
def answer() -> int: ...

answer.source("return $example.answer;")

@js
def main() -> int:
    return answer()
""".lstrip(),
        "external.py",
        "external",
    )
    package = NpmPackage("example", "1.2.3")
    module.__pyjs_npm_imports__ = (NpmImport(package, "$example"),)
    return module


def test_standalone_modules_import_the_managed_vendor_namespace():
    module = external_module()
    entry_point, _tailwind = from_entry_point(module.main)
    try:
        generated = transpile_module_with_source_map(entry_point.container)
    finally:
        release_compilation(entry_point)

    assert generated.javascript == """\
import { $example } from './pyjs-vendor.js';

export function answer() {
    return $example.answer;
}"""
    assert generated.npm_imports == module.__pyjs_npm_imports__


def test_bundles_hoist_managed_vendor_imports_outside_module_factories():
    module = external_module()

    generated, _css = bundle_with_source_map(
        module.main,
        include_main=True,
    )

    assert generated.javascript.startswith(
        "import { $example } from './pyjs-vendor.js';\n"
    )
    assert generated.javascript.count("from './pyjs-vendor.js'") == 1
    assert "return $example.answer;" in generated.javascript
    assert generated.npm_imports == module.__pyjs_npm_imports__
