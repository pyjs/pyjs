"""Presentation metadata for complete runnable artifacts, without changing them."""
import ast
import gzip
import hashlib
import re
from pathlib import Path


def program_files(target, directory):
    if target == "cpython":
        return [directory / "program.py", directory / "driver.py"]
    if target in {"javascript", "pyjs-js"}:
        return [directory / "program.cjs"]
    if target in {"java", "pyjs-jvm"}:
        return sorted(directory.glob("*.class"))
    return [directory / "program"]


def code_size(target, directory):
    """Full benchmark program, including adapters/support; excluding installed VMs."""
    files = program_files(target, directory)
    if not files or any(not path.is_file() for path in files):
        return None
    result = {"bytes": sum(path.stat().st_size for path in files),
              "files": [path.name for path in files]}
    if target in {"javascript", "pyjs-js"}:
        result["gzip_bytes"] = len(gzip.compress(files[0].read_bytes(), mtime=0))
    return result


def recorded_code_size(row, root):
    """Enrich older snapshots only from their own retained, size-matching artifacts."""
    directory = root / "build" / row["case"] / row["target"]
    if not directory.resolve().is_relative_to(root.resolve()):
        return None
    files = program_files(row["target"], directory)
    if not files or any(not path.resolve().is_relative_to(root.resolve()) or
                        not path.is_file() or row.get("artifacts", {}).get(str(path.relative_to(root))) != path.stat().st_size
                        for path in files):
        return None
    return code_size(row["target"], directory)


def algorithm_names(source):
    tree = ast.parse(source)
    functions = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    methods = {f"{node.name}.{method.name}" for node in tree.body if isinstance(node, ast.ClassDef)
               for method in node.body if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return functions, classes, methods


def merge_ranges(ranges):
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        elif start < end:
            merged.append((start, end))
    return merged


def javascript_ranges(source_map, source):
    """Use compiler scope provenance, not brace counting or minifier heuristics."""
    functions, classes, methods = algorithm_names(source)
    names = functions | classes | methods
    return merge_ranges((scope.start_line, scope.end_line + 1)
                        for scope in source_map.generated_scopes
                        if scope.scope.source.filename == "workload.py" and scope.scope.name in names)


def algorithm_ranges(source, target, text):
    """Recognize whole declarations in retained compiler output; otherwise unfold it.

    This fallback supports older snapshots without source-map metadata. It never
    strips instructions inside an algorithm function, including runtime checks.
    """
    functions, classes, methods = algorithm_names(source)
    lines = text.split("\n")
    ranges = []
    if target == "pyjs-js":
        # Only declarations inside the workload module, delimited by its exports.
        in_workload = False
        start = None
        for index, line in enumerate(lines):
            if line.startswith("define("):
                in_workload = line.startswith("define('perf_workload',")
                start = None
            if not in_workload:
                continue
            match = re.match(r"(?:function|class) ([\w$]+)[( {]", line)
            if match and match[1] in functions | classes:
                start = index
            if start is not None and line.startswith("__export_js__."):
                ranges.append((start, index))
                start = None
    elif target == "pyjs-llvm":
        start = None
        for index, line in enumerate(lines):
            match = re.match(r"define .*@fn\.([^ (]+)\(", line)
            if match:
                start = index if match[1] in functions | methods else None
            if start is not None and line == "}":
                ranges.append((start, index + 1))
                start = None
    elif target == "pyjs-jvm":
        owner = ""
        start = None
        for index, line in enumerate(lines):
            if line.startswith("Classfile "):
                owner = Path(line.removeprefix("Classfile ")).stem
            if owner in {"PyjsProgram$" + name for name in classes}:
                if line == "{":
                    start = index
                elif line == "}" and start is not None:
                    ranges.append((start, index + 1))
                    start = None
            elif owner == "PyjsProgram":
                match = re.match(r"  (?:public|private|protected).* ([\w$]+)\(", line)
                if match or line == "}":
                    if start is not None:
                        ranges.append((start, index))
                    start = index if match and match[1] in functions else None
    return merge_ranges(ranges)


def fold_header(source, target, text, metadata=None):
    digest = hashlib.sha256(text.encode()).hexdigest()
    if metadata and metadata.get("sha256") == digest:
        ranges = metadata["ranges"]
    else:
        ranges = algorithm_ranges(source, target, text)
    return ";".join(f"{start}:{end}" for start, end in ranges)
