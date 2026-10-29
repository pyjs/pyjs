import json
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest

from pyjs.tooling.npm import (
    ManagedNpmProject,
    NpmImport,
    NpmPackage,
    collect_npm_imports,
    collect_npm_packages,
    merge_npm_imports,
    module_npm_packages,
)


def install_module(monkeypatch, name, packages):
    module = ModuleType(name)
    module.__pyjs_npm_packages__ = packages
    monkeypatch.setitem(sys.modules, name, module)


def test_collect_npm_packages_deduplicates_and_sorts_exact_requirements(
    monkeypatch,
):
    install_module(
        monkeypatch,
        "example.first",
        (NpmPackage("yjs", "13.6.27"),),
    )
    install_module(
        monkeypatch,
        "example.second",
        (
            NpmPackage("@example/provider", "1.2.3"),
            NpmPackage("yjs", "13.6.27"),
        ),
    )

    assert collect_npm_packages(
        ["example.second", "example.first", "example.second"]
    ) == (
        NpmPackage("@example/provider", "1.2.3"),
        NpmPackage("yjs", "13.6.27"),
    )


def test_collect_npm_imports_includes_packages_and_rejects_alias_conflicts(
    monkeypatch,
):
    yjs = NpmPackage("yjs", "13.6.32")
    install_module(monkeypatch, "example.yjs", ())
    sys.modules["example.yjs"].__pyjs_npm_imports__ = (
        NpmImport(yjs, "$yjs"),
    )

    assert collect_npm_imports(["example.yjs"]) == (NpmImport(yjs, "$yjs"),)
    assert collect_npm_packages(["example.yjs"]) == (yjs,)

    other = NpmPackage("other", "1.0.0")
    install_module(monkeypatch, "example.other", ())
    sys.modules["example.other"].__pyjs_npm_imports__ = (
        NpmImport(other, "$yjs"),
    )
    with pytest.raises(ValueError, match="npm namespace '\\$yjs' refers to both"):
        collect_npm_imports(["example.yjs", "example.other"])


def test_collect_npm_packages_rejects_conflicting_exact_versions(monkeypatch):
    install_module(
        monkeypatch,
        "example.first",
        (NpmPackage("yjs", "13.6.26"),),
    )
    install_module(
        monkeypatch,
        "example.second",
        (NpmPackage("yjs", "13.6.27"),),
    )

    with pytest.raises(
        ValueError,
        match=(
            "npm package 'yjs' requires both '13.6.26' from example.first "
            "and '13.6.27' from example.second"
        ),
    ):
        collect_npm_packages(["example.first", "example.second"])


@pytest.mark.parametrize(
    ("name", "version", "message"),
    [
        ("YJS", "13.6.27", "Invalid npm package name"),
        ("yjs", "latest", "requires an exact semantic version"),
        ("yjs", "^13.6.27", "requires an exact semantic version"),
    ],
)
def test_npm_packages_require_canonical_names_and_exact_versions(
    name,
    version,
    message,
):
    with pytest.raises(ValueError, match=message):
        NpmPackage(name, version)


def test_npm_packages_accept_exact_versions_with_build_metadata():
    assert NpmPackage("yjs", "13.6.27+pyjs.1").version == "13.6.27+pyjs.1"


def test_npm_imports_require_reserved_namespace_identifiers():
    package = NpmPackage("yjs", "13.6.32")

    with pytest.raises(ValueError, match="identifiers beginning with '\\$'"):
        NpmImport(package, "yjs")


def test_module_npm_packages_rejects_malformed_metadata(monkeypatch):
    install_module(monkeypatch, "example.invalid", [NpmPackage("yjs", "13.6.27")])

    with pytest.raises(
        TypeError,
        match=r"__pyjs_npm_packages__ must be a tuple of NpmPackage values",
    ):
        module_npm_packages("example.invalid")


def test_managed_npm_project_writes_deterministic_internal_metadata(tmp_path):
    npm = Mock()
    project = ManagedNpmProject(tmp_path / ".pyjs" / "npm", npm)
    packages = (
        NpmPackage("@example/provider", "1.2.3"),
        NpmPackage("yjs", "13.6.27"),
    )

    package_imports = (NpmImport(packages[1], "$yjs"),)
    result = project.sync(packages, package_imports)

    assert result.directory == tmp_path / ".pyjs" / "npm"
    assert result.packages == packages
    assert result.imports == package_imports
    assert result.vendor == result.directory / "pyjs-vendor.js"
    assert json.loads((result.directory / "package.json").read_text()) == {
        "name": "pyjs-managed-dependencies",
        "private": True,
        "dependencies": {
            "@example/provider": "1.2.3",
            "yjs": "13.6.27",
        },
        "devDependencies": {"esbuild": "0.28.2"},
        "pyjs": {"imports": {"$yjs": "yjs"}},
    }
    npm.sync.assert_called_once_with(result.directory)
    npm.bundle.assert_called_once_with(
        result.directory / "pyjs-vendor-entry.js",
        result.vendor,
    )
    assert (result.directory / "pyjs-vendor-entry.js").read_text() == (
        "import * as $yjs from 'yjs';\nexport {$yjs};\n"
    )


