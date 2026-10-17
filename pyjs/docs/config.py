from dataclasses import dataclass
from pathlib import Path
from tomllib import load


@dataclass(frozen=True)
class DocsVersion:
    label: str
    url: str


@dataclass(frozen=True)
class DocsConfig:
    project_root: Path
    docs_dir: Path
    site_dir: Path
    site_name: str
    site_url: str
    repo_url: str
    repo_name: str
    discord_url: str = ""
    x_url: str = ""
    route_prefix: str = ""
    nojekyll: bool = True
    version: str = ""
    versions: tuple[DocsVersion, ...] = ()
    social_image: str = ""
    social_image_alt: str = ""
    social_image_width: int = 0
    social_image_height: int = 0
    x_handle: str = ""
    api_modules: tuple[str, ...] = ()


def _versions(values: list[dict[str, object]]) -> tuple[DocsVersion, ...]:
    return tuple(
        DocsVersion(label=str(value["label"]), url=str(value["url"]))
        for value in values
    )


def _project_name(name: str) -> str:
    return "PyJS" if name.lower() == "pyjs" else name.replace("-", " ").title()


def _api_modules(value: object) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError("tool.pyjs.docs.api must be a list of module names")
    modules = tuple(value)
    invalid = [
        module
        for module in modules
        if not isinstance(module, str)
        or not module
        or not all(part.isidentifier() for part in module.split("."))
    ]
    if invalid:
        raise ValueError(
            "tool.pyjs.docs.api contains invalid module names: "
            + ", ".join(repr(module) for module in invalid)
        )
    return modules


def load_config(project_root: str | Path = ".") -> DocsConfig:
    project_root = Path(project_root).resolve()
    pyproject_path = project_root / "pyproject.toml"
    pyproject = {}
    if pyproject_path.exists():
        with pyproject_path.open("rb") as file:
            pyproject = load(file)

    project = pyproject.get("project", {})
    docs = pyproject.get("tool", {}).get("pyjs", {}).get("docs", {})
    urls = project.get("urls", {})
    repo_url = docs.get("repo_url", urls.get("Source", ""))
    return DocsConfig(
        project_root=project_root,
        docs_dir=project_root / docs.get("source", "docs"),
        site_dir=project_root / docs.get("output", "site"),
        site_name=docs.get("site_name", _project_name(project.get("name", project_root.name))),
        site_url=docs.get("site_url", urls.get("Documentation", "")),
        repo_url=repo_url,
        repo_name=docs.get("repo_name", repo_url.removesuffix("/").rsplit("/", 2)[-1]),
        discord_url=urls.get("Discord", ""),
        x_url=urls.get("X", ""),
        route_prefix=docs.get("route_prefix", ""),
        nojekyll=docs.get("nojekyll", True),
        version=str(docs.get("version", project.get("version", ""))),
        versions=_versions(docs.get("versions", [])),
        social_image=str(docs.get("social_image", "")),
        social_image_alt=str(docs.get("social_image_alt", "")),
        social_image_width=int(docs.get("social_image_width", 0)),
        social_image_height=int(docs.get("social_image_height", 0)),
        x_handle=str(docs.get("x_handle", "")),
        api_modules=_api_modules(docs.get("api", ())),
    )
