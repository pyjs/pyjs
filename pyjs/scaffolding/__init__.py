import importlib
import importlib.metadata
import inspect
import json
import keyword
import re
import shutil
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath

from pyjs import __version__

TEMPLATE_ENTRY_POINT_GROUP = "pyjs.templates"
IGNORED_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}


@dataclass(frozen=True)
class Template:
    name: str
    title: str
    description: str
    kind: str
    modules: tuple[str, ...]

    @property
    def primary_module(self) -> str:
        name = self.name.rsplit(".", 1)[-1]
        return name if name in self.modules else self.modules[0]


def version_string() -> str:
    return ".".join(str(part) for part in __version__)


def templates() -> tuple[Template, ...]:
    discovered = []
    seen = set()
    entry_points = importlib.metadata.entry_points(group=TEMPLATE_ENTRY_POINT_GROUP)
    for entry_point in sorted(entry_points, key=lambda entry_point: entry_point.name):
        source = entry_point.load()
        name = source.__name__
        if name in seen:
            raise ValueError(f"duplicate PyJS template: {name!r}")
        seen.add(name)
        if hasattr(source, "__path__"):
            kind = "directory"
            modules = tuple(
                sorted(
                    child.name.removesuffix(".py")
                    for child in resources.files(source).iterdir()
                    if child.name.endswith(".py") and not child.name.startswith("__")
                )
            )
            if not modules:
                raise ValueError(
                    f"directory template {name!r} must contain at least one Python module"
                )
        else:
            kind = "file"
            modules = (Path(source.__file__).stem,)
        discovered.append(
            Template(
                name=name,
                title=name.rsplit(".", 1)[-1].replace("_", " ").replace("-", " ").title(),
                description=inspect.getdoc(source) or f"An application created from {name}.",
                kind=kind,
                modules=modules,
            )
        )
    return tuple(sorted(discovered, key=lambda template: template.name))


def find_template(name: str) -> Template:
    catalog = templates()
    if not catalog:
        raise ValueError(
            "no PyJS templates are installed; "
            "install the official templates with 'python -m pip install pyjs-examples'"
        )
    for template in catalog:
        if template.name == name:
            return template
    choices = ", ".join(template.name for template in catalog)
    raise ValueError(f"unknown template {name!r}; choose from: {choices}")


def _ignored_source(name: str) -> bool:
    return name in IGNORED_NAMES or name.endswith((".pyc", ".main.js", ".main.css", ".main.html"))


def _source_files(source, parent: PurePosixPath | None = None):
    if parent is None:
        parent = PurePosixPath()
    for child in sorted(source.iterdir(), key=lambda child: child.name):
        if _ignored_source(child.name):
            continue
        if not parent.parts and child.name in {"__init__.py", "__main__.py"}:
            continue
        relative_path = parent / child.name
        if child.is_dir():
            yield from _source_files(child, relative_path)
        else:
            yield relative_path.as_posix(), child.read_bytes()


def _normalize_source(
    name: str,
    content: bytes,
    template: Template,
) -> bytes:
    try:
        value = content.decode("utf-8")
    except UnicodeDecodeError:
        return content

    if name == "README.md":
        value = value.replace(".venv/bin/python", "python")
        value = value.replace(
            f"python -m {template.name}",
            f"python {template.primary_module}.py",
        )
        package_path = template.name.split(".", 1)[-1].replace(".", "/")
        value = value.replace(f"examples/{package_path}/", "")
        value = value.replace("From the repository root", "From the project root")

    if name.endswith(".py"):
        for module in template.modules:
            value = value.replace(
                f"from {template.name}.{module} import",
                f"from {module} import",
            )
            value = value.replace(f"from .{module} import", f"from {module} import")

    return value.encode("utf-8")


def _materialized_sources(template: Template) -> tuple[tuple[str, bytes], ...]:
    if template.kind == "file":
        source = Path(importlib.import_module(template.name).__file__)
        return ((source.name, source.read_bytes()),)

    return tuple(
        (name, _normalize_source(name, content, template))
        for name, content in _source_files(resources.files(template.name))
    )


def template_sources(template: Template) -> tuple[tuple[str, str | None], ...]:
    sources = []
    for name, content in _materialized_sources(template):
        try:
            value = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            value = None
        sources.append((name, value))
    return tuple(sources)


def _distribution_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError(
            "project names must start with a letter or number and contain only "
            "letters, numbers, dots, underscores, or hyphens"
        )
    return re.sub(r"[-_.]+", "-", name).lower()


def _package_name(name: str) -> str:
    if not name.isidentifier() or keyword.iskeyword(name):
        raise ValueError(
            "application names must be valid Python identifiers because they are also "
            "used as package names"
        )
    return name


def _render(value: str, context: dict[str, str]) -> str:
    for name, replacement in context.items():
        value = value.replace(f"__PYJS_{name}__", replacement)
    return value


def _copy_template(source, destination: Path, context: dict[str, str]):
    destination.mkdir(parents=True, exist_ok=True)
    for child in sorted(source.iterdir(), key=lambda child: child.name):
        output_name = ".gitignore" if child.name == "gitignore.template" else child.name
        if output_name.endswith(".template"):
            output_name = output_name.removesuffix(".template")
        output_name = _render(output_name, context)
        output = destination / output_name
        if child.is_dir():
            _copy_template(child, output, context)
        elif child.name.endswith(".template"):
            output.write_text(
                _render(child.read_text(encoding="utf-8"), context),
                encoding="utf-8",
            )
        else:
            output.write_bytes(child.read_bytes())


def _copy_source(template: Template, destination: Path):
    for name, content in _materialized_sources(template):
        output = destination / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)


