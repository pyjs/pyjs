import importlib
import json
import sys
from pathlib import Path

from pyjs.server.dev import Application, Server, browser_url

from .builder import build
from .config import load_config


def _print_api_coverage(output: Path):
    report = output / "_pyjs" / "api-coverage.json"
    if not report.is_file():
        return
    coverage = json.loads(report.read_text(encoding="utf-8"))
    module_label = "module" if coverage["modules"] == 1 else "modules"
    print(
        "API reference: "
        f"{coverage['documented']}/{coverage['symbols']} public symbols "
        f"documented across {coverage['modules']} {module_label}"
    )
    if coverage["undocumented"]:
        print(f"API coverage details: {report}")


def _serve(project_root: Path, host: str, port: int, *, apps=(), open_path=None):
    if open_path is not None:
        browser_url("http://localhost", open_path)
    output = build(load_config(project_root))
    application = Application(name="PyJS documentation")
    application.mount_files("/", output, index=True)
    # Explicit trusted local extensions, shared with ordinary website applications.
    previous = sys.path[:]
    sys.path.insert(0, str(project_root))
    try:
        for target in apps:
            module, attribute = target.split(":", 1)
            getattr(importlib.import_module(module), attribute)(application)
    finally:
        sys.path[:] = previous
    server = Server(application, host=host, port=port, allow_remote=True)
    print(f"Built documentation in {output}")
    _print_api_coverage(output)
    try:
        if open_path is None:
            server.serve_forever()
        else:
            server.serve_forever(open_path=open_path)
    except KeyboardInterrupt:
        print("\nStopping documentation server.")
    finally:
        server.close()


def _add_project_dir(command):
    command.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="project containing pyproject.toml and docs/ (default: current directory)",
    )


def add_parser(subcommands):
    docs = subcommands.add_parser(
        "docs",
        help="build and serve static documentation",
        description="Build static documentation with PyJS.",
    )
    docs_commands = docs.add_subparsers(dest="docs_command", required=True)
    build_command = docs_commands.add_parser("build", help="build the static site")
    _add_project_dir(build_command)
    serve = docs_commands.add_parser("serve", help="build and serve the static site")
    _add_project_dir(serve)
    serve.add_argument("--host", default="localhost")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--open", nargs="?", const="/", dest="open_path", metavar="PATH")
    serve.add_argument("--app", action="append", default=[], metavar="MODULE:FUNCTION",
                       help="register live UI routes on the documentation server")


def run(args) -> int:
    project_root = args.project_dir.resolve()
    if args.docs_command == "build":
        output = build(load_config(project_root))
        print(f"Built documentation in {output}")
        _print_api_coverage(output)
        return 0
    _serve(project_root, args.host, args.port, apps=args.app, open_path=args.open_path)
    return 0
