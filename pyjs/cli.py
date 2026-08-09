import argparse
import asyncio
import importlib
import importlib.util
import json
import os
import runpy
import shutil
import sys
import textwrap
import tomllib
import traceback
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from pyjs.docs.cli import add_parser as add_docs_parser
from pyjs.docs.cli import run as run_docs
from pyjs.scaffolding import (
    Template,
    create,
    find_template,
    template_sources,
    templates,
    version_string,
)
from pyjs.server import page
from pyjs.server import serve as serve_application
from pyjs.testing.capture import capture_url
from pyjs.tooling.node import Node
from pyjs.tooling.perf import (
    DEFAULT_SAMPLES,
    DEFAULT_WARMUPS,
    Benchmark,
    benchmark_python,
    calibrate_python,
    javascript_benchmark,
    run_python,
)
from pyjs.transpiler import (
    CompilationError,
    SourceCompilation,
    bundle,
    compile_source,
    format_compilation_error,
    prepare_bundle,
)

SUBCOMMANDS = {"build", "create", "serve", "template", "inspect", "skill", "docs"}


@dataclass(frozen=True)
class DirectInput:
    source: str
    filename: str
    module_name: str
    javascript_name: str


def parser() -> argparse.ArgumentParser:
    version = version_string()
    command = argparse.ArgumentParser(
        prog="pyjs",
        description="Run Python as JavaScript, build web applications, and create PyJS projects.",
        epilog=(
            "Direct execution: pyjs app.py, pyjs -m package.module, or pyjs -c 'print(1)'. "
            "Use --src to print JavaScript without running it."
        ),
    )
    command.add_argument("--version", action="version", version=f"%(prog)s {version}")
    subcommands = command.add_subparsers(dest="command")

    build = subcommands.add_parser("build", help="build a Python entry point for the browser")
    build.add_argument(
        "module",
        help="module containing the entry point, optionally followed by :function",
    )
    build.add_argument("--only-js", action="store_true", help="only generate JavaScript")
    build.add_argument(
        "--include-main",
        action="store_true",
        help="include and call the entry-point function in the browser bundle",
    )
    build.add_argument("--args", help="JSON list of arguments passed to the entry point")

    serve = subcommands.add_parser("serve", help="serve a PyJS web application")
    serve.add_argument(
        "target",
        nargs="?",
        help="application module or Python file; defaults to the project configuration",
    )

    create_command = subcommands.add_parser("create", help="create a PyJS project or file")
    create_command.add_argument(
        "name",
        help="application and Python package name",
    )
    create_command.add_argument(
        "destination",
        nargs="?",
        help="directory to populate; defaults to NAME",
    )
    create_command.add_argument("--template", help="start from a registered template")
    create_command.add_argument(
        "--src-layout",
        action="store_true",
        help="place the application package under a src directory",
    )
    create_command.add_argument(
        "--single-file",
        action="store_true",
        help="create one standalone Python file instead of a project directory",
    )

    template_command = subcommands.add_parser(
        "template",
        help="list templates or print a template's source",
    )
    template_command.add_argument("name", nargs="?", help="registered template to inspect")
    template_command.add_argument(
        "--src",
        action="store_true",
        help="print the template's transpiled entry-module JavaScript",
    )
    template_command.add_argument("--json", action="store_true", help="emit the catalog as JSON")

    inspect = subcommands.add_parser(
        "inspect",
        help="capture and inspect a running web application",
    )
    inspect.add_argument("url", nargs="?", default="http://127.0.0.1:8000")
    inspect.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("screenshots/pyjs-inspect.png"),
    )
    inspect.add_argument("--width", type=int, default=1280)
    inspect.add_argument("--height", type=int, default=800)
    inspect.add_argument("--scale", type=float, default=1)
    inspect.add_argument("--color-scheme", choices=("light", "dark"))
    inspect.add_argument("--wait-for", metavar="SELECTOR")
    inspect.add_argument("--selector", help="capture only the matching element")
    inspect.add_argument("--delay", type=float, default=0, help="seconds to wait before capture")
    inspect.add_argument("--frames", type=int, default=2, help="animation frames to wait")
    inspect.add_argument("--full-page", action="store_true")
    inspect.add_argument("--interval", type=float, help="seconds between repeated captures")
    inspect.add_argument("--duration", type=float, help="total repeated-capture duration")
    inspect.add_argument("--no-settle", action="store_true")
    inspect.add_argument("--headed", action="store_true")
    inspect.add_argument("--json", action="store_true", help="print artifact paths as JSON")

    subcommands.add_parser(
        "skill",
        help="print version-matched instructions for coding agents",
    )
    add_docs_parser(subcommands)
    return command