def test_managed_npm_project_finds_only_an_exact_current_vendor(tmp_path):
    npm = Mock()
    project = ManagedNpmProject(tmp_path / "managed", npm)
    package = NpmPackage("yjs", "13.6.32")
    imports = (NpmImport(package, "$yjs"),)
    result = project.sync((package,), imports)
    assert result.vendor is not None
    result.vendor.touch()

    assert project.vendor_for(imports) == result.vendor
    assert project.vendor_for(
        (NpmImport(NpmPackage("yjs", "13.6.31"), "$yjs"),)
    ) is None


def test_managed_npm_project_is_located_from_nested_project_source(tmp_path):
    (tmp_path / "pyproject.toml").touch()
    source = tmp_path / "package" / "app.py"
    source.parent.mkdir()
    source.touch()

    project = ManagedNpmProject.for_project(source, Mock())

    assert project.directory == tmp_path / ".pyjs" / "npm"


def test_managed_npm_project_copies_a_matching_vendor(tmp_path):
    npm = Mock()
    project = ManagedNpmProject(tmp_path / "managed", npm)
    package = NpmPackage("yjs", "13.6.32")
    imports = (NpmImport(package, "$yjs"),)
    result = project.sync((package,), imports)
    assert result.vendor is not None
    result.vendor.write_text("export const ready = true;\n")
    destination = tmp_path / "static" / "pyjs-vendor.js"

    assert project.copy_vendor(imports, destination) == destination
    assert destination.read_text() == "export const ready = true;\n"


def test_styles_are_merged_and_part_of_vendor_identity(tmp_path, monkeypatch):
    package = NpmPackage('example-style', '1.2.3')
    for name, styles in [('style.first', ('theme.css',)), ('style.second', ('base.css',))]:
        install_module(monkeypatch, name, ())
        sys.modules[name].__pyjs_npm_imports__ = (NpmImport(package, '$style', styles),)
    imports = collect_npm_imports(['style.first', 'style.second'])
    assert len(imports) == 1
    assert imports[0].styles == ('base.css', 'theme.css')
    npm = Mock()
    project = ManagedNpmProject(tmp_path, npm)
    assets = tmp_path / 'node_modules' / package.name
    assets.mkdir(parents=True)
    (assets / 'base.css').write_text('.terminal{position:relative}')
    (assets / 'theme.css').write_text('.terminal{color:#123456}')
    result = project.sync((package,), imports)
    source = (tmp_path / 'pyjs-vendor-entry.js').read_text()
    assert "typeof document !== 'undefined'" in source
    assert 'style.textContent =' in source
    assert '.terminal{color:#123456}' in source
    result.vendor.write_text('bundled')
    assert project.vendor_for(imports) == result.vendor
    assert project.vendor_for((NpmImport(package, '$style'),)) is None


@pytest.mark.parametrize('style', ['../a.css', '/a.css', r'..\a.css', 'a.js'])
def test_styles_reject_non_package_paths(style):
    with pytest.raises(ValueError):
        NpmImport(NpmPackage('example', '1.0.0'), '$example', (style,))


def test_failed_styles_bundle_does_not_reuse_a_stale_vendor(tmp_path):
    project = ManagedNpmProject(tmp_path, Mock())
    package = NpmPackage('example-style', '1.2.3')
    imports = (NpmImport(package, '$style', ('base.css',)),)
    (tmp_path / 'pyjs-vendor.js').write_text('stale')
    with pytest.raises(FileNotFoundError):
        project.sync((package,), imports)
    assert project.vendor_for(imports) is None


def test_import_merge_is_deterministic_for_split_targets(tmp_path):
    package = NpmPackage('example-style', '1.2.3')
    first = NpmImport(package, '$style', ('theme.css',))
    second = NpmImport(package, '$style', ('base.css',))
    imports = merge_npm_imports((first, second))
    assert imports == merge_npm_imports((second, first))
    project = ManagedNpmProject(tmp_path, Mock())
    assets = tmp_path / 'node_modules' / package.name
    assets.mkdir(parents=True)
    for path in ('base.css', 'theme.css'):
        (assets / path).write_text('.terminal{color:red}')
    vendor = project.sync((package,), imports).vendor
    vendor.write_text('bundled')
    assert project.vendor_for(tuple({first, second})) == vendor
    assert merge_npm_imports((NpmImport(package, '$style', ('theme.css', 'base.css')),)) == (
        NpmImport(package, '$style', ('theme.css', 'base.css')),)
    with pytest.raises(ValueError, match='Conflicting npm stylesheet order'):
        merge_npm_imports((NpmImport(package, '$style', ('theme.css', 'base.css')),
                           NpmImport(package, '$style', ('base.css', 'theme.css'))))


