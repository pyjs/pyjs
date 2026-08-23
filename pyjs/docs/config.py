from dataclasses import dataclass
from pathlib import Path
from tomllib import load


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


def _project_name(name: str) -> str:
    return "PyJS" if name.lower() == "pyjs" else name.replace("-", " ").title()


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
    )
