from pathlib import Path

from pyjs.server.dev import Application, Server

from .builder import build
from .config import load_config


def _serve(project_root: Path, host: str, port: int):
    output = build(load_config(project_root))
    application = Application(name="PyJS documentation")
    application.mount_files("/", output, index=True)
    server = Server(application, host=host, port=port, allow_remote=True)
    print(f"Built documentation in {output}")
    print(f"Serving documentation at {server.url}")
    try:
        server.serve_forever()
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


def run(args) -> int:
    project_root = args.project_dir.resolve()
    if args.docs_command == "build":
        output = build(load_config(project_root))
        print(f"Built documentation in {output}")
        return 0
    _serve(project_root, args.host, args.port)
    return 0
