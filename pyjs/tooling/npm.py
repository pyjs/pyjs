import importlib
import json
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pyjs.tooling.node import Npm

PACKAGE_NAME = re.compile(r"(?:@[a-z0-9._-]+/)?[a-z0-9._-]+$")
EXACT_VERSION = re.compile(
    r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
JAVASCRIPT_IDENTIFIER = re.compile(r"[$A-Za-z_][$0-9A-Za-z_]*$")
ESBUILD_VERSION = "0.28.2"


@dataclass(frozen=True, order=True)
class NpmPackage:
    """One exact npm dependency required by a client compatibility module."""

    name: str
    version: str

    def __post_init__(self):
        if PACKAGE_NAME.fullmatch(self.name) is None:
            raise ValueError(f"Invalid npm package name: {self.name!r}.")
        if EXACT_VERSION.fullmatch(self.version) is None:
            raise ValueError(
                f"npm package {self.name!r} requires an exact semantic version, "
                f"got {self.version!r}."
            )


@dataclass(frozen=True, order=True)
class NpmImport:
    """One npm package namespace exposed to generated JavaScript."""

    package: NpmPackage
    alias: str
    styles: tuple[str, ...] = ()

    def __post_init__(self):
        for style in self.styles:
            if (not isinstance(style, str) or '\\' in style or style.startswith('/')
                    or '..' in style.split('/') or not style.endswith('.css')):
                raise ValueError('npm styles must be package-relative CSS paths')
        if not self.alias.startswith("$") or JAVASCRIPT_IDENTIFIER.fullmatch(
            self.alias
        ) is None:
            raise ValueError(
                "npm namespace aliases must be JavaScript identifiers beginning "
                f"with '$', got {self.alias!r}."
            )


def module_npm_imports(module_name: str) -> tuple[NpmImport, ...]:
    module = importlib.import_module(module_name)
    imports = getattr(module, "__pyjs_npm_imports__", ())
    if not isinstance(imports, tuple) or not all(
        isinstance(value, NpmImport) for value in imports
    ):
        raise TypeError(
            f"{module_name}.__pyjs_npm_imports__ must be a tuple of "
            "NpmImport values."
        )
    return imports


def module_npm_packages(module_name: str) -> tuple[NpmPackage, ...]:
    module = importlib.import_module(module_name)
    packages = getattr(module, "__pyjs_npm_packages__", ())
    if not isinstance(packages, tuple) or not all(
        isinstance(package, NpmPackage) for package in packages
    ):
        raise TypeError(
            f"{module_name}.__pyjs_npm_packages__ must be a tuple of "
            "NpmPackage values."
        )
    return packages + tuple(value.package for value in module_npm_imports(module_name))


def collect_npm_packages(module_names: Iterable[str]) -> tuple[NpmPackage, ...]:
    packages: dict[str, NpmPackage] = {}
    owners: dict[str, str] = {}
    for module_name in dict.fromkeys(module_names):
        for package in module_npm_packages(module_name):
            existing = packages.get(package.name)
            if existing is not None and existing.version != package.version:
                raise ValueError(
                    f"npm package {package.name!r} requires both "
                    f"{existing.version!r} from {owners[package.name]} and "
                    f"{package.version!r} from {module_name}."
                )
            packages[package.name] = package
            owners[package.name] = module_name
    return tuple(sorted(packages.values()))


def collect_npm_imports(module_names: Iterable[str]) -> tuple[NpmImport, ...]:
    imports: dict[str, NpmImport] = {}
    owners: dict[str, str] = {}
    for module_name in dict.fromkeys(module_names):
        for value in module_npm_imports(module_name):
            existing = imports.get(value.alias)
            if existing is not None and existing.package != value.package:
                raise ValueError(
                    f"npm namespace {value.alias!r} refers to both "
                    f"{existing.package.name!r} from {owners[value.alias]} and "
                    f"{value.package.name!r} from {module_name}."
                )
            if existing is not None:
                value = NpmImport(value.package, value.alias,
                                  tuple(dict.fromkeys((*existing.styles, *value.styles))))
            imports[value.alias] = value
            owners[value.alias] = module_name
    return tuple(sorted(imports.values()))


@dataclass(frozen=True)
class NpmSyncResult:
    directory: Path
    packages: tuple[NpmPackage, ...]
    imports: tuple[NpmImport, ...]
    vendor: Path | None


class ManagedNpmProject:
    """Materialize exact reachable npm dependencies without user-authored JS config."""

    def __init__(self, directory: Path, npm: Npm | None = None):
        self.directory = directory
        self.npm = npm or Npm()

    @classmethod
    def for_project(
        cls,
        start: Path,
        npm: Npm | None = None,
    ) -> ManagedNpmProject:
        """Locate the nearest Python project and its managed npm directory."""
        start = start.resolve()
        directory = start.parent if start.is_file() else start
        for candidate in (directory, *directory.parents):
            if (candidate / "pyproject.toml").is_file():
                return cls(candidate / ".pyjs" / "npm", npm)
        return cls(directory / ".pyjs" / "npm", npm)

    def sync(
        self,
        packages: tuple[NpmPackage, ...],
        imports: tuple[NpmImport, ...] = (),
    ) -> NpmSyncResult:
        self.directory.mkdir(parents=True, exist_ok=True)
        metadata = {
            "name": "pyjs-managed-dependencies",
            "private": True,
            "dependencies": {
                package.name: package.version for package in packages
            },
        }
        if imports:
            metadata["devDependencies"] = {"esbuild": ESBUILD_VERSION}
            metadata["pyjs"] = {
                "imports": {
                    value.alias: value.package.name for value in imports
                }
            }
            if any(value.styles for value in imports):
                metadata["pyjs"]["styles"] = {
                    value.alias: list(value.styles) for value in imports if value.styles
                }
        package_json = json.dumps(metadata, indent=2) + "\n"
        package_path = self.directory / "package.json"
        unchanged = (
            package_path.is_file()
            and package_path.read_text(encoding="utf-8") == package_json
        )
        package_path.write_text(
            package_json,
            encoding="utf-8",
        )
        vendor = self.directory / "pyjs-vendor.js" if imports else None
        if not unchanged or not (self.directory / "package-lock.json").is_file():
            self.npm.sync(self.directory)
        if vendor is not None and (not unchanged or not vendor.is_file()):
            vendor.unlink(missing_ok=True)
            entry = self.directory / "pyjs-vendor-entry.js"
            entry.write_text(
                "".join(
                    f"import * as {value.alias} from {value.package.name!r};\n"
                    for value in imports
                )
                + self._styles_source(imports)
                + "export {"
                + ", ".join(value.alias for value in imports)
                + "};\n",
                encoding="utf-8",
            )
            self.npm.bundle(entry, vendor)
        return NpmSyncResult(self.directory, packages, imports, vendor)

    def _styles_source(self, imports: tuple[NpmImport, ...]) -> str:
        sources = []
        for value in imports:
            for style in value.styles:
                path = self.directory / "node_modules" / value.package.name / style
                package_root = self.directory / "node_modules" / value.package.name
                if not path.resolve().is_relative_to(package_root.resolve()):
                    raise ValueError("npm stylesheet escapes its package")
                css = path.read_text(encoding="utf-8")
                if re.search(r"@import\b|url\(", css, re.IGNORECASE):
                    raise ValueError("npm styles must be self-contained CSS without imports or URLs")
                identifier = value.package.name + "@" + value.package.version + "/" + style
                sources.append(
                    "if (typeof document !== 'undefined') {\n"
                    f"const id = {json.dumps('pyjs-npm:' + identifier)};\n"
                    "if (!document.getElementById(id)) {\n"
                    "const style = document.createElement('style'); style.id = id;\n"
                    f"style.textContent = {json.dumps(css)};\n"
                    "document.head.appendChild(style);\n}\n}\n"
                )
        return "".join(sources)

    def vendor_for(self, imports: tuple[NpmImport, ...]) -> Path | None:
        """Return the current vendor module when it matches exact imports."""
        if not imports:
            return None
        package_path = self.directory / "package.json"
        vendor = self.directory / "pyjs-vendor.js"
        if not package_path.is_file() or not vendor.is_file():
            return None
        try:
            metadata = json.loads(package_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        expected = {
            value.alias: value.package.name for value in imports
        }
        styles = {value.alias: list(value.styles) for value in imports if value.styles}
        if metadata.get("pyjs", {}).get("styles", {}) != styles:
            return None
        dependencies = metadata.get("dependencies", {})
        if metadata.get("pyjs", {}).get("imports") != expected or any(
            dependencies.get(value.package.name) != value.package.version
            for value in imports
        ):
            return None
        return vendor

    def copy_vendor(
        self,
        imports: tuple[NpmImport, ...],
        destination: Path,
    ) -> Path | None:
        """Copy the exact current vendor or explain how to synchronize it."""
        if not imports:
            return None
        vendor = self.vendor_for(imports)
        if vendor is None:
            raise RuntimeError(
                "JavaScript dependencies are not synchronized; run "
                "'pyjs npm sync' from the project directory"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if vendor.resolve() != destination.resolve():
            shutil.copy2(vendor, destination)
        return destination