def _project_toml(
    name: str,
    description: str,
    modules: tuple[str, ...],
    package: str | None = None,
    src_layout: bool = False,
) -> str:
    version = version_string()
    description_value = json.dumps(description)
    if package is None:
        module_list = ", ".join(f'"{module}"' for module in modules)
        setuptools = f"[tool.setuptools]\npy-modules = [{module_list}]"
    else:
        source = 'where = ["src"]\n' if src_layout else ""
        setuptools = (
            "[tool.setuptools.packages.find]\n"
            f"{source}"
            f'include = ["{package}", "{package}.*"]'
        )
    application = (
        f'\n[tool.pyjs]\napplication = "{package}.{package}"\n' if package else ""
    )
    return f"""\
[build-system]
requires = ["setuptools>=82.0.1"]
build-backend = "setuptools.build_meta"

[project]
name = "{_distribution_name(name)}"
version = "0.1.0"
description = {description_value}
readme = "README.md"
requires-python = ">=3.14"
dependencies = ["pyjs~={version}"]

[project.optional-dependencies]
test = ["pytest>=9.0", "ruff>=0.15.0"]

{setuptools}
{application}

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
target-version = "py314"
line-length = 100

[tool.ruff.lint]
extend-select = ["B", "I", "UP"]
"""


def _write_project_files(
    destination: Path,
    name: str,
    description: str,
    modules: tuple[str, ...],
    package: str | None = None,
    src_layout: bool = False,
):
    (destination / "pyproject.toml").write_text(
        _project_toml(name, description, modules, package, src_layout),
        encoding="utf-8",
    )
    (destination / ".gitignore").write_text(
        ".venv/\n__pycache__/\n.pytest_cache/\n.ruff_cache/\n*.py[cod]\n"
        "*.main.js\n*.main.css\n*.main.html\n",
        encoding="utf-8",
    )


def _populate(
    destination: Path,
    project_name: str,
    template: Template | None,
    src_layout: bool = False,
):
    title = project_name.replace("-", " ").replace("_", " ").title()
    description = "A browser application built with PyJS."
    context = {
        "INLINE_TEST": "",
        "PACKAGE": _package_name(project_name),
        "PROJECT_NAME": _distribution_name(project_name),
        "PROJECT_TITLE": title,
        "SOURCE_ROOT": "src" if src_layout else "",
        "VERSION": version_string(),
    }

    starter = resources.files(__package__).joinpath("templates", "app")
    if template is None:
        _copy_template(starter, destination, context)
        modules = ()
        package = context["PACKAGE"]
    else:
        description = template.description
        _copy_source(template, destination)
        if template.kind == "file":
            (destination / "README.md").write_text(
                f"# {title}\n\n{description}\n\n"
                "## Run\n\n"
                f"```bash\npython {template.modules[0]}.py\n```\n",
                encoding="utf-8",
            )
        modules = template.modules
        package = None

    _write_project_files(
        destination,
        project_name,
        description,
        modules,
        package,
        src_layout,
    )


def _populate_file(destination: Path, project_name: str, template: Template | None):
    if template is None:
        inline_test = resources.files(__package__).joinpath("templates", "app_test.py.template")
        context = {
            "INLINE_TEST": inline_test.read_text(encoding="utf-8").rstrip() + "\n\n\n",
            "PACKAGE": _package_name(project_name),
            "PROJECT_NAME": _distribution_name(project_name),
            "PROJECT_TITLE": project_name.replace("-", " ").replace("_", " ").title(),
            "VERSION": version_string(),
        }
        source = resources.files(__package__).joinpath(
            "templates",
            "app",
            "__PYJS_SOURCE_ROOT__",
            "__PYJS_PACKAGE__",
            "__PYJS_PACKAGE__.py.template",
        )
        destination.write_text(
            _render(source.read_text(encoding="utf-8"), context), encoding="utf-8"
        )
        return

    _, content = _materialized_sources(template)[0]
    destination.write_bytes(content)


def create(
    name: str,
    destination: str | Path | None = None,
    *,
    template: str | None = None,
    single_file: bool = False,
    src_layout: bool = False,
) -> Path:
    project_name = _package_name(name)
    if destination is None:
        destination = Path.cwd() if single_file else Path(project_name)
    destination = Path(destination).resolve()
    selected_template = find_template(template) if template is not None else None
    if src_layout and single_file:
        raise ValueError("--src-layout cannot be combined with --single-file")
    if src_layout and selected_template is not None:
        raise ValueError("--src-layout cannot be combined with --template")
    if single_file:
        if selected_template is not None and selected_template.kind != "file":
            raise ValueError(
                f"template {selected_template.name!r} is a directory template "
                "and cannot create a single file"
            )
        if destination.exists() and not destination.is_dir():
            raise FileExistsError(f"destination is not a directory: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        application = destination / f"{project_name}.py"
        if application.exists():
            raise FileExistsError(f"destination already exists: {application}")

        temporary = Path(tempfile.mkdtemp(prefix=f".{project_name}-", dir=destination))
        try:
            temporary_file = temporary / application.name
            _populate_file(temporary_file, project_name, selected_template)
            temporary_file.replace(application)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        return application

    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise FileExistsError(f"destination is not empty: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{project_name}-", dir=destination.parent))
    try:
        _populate(temporary, project_name, selected_template, src_layout)
        if destination.exists():
            shutil.copytree(temporary, destination, dirs_exist_ok=True)
        else:
            temporary.replace(destination)
            temporary = None
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
    return destination


__all__ = [
    "Template",
    "create",
    "find_template",
    "template_sources",
    "templates",
    "version_string",
]