def direct_parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        prog="pyjs",
        description="Transpile Python and run the result with PyJS-managed Node.",
    )
    input_group = command.add_mutually_exclusive_group()
    input_group.add_argument("-c", dest="code", help="Python program passed as a string")
    input_group.add_argument("-m", dest="module", help="run a Python module as JavaScript")
    command.add_argument("source", nargs="?", help="Python file, or - to read standard input")
    source_group = command.add_mutually_exclusive_group()
    source_group.add_argument(
        "--src", action="store_true", help="print the entry module without running it"
    )
    source_group.add_argument(
        "--src-all",
        action="store_true",
        help="print the entry module and all tree-shaken dependencies",
    )
    command.add_argument(
        "-v",
        action="count",
        default=0,
        help="show generated source and diagnostics; repeat for more detail",
    )
    command.add_argument("--json", action="store_true", help="emit machine-readable results")
    command.add_argument("--perf", action="store_true", help="compare Python and JavaScript speed")
    command.add_argument("--loops", type=int, help="iterations in each performance sample")
    command.add_argument(
        "--samples",
        type=int,
        default=DEFAULT_SAMPLES,
        help=f"performance samples (default: {DEFAULT_SAMPLES})",
    )
    command.add_argument(
        "--warmups",
        type=int,
        default=DEFAULT_WARMUPS,
        help=f"warmup samples (default: {DEFAULT_WARMUPS})",
    )
    return command


def _is_direct_invocation(argv: list[str]) -> bool:
    if argv and argv[0] in SUBCOMMANDS:
        return False
    direct_options = {
        "-c",
        "-m",
        "--src",
        "--src-all",
        "--json",
        "--perf",
        "--loops",
        "--samples",
        "--warmups",
    }
    if any(
        argument in direct_options
        or (argument.startswith("-") and argument[1:] and set(argument[1:]) == {"v"})
        for argument in argv
    ):
        return True
    return any(argument == "-" for argument in argv) or any(
        not argument.startswith("-") and argument not in SUBCOMMANDS for argument in argv
    )


def _direct_input(args, command_parser: argparse.ArgumentParser) -> DirectInput:
    selected = sum(value is not None for value in (args.code, args.module, args.source))
    if selected != 1:
        command_parser.error("provide exactly one of a Python file, -, -c CODE, or -m MODULE")

    if args.code is not None:
        return DirectInput(args.code, "<string>", "__pyjs_command__", ".js")

    if args.module is not None:
        spec = importlib.util.find_spec(args.module)
        if spec is None or spec.origin is None:
            command_parser.error(f"cannot find module {args.module!r}")
        module_name = args.module
        if spec.submodule_search_locations is not None:
            module_name = f"{args.module}.__main__"
            spec = importlib.util.find_spec(module_name)
            if spec is None or spec.origin is None:
                command_parser.error(f"package {args.module!r} has no __main__ module")
        path = Path(spec.origin)
        if path.suffix != ".py":
            command_parser.error(f"module {args.module!r} does not have Python source")
        return DirectInput(
            path.read_text(encoding="utf-8"),
            str(path),
            module_name,
            f"{module_name}.js",
        )

    if args.source == "-":
        source = sys.stdin.read()
        return DirectInput(source, "<stdin>", "__pyjs_stdin__", "stdin.js")

    path = Path(args.source)
    if not path.is_file():
        command_parser.error(f"cannot open {args.source!r}: no such file")
    source = path.read_text(encoding="utf-8")
    return DirectInput(source, str(path), path.stem.replace("-", "_"), str(path.with_suffix(".js")))