def test_failed_npm_install_restores_metadata_and_retries(tmp_path):
    package = NpmPackage('example-style', '1.2.3')
    npm = Mock()
    project = ManagedNpmProject(tmp_path, npm)
    assets = tmp_path / 'node_modules' / package.name
    assets.mkdir(parents=True)
    (assets / 'theme.css').write_text('.terminal{color:red}')
    old = (NpmImport(package, '$style'),)
    new = (NpmImport(package, '$style', ('theme.css',)),)
    project.sync((package,), old).vendor.write_text('old vendor')
    (tmp_path / 'package-lock.json').write_text('{}')
    metadata = (tmp_path / 'package.json').read_text()
    npm.sync.side_effect = RuntimeError('Install failed')
    with pytest.raises(RuntimeError, match='Install failed'):
        project.sync((package,), new)
    assert project.vendor_for(new) is None
    assert (tmp_path / 'package.json').read_text() == metadata
    npm.sync.side_effect = None
    npm.reset_mock()
    project.sync((package,), new)
    npm.sync.assert_called_once()
    npm.bundle.assert_called_once()


@pytest.mark.parametrize('css', [
    '@import "asset.css";', r'@\69mport "asset.css";',
    '.x{background:url(asset.png)}', r'.x{background:u\72l(asset.png)}',
    '.x{background:image-set("asset.png" 1x)}',
    '.x{background:-webkit-image-set("asset.png" 1x)}',
    '.x{background:image("asset.png")}', '.x{background:src("asset.png")}',
    '.x{content:"/*"}.y{background:url(asset.png)}/*end*/',
])
def test_package_css_rejects_asset_constructs_before_bundling(tmp_path, css):
    package = NpmPackage('example-style', '1.2.3')
    project = ManagedNpmProject(tmp_path, Mock())
    path = tmp_path / 'node_modules' / package.name / 'theme.css'
    path.parent.mkdir(parents=True)
    path.write_text(css)
    with pytest.raises(ValueError, match='self-contained'):
        project.sync((package,), (NpmImport(package, '$style', ('theme.css',)),))
    project.npm.bundle.assert_not_called()


def test_split_target_merge_retains_declarations_not_incidental_tie_order():
    package = NpmPackage('example-style', '1.2.3')
    first = NpmImport(package, '$style', ('first.css',))
    second = NpmImport(package, '$style', ('second.css',))
    ordered = NpmImport(package, '$style', ('second.css', 'first.css'))
    target_a = merge_npm_imports((first, second))
    target_b = merge_npm_imports((ordered,))
    assert merge_npm_imports((*target_a, *target_b)) == merge_npm_imports((first, second, ordered))
    assert merge_npm_imports((*target_a, *target_b))[0].styles == ('second.css', 'first.css')


def test_aliases_share_package_styles_and_split_target_vendor_identity(tmp_path):
    package = NpmPackage('example-style', '1.2.3')
    first = NpmImport(package, '$first', ('theme.css',))
    second = NpmImport(package, '$second', ('base.css', 'theme.css'))
    third = NpmImport(package, '$third', ('reset.css', 'base.css'))
    merged = merge_npm_imports((first, second, third))
    split = tuple(sorted(set(merge_npm_imports((first, second))) | set(merge_npm_imports((third,)))))
    assert merge_npm_imports(split) == merged
    assert merge_npm_imports(reversed((first, second, third))) == merged
    assert all(value.styles == ('reset.css', 'base.css', 'theme.css') for value in merged)
    project = ManagedNpmProject(tmp_path, Mock())
    assets = tmp_path / 'node_modules' / package.name
    assets.mkdir(parents=True)
    for name in ('reset', 'base', 'theme'):
        (assets / (name + '.css')).write_text('.' + name + '{color:red}')
    project.npm.bundle.side_effect = lambda entry, output: output.write_text(entry.read_text())
    result = project.sync((package,), (first, second, third))
    assert project.vendor_for(split) == result.vendor
    source = result.vendor.read_text()
    assert source.count('.theme{color:red}') == 1
    assert source.count('.base{color:red}') == 1
    assert source.index('.reset{') < source.index('.base{') < source.index('.theme{')
    assert 'export {$first, $second, $third};' in source


def test_contradictory_styles_across_aliases_are_rejected():
    package = NpmPackage('example-style', '1.2.3')
    first = NpmImport(package, '$first', ('base.css', 'theme.css'))
    second = NpmImport(package, '$second', ('theme.css', 'base.css'))
    with pytest.raises(ValueError, match='Conflicting npm stylesheet order'):
        merge_npm_imports((first, second))
    third = NpmImport(package, '$third', ('theme.css', 'extra.css'))
    fourth = NpmImport(package, '$fourth', ('extra.css', 'base.css'))
    with pytest.raises(ValueError, match='Conflicting npm stylesheet order'):
        merge_npm_imports((*merge_npm_imports((first, third)), fourth))