def _compile_direct(program: DirectInput) -> SourceCompilation:
    return compile_source(
        program.source,
        filename=program.filename,
        module_name=program.module_name,
    )


def _executable_javascript(compilation: SourceCompilation) -> str:
    return compilation.javascript + textwrap.dedent("""\
    Promise.resolve(__pyjsEntry__.main()).catch((error) => {
      console.error(error);
      process.exitCode = 1;
    });
    """)


def _direct(args, command_parser: argparse.ArgumentParser) -> int:
    source_only = args.src or args.src_all
    if source_only and args.json:
        command_parser.error("--src and --src-all cannot be combined with --json")
    if source_only and args.perf:
        command_parser.error("--src and --src-all cannot be combined with --perf")
    if args.loops is not None and args.loops <= 0:
        command_parser.error("--loops must be positive")
    if args.samples <= 0 or args.warmups < 0:
        command_parser.error("--samples must be positive and --warmups cannot be negative")

    try:
        program = _direct_input(args, command_parser)
        compilation = _compile_direct(program)
    except CompilationError as error:
        if args.json:
            print(json.dumps({"error": error.diagnostic.to_dict()}, indent=2))
        else:
            print(format_compilation_error(error), file=sys.stderr, end="")
        return 2
    except SyntaxError as error:
        if args.json:
            details = {
                "type": "SyntaxError",
                "message": error.msg,
                "file": error.filename,
                "line": error.lineno,
                "column": error.offset,
                "end_line": error.end_lineno,
                "end_column": error.end_offset,
            }
            print(json.dumps({"error": details}, indent=2))
        else:
            formatted = "".join(traceback.format_exception_only(error))
            print(formatted, file=sys.stderr, end="")
        return 2
    except Exception as error:
        if args.json:
            details = {
                "type": type(error).__name__,
                "message": str(error),
            }
            if args.v:
                details["traceback"] = traceback.format_exc()
            print(json.dumps({"error": details}, indent=2))
            return 2
        if args.v:
            traceback.print_exc()
            print(f"pyjs: error: {error}", file=sys.stderr)
            return 2
        command_parser.error(str(error))

    javascript = _executable_javascript(compilation)
    if source_only:
        _print_sources(
            program,
            compilation,
            include_dependencies=args.src_all,
            headings=args.src_all,
        )
        return 0
    if args.perf:
        return _perf(args, program, compilation, javascript, command_parser)

    node = Node()
    try:
        result = node.run_javascript(javascript)
    except (OSError, RuntimeError) as error:
        command_parser.error(str(error))

    if args.json:
        payload = {
            "input": program.filename,
            "javascript_name": program.javascript_name,
            "node": {"version": node.version, "path": str(node.executable)},
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        if args.v:
            payload["sources"] = _source_files(program, compilation, include_dependencies=False)
        if args.v >= 2:
            payload["compilation"] = _compilation_metadata(compilation, javascript, node)
        if args.v >= 3:
            payload["types"] = _analyzed_types(compilation)
        print(json.dumps(payload, indent=2))
        return result.returncode

    if args.v >= 2:
        _print_compilation(compilation, javascript, node)
    if args.v >= 3:
        _print_section("analyzed types")
        print(_analyzed_types(compilation))
    if args.v:
        _print_sources(program, compilation, include_dependencies=False)
        _print_section(f"node v{node.version} output")
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def _print_section(name: str) -> None:
    print(f"===== {name} =====")


def _compilation_metadata(
    compilation: SourceCompilation, javascript: str, node: Node | None = None
) -> dict:
    metadata = {
        "entry": f"{compilation.entry_point.container.name}.{compilation.entry_point.name}",
        "modules": list(compilation.module_names),
        "transpile_ms": round(compilation.elapsed * 1000, 3),
        "generated_source_bytes": sum(
            len(source.encode()) for source in compilation.sources.values()
        ),
        "executable_bundle_bytes": len(javascript.encode()),
        "runtime_wrapper": "hidden from source display",
    }
    if node is not None:
        metadata.update(node_version=node.version, node_path=str(node.executable))
    return metadata


def _print_compilation(compilation: SourceCompilation, javascript: str, node: Node) -> None:
    _print_section("compilation")
    for name, value in _compilation_metadata(compilation, javascript, node).items():
        if isinstance(value, list):
            value = ", ".join(value)
        print(f"{name}: {value}")


def _analyzed_types(compilation: SourceCompilation) -> str:
    try:
        return compilation.analysis.types
    except Exception as error:
        return f"[type-tree output unavailable: {error}]"


def _source_files(
    program: DirectInput,
    compilation: SourceCompilation,
    *,
    include_dependencies: bool,
) -> dict[str, str]:
    entry_module = compilation.entry_point.container.name
    return {
        program.javascript_name if name == entry_module else f"{name}.js": source
        for name, source in compilation.sources.items()
        if include_dependencies or name == entry_module
    }


def _print_sources(
    program: DirectInput,
    compilation: SourceCompilation,
    *,
    include_dependencies: bool,
    headings: bool = True,
) -> None:
    sources = _source_files(
        program,
        compilation,
        include_dependencies=include_dependencies,
    )
    for index, (name, source) in enumerate(sources.items()):
        if headings:
            if index:
                print()
            _print_section(name)
        print(source, end="" if source.endswith("\n") else "\n")


def _perf(args, program, compilation, javascript, command_parser) -> int:
    node = Node()
    python_entry = compilation.analysis.module.main
    python_stdout, python_stderr, python_error = run_python(python_entry)
    try:
        node_result = node.run_javascript(javascript)
    except (OSError, RuntimeError) as error:
        command_parser.error(str(error))

    if python_error is not None:
        python_stderr += "".join(
            traceback.format_exception(type(python_error), python_error, python_error.__traceback__)
        )
    outputs_match = (
        python_error is None
        and node_result.returncode == 0
        and python_stdout == node_result.stdout
        and python_stderr == node_result.stderr
    )

    try:
        calibration = None
        loops = args.loops
        if loops is None:
            python_loops = calibrate_python(python_entry)
            javascript_loops = _benchmark_javascript(
                node,
                compilation.javascript,
                is_async=compilation.entry_point.is_async,
                loops=None,
                samples=0,
                warmups=0,
            ).loops
            loops = max(python_loops, javascript_loops)
            calibration = {
                "python_loops": python_loops,
                "javascript_loops": javascript_loops,
                "selected_loops": loops,
            }
        python_benchmark = benchmark_python(
            python_entry,
            loops=loops,
            samples=args.samples,
            warmups=args.warmups,
        )
        node_benchmark = _benchmark_javascript(
            node,
            compilation.javascript,
            is_async=compilation.entry_point.is_async,
            loops=loops,
            samples=args.samples,
            warmups=args.warmups,
        )
    except Exception as error:
        command_parser.error(f"performance measurement failed: {error}")

    python_stats = python_benchmark.json()
    node_stats = node_benchmark.json()
    ratio = python_stats["median"] / node_stats["median"]
    payload = {
        "input": program.filename,
        "correctness": {
            "matches": outputs_match,
            "python": {
                "version": sys.version.split()[0],
                "stdout": python_stdout,
                "stderr": python_stderr,
                "exit_code": 0 if python_error is None else 1,
            },
            "node": {
                "version": node.version,
                "stdout": node_result.stdout,
                "stderr": node_result.stderr,
                "exit_code": node_result.returncode,
            },
        },
        "performance": {
            "python": python_stats,
            "javascript": node_stats,
            "python_to_javascript_ratio": ratio,
        },
    }
    if calibration is not None:
        payload["performance"]["calibration"] = calibration
    if args.v:
        payload["sources"] = _source_files(program, compilation, include_dependencies=False)
    if args.v >= 2:
        payload["compilation"] = _compilation_metadata(compilation, javascript, node)
    if args.v >= 3:
        payload["types"] = _analyzed_types(compilation)

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0 if outputs_match else 1

    if args.v >= 2:
        _print_compilation(compilation, javascript, node)
    if args.v >= 3:
        _print_section("analyzed types")
        print(_analyzed_types(compilation))
    if args.v:
        _print_sources(program, compilation, include_dependencies=False)
    _print_section("correctness")
    print(f"outputs match: {'yes' if outputs_match else 'no'}")
    if args.v >= 2 or not outputs_match:
        print(f"python stdout: {python_stdout!r}")
        print(f"node stdout:   {node_result.stdout!r}")
        print(f"python stderr: {python_stderr!r}")
        print(f"node stderr:   {node_result.stderr!r}")
    _print_section("performance")
    if calibration is not None:
        print(
            f"Auto-calibrated {calibration['selected_loops']} common loops "
            f"(Python {calibration['python_loops']}, "
            f"JavaScript {calibration['javascript_loops']})"
        )
    _print_benchmark("Python", python_stats)
    _print_benchmark("JavaScript", node_stats)
    faster = "JavaScript" if ratio > 1 else "Python"
    factor = ratio if ratio > 1 else 1 / ratio
    print(f"{faster} is {factor:.2f}x faster (median per loop)")
    return 0 if outputs_match else 1


def _print_benchmark(name: str, stats: dict) -> None:
    print(
        f"{name}: {stats['median'] * 1e6:.3f} us median "
        f"({stats['loops']} loops x {len(stats['samples'])} samples; "
        f"mean {stats['mean'] * 1e6:.3f} us, "
        f"stdev {stats['stdev'] * 1e6:.3f} us, "
        f"range {stats['min'] * 1e6:.3f}-{stats['max'] * 1e6:.3f} us)"
    )


def _benchmark_javascript(
    node: Node,
    source: str,
    *,
    is_async: bool,
    loops: int | None,
    samples: int,
    warmups: int,
) -> Benchmark:
    benchmark_source = javascript_benchmark(
        source,
        is_async=is_async,
        loops=loops,
        samples=samples,
        warmups=warmups,
    )
    result = node.run_javascript(benchmark_source)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Node benchmark failed")
    marker = next(
        line.removeprefix("__PYJS_PERF__")
        for line in result.stdout.splitlines()
        if line.startswith("__PYJS_PERF__")
    )
    values = json.loads(marker)
    return Benchmark(values["loops"], tuple(values["values"]))


def _build(args, command_parser: argparse.ArgumentParser) -> int:
    if args.module.endswith(".py"):
        suggestion = f"perhaps try: {Path(args.module).stem}"
        command_parser.error(
            f"{args.module} appears to be a Python file; a module name is expected, {suggestion}"
        )

    module_name, entry = args.module, "main"
    if ":" in args.module:
        module_name, entry = args.module.split(":", 1)

    entry_args = []
    if args.args:
        try:
            entry_args = json.loads(args.args)
        except json.JSONDecodeError as error:
            command_parser.error(f"--args must be valid JSON: {error.msg}")
        if not isinstance(entry_args, list):
            command_parser.error("--args must be a JSON list")

    module = importlib.import_module(module_name)
    entry_point = getattr(module, entry)
    file_stem = f"{module_name}.{entry}"

    js_file_name = f"{file_stem}.js"
    print(f"Writing {module_name}:{entry} JavaScript to ./{js_file_name}")
    javascript, css = bundle(entry_point, args.include_main)
    Path(js_file_name).write_text(javascript, encoding="utf-8")

    if args.only_js:
        return 0

    css_file_name = f"{file_stem}.css"
    print(f"Writing {module_name}:{entry} CSS to ./{css_file_name}")
    Path(css_file_name).write_text(css, encoding="utf-8")

    html = page(entry_point(*entry_args), js_file_name, css_file_name, "text/javascript")
    html_file_name = f"{file_stem}.html"
    print(f"Writing {module_name}:{entry} HTML to ./{html_file_name}")
    Path(html_file_name).write_text(html, encoding="utf-8")
    return 0


def _configured_application(command_parser: argparse.ArgumentParser) -> str:
    for directory in (Path.cwd(), *Path.cwd().parents):
        configuration = directory / "pyproject.toml"
        if not configuration.is_file():
            continue
        try:
            project = tomllib.loads(configuration.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            command_parser.error(f"could not read {configuration}: {error}")
        application = project.get("tool", {}).get("pyjs", {}).get("application")
        if not isinstance(application, str) or not application:
            command_parser.error(
                "no application is configured; provide a module or Python file"
            )
        sys.path.insert(0, str(directory))
        return application
    command_parser.error("no application is configured; provide a module or Python file")


def _serve(args, command_parser: argparse.ArgumentParser) -> int:
    target = args.target or _configured_application(command_parser)
    path = Path(target)
    if path.is_file():
        path = path.resolve()
        sys.path.insert(0, str(path.parent))
        serve_application(str(path))
        return 0
    if path.suffix == ".py" or os.sep in target:
        command_parser.error(f"cannot open {target!r}: no such file")
    try:
        spec = importlib.util.find_spec(target)
    except (ImportError, ModuleNotFoundError, ValueError) as error:
        command_parser.error(str(error))
    if spec is None:
        command_parser.error(f"cannot find module {target!r}")
    if spec.submodule_search_locations is not None:
        try:
            main_spec = importlib.util.find_spec(f"{target}.__main__")
        except (ImportError, ModuleNotFoundError, ValueError):
            main_spec = None
        if main_spec is not None:
            runpy.run_module(target, run_name="__main__", alter_sys=True)
            return 0
    serve_application(target)
    return 0


def _create(args, command_parser: argparse.ArgumentParser) -> int:
    try:
        destination = create(
            args.name,
            args.destination,
            template=args.template,
            single_file=args.single_file,
            src_layout=args.src_layout,
        )
    except (FileExistsError, OSError, ValueError) as error:
        command_parser.error(str(error))

    if args.single_file:
        print(f"Created PyJS application at {destination}")
        print()
        print(f"  python {destination}")
        return 0

    print(f"Created PyJS project in {destination}")
    print()
    if Path.cwd().resolve() != destination:
        print(f"  cd {destination}")
    print('  python -m pip install -e ".[test]"')
    if args.template is None:
        print(f"  python -m {args.name}")
        print()
        print("Or run directly with PyJS (including the npm distribution):")
        print()
        print("  pyjs serve")
    else:
        print("  See README.md for the run command")
    return 0


def _template_javascript(template: Template) -> str:
    module_name = template.name
    if template.kind == "directory":
        module_name += f".{template.primary_module}"
    module = importlib.import_module(module_name)
    package, entry_point, _ = prepare_bundle(
        module.main,
        include_main=True,
        include_css=False,
    )
    return package[entry_point.container.name]


def _template(args, command_parser: argparse.ArgumentParser) -> int:
    if args.name is not None:
        if args.json:
            command_parser.error("--json cannot be combined with a template name")
        try:
            template = find_template(args.name)
        except ValueError as error:
            command_parser.error(str(error))
        if args.src:
            try:
                source = _template_javascript(template)
            except Exception as error:
                command_parser.error(f"could not transpile template {template.name!r}: {error}")
            print(f"===== {template.primary_module}.js =====")
            print(source, end="" if source.endswith("\n") else "\n")
            return 0
        sources = template_sources(template)
        for index, (name, content) in enumerate(sources):
            if index:
                print()
            print(f"===== {name} =====")
            if content is None:
                print("[binary file omitted]")
            else:
                print(content, end="" if content.endswith("\n") else "\n")
        return 0

    if args.src:
        command_parser.error("--src requires a template name")

    catalog = templates()
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "name": template.name,
                        "title": template.title,
                        "description": template.description,
                        "kind": template.kind,
                    }
                    for template in catalog
                ],
                indent=2,
            )
        )
        return 0

    if not catalog:
        print("No PyJS templates are installed.")
        print()
        print("Install the official templates with:")
        print()
        print("  python -m pip install pyjs-examples")
        return 0

    width = max(
        (len(template.name) for template in catalog),
        default=len("Template"),
    )
    description_indent = width + 10
    description_width = max(
        20,
        shutil.get_terminal_size(fallback=(100, 24)).columns - description_indent,
    )
    print(f"  {'Template':<{width}}  {'Type':<4}  Description")
    for template in catalog:
        description = textwrap.wrap(template.description, width=description_width) or [""]
        kind = "dir" if template.kind == "directory" else template.kind
        print(f"  {template.name:<{width}}  {kind:<4}  {description[0]}")
        for line in description[1:]:
            print(f"{'':<{description_indent}}{line}")
    return 0


def _skill() -> int:
    skill = resources.files("pyjs").joinpath("skills", "pyjs", "SKILL.md")
    content = skill.read_text(encoding="utf-8")
    print(content, end="" if content.endswith("\n") else "\n")
    return 0


def _inspect(args, command_parser: argparse.ArgumentParser) -> int:
    if args.width <= 0 or args.height <= 0 or args.scale <= 0:
        command_parser.error("--width, --height, and --scale must be positive")
    if args.delay < 0 or args.frames < 0:
        command_parser.error("--delay and --frames cannot be negative")
    if (args.interval is None) != (args.duration is None):
        command_parser.error("--interval and --duration must be used together")
    if args.interval is not None and (args.interval <= 0 or args.duration <= 0):
        command_parser.error("--interval and --duration must be positive")

    try:
        result = asyncio.run(
            capture_url(
                args.url,
                args.output,
                width=args.width,
                height=args.height,
                scale=args.scale,
                color_scheme=args.color_scheme,
                wait_for_selector=args.wait_for,
                selector=args.selector,
                delay=args.delay,
                frames=args.frames,
                full_page=args.full_page,
                settle=not args.no_settle,
                interval=args.interval,
                duration=args.duration,
                headed=args.headed,
            )
        )
    except (ConnectionError, OSError, RuntimeError, TimeoutError) as error:
        command_parser.error(str(error))

    if args.json:
        print(json.dumps(result.json(), indent=2))
    else:
        for screenshot in result.screenshots:
            print(f"Saved screenshot: {screenshot}")
        print(f"Saved diagnostics: {result.diagnostics}")
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, os.getcwd())
    argv = list(sys.argv[1:] if argv is None else argv)
    if _is_direct_invocation(argv):
        command_parser = direct_parser()
        return _direct(command_parser.parse_args(argv), command_parser)
    command_parser = parser()
    args = command_parser.parse_args(argv)
    if args.command is None:
        command_parser.print_help()
        return 0
    if args.command == "build":
        return _build(args, command_parser)
    if args.command == "serve":
        return _serve(args, command_parser)
    if args.command == "create":
        return _create(args, command_parser)
    if args.command == "template":
        return _template(args, command_parser)
    if args.command == "inspect":
        return _inspect(args, command_parser)
    if args.command == "skill":
        return _skill()
    if args.command == "docs":
        return run_docs(args)
    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
