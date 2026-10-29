"""Serializable editor information from the compiler's existing module graph."""

import ast
import hashlib
import inspect
import io
import tokenize
import unicodedata
from pathlib import Path

from pyjs.analysis.objects import Class, Function, Instance, Module


def type_text(value) -> str:
    if value is None:
        return "unknown"
    try:
        text = ast.unparse(value.annotation)
        return text.replace("NoneType", "None")
    except (AttributeError, ValueError, TypeError):
        return value.name


def functions(container, seen=None):
    seen = set() if seen is None else seen
    values = list(container.scope.names.values())
    if isinstance(container, Class):
        values.extend(container.internal_scope.names.values())
    for value in values:
        if id(value) in seen or value.container is not container:
            continue
        seen.add(id(value))
        if isinstance(value, Class):
            yield from functions(value, seen)
        elif isinstance(value, Function) and value.is_analyzed and not value.has_synthetic_source:
            yield value


def collect(entry: Function, root: Path, sources: dict[str, str], synthetic: str) -> dict:
    definitions = {}
    parameter_definitions = {}
    signatures = {}
    documentation = {}
    snapshots = {}
    file_lines = {path: text.splitlines() for path, text in sources.items()}
    declaration_names = {}
    name_starts = {}
    name_ends = {}
    for path, text in sources.items():
        keyword_line = 0
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.NAME:
                name_starts[path, *token.start] = token
                name_ends[path, *token.end] = token
            if keyword_line and token.type == tokenize.NAME:
                declaration_names[path, keyword_line, unicodedata.normalize('NFKC', token.string)] = token
                keyword_line = 0
            elif token.type == tokenize.NAME and token.string in ('def', 'class'):
                keyword_line = token.start[0]
    resolved_paths = {}
    type_labels = {}

    def label(value):
        if value not in type_labels:
            type_labels[value] = type_text(value)
        return type_labels[value]

    def resolve(filename):
        if filename not in resolved_paths:
            resolved_paths[filename] = str(Path(filename).resolve())
        return resolved_paths[filename]

    modules = []
    for module in entry.container.container.values():
        if not isinstance(module, Module):
            continue
        filename = getattr(module.py_module, "__file__", None)
        if not filename:
            continue
        path = resolve(filename)
        if path not in sources:
            continue
        modules.append((module, path))
        snapshots[path] = {"status": "ready", "message": "", "symbols": [], "occurrences": [],
                           "sourceHash": hashlib.sha256(sources[path].encode()).hexdigest()}

    def location(fragment, node):
        path = resolve(fragment.source.filename)
        line = node.lineno + fragment.line_delta
        end_line = (getattr(node, "end_lineno", None) or node.lineno) + fragment.line_delta
        lines = file_lines.get(path, [])
        def column(row, byte):
            if not 0 < row <= len(lines):
                return 0
            return len(lines[row - 1].encode()[:byte].decode("utf-8", errors="replace"))
        return path, {"line": line, "column": column(line, node.col_offset + fragment.column_delta),
                      "endLine": end_line,
                      "endColumn": column(end_line, (getattr(node, "end_col_offset", None) or node.col_offset + 1) + fragment.column_delta)}

    def definition(path, line, column=0):
        return {"definitionPath": Path(path).relative_to(root).as_posix(),
                "definitionLine": line, "definitionColumn": column}

    all_functions = []
    for module, path in modules:
        snapshot = snapshots[path]
        tree = ast.parse(sources[path], path)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                value = module.scope.names.get(node.name)
                if value is not None:
                    definitions[id(value)] = definition(path, *declaration_names[path, node.lineno, node.name].start)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            for target in targets:
                if isinstance(target, ast.Name):
                    value = vars(module.py_module).get(target.id)
                    modeled = module.scope.names.get(target.id)
                    if modeled is not None:
                        definitions[id(modeled)] = definition(path, target.lineno, target.col_offset)
                    if target.id in vars(module.py_module) and not inspect.ismodule(value):
                        snapshot["symbols"].append({"name": target.id, "type": type(value).__name__,
                                                    "kind": "global", "line": target.lineno})
        for function in functions(module):
            if function.name == synthetic or function.source_fragment is None:
                continue
            fragment = function.source_fragment
            actual = resolve(fragment.source.filename)
            if actual != path:
                continue
            node = function.original_node
            line = node.lineno + fragment.line_delta
            declaration = declaration_names[path, line, function.name]
            definitions[id(function)] = definition(path, *declaration.start)
            bindings = parameter_definitions[id(function)] = {}
            qualified = function.cls.name + "." + function.name if function.cls is not None else function.name
            positional = [*node.args.posonlyargs, *node.args.args]
            defaults = {argument.arg: ast.unparse(default) for argument, default in
                        zip(positional[len(positional) - len(node.args.defaults):], node.args.defaults, strict=True)}
            defaults.update({argument.arg: ast.unparse(default) for argument, default in
                             zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True) if default is not None})
            def parameter_text(parameter, prefix="", defaults=defaults):
                text = ast.unparse(parameter.annotation).replace("NoneType", "None") if parameter.annotation else "unknown"
                return prefix + parameter.arg + ": " + text + (" = " + defaults[parameter.arg] if parameter.arg in defaults else "")

            parameters = []
            for index, parameter in enumerate(function.params):
                parameters.append(parameter_text(parameter))
                if index + 1 == len(node.args.posonlyargs):
                    parameters.append("/")
            if function.vararg is not None:
                parameters.append(parameter_text(function.vararg, "*"))
            elif function.kwonlyargs:
                parameters.append("*")
            parameters.extend(parameter_text(parameter) for parameter in function.kwonlyargs)
            if function.kwarg is not None:
                parameters.append(parameter_text(function.kwarg, "**"))
            signature = qualified + "(" + ", ".join(parameters) + ") -> " + label(function.return_type)
            signatures[id(function)] = signature
            documentation[id(function)] = (inspect.getdoc(function.py_func) or "")[:2000]
            snapshot["symbols"].append({"name": qualified, "type": signature, "kind": "function", "line": line})
            start = definitions[id(function)]["definitionColumn"]
            snapshot["occurrences"].append({"name": function.name, "type": label(function.return_type),
                "kind": "function", "line": definitions[id(function)]["definitionLine"],
                "column": start, "endLine": definitions[id(function)]["definitionLine"],
                "endColumn": declaration.end[1], "signature": signature,
                "documentation": documentation[id(function)], "hint": False, **definitions[id(function)]})
            for parameter in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                              *([node.args.vararg] if node.args.vararg else []),
                              *([node.args.kwarg] if node.args.kwarg else [])):
                value = function.scope.names.get(parameter.arg)
                if value is not None and hasattr(parameter, "lineno"):
                    _, span = location(fragment, parameter)
                    bindings[parameter.arg] = definition(path, span["line"], span["column"])
                    value_type = label(value.type)
                    snapshot["occurrences"].append({"name": parameter.arg, "type": value_type, "kind": "parameter",
                        **span, "endLine": span["line"],
                        "endColumn": name_starts[path, span['line'], span['column']].end[1],
                        "signature": parameter.arg + ": " + value_type, "documentation": "Parameter of " + signature,
                        "hint": False, **bindings[parameter.arg]})
            body = function.node
            references = []
            for item in ast.walk(body):
                if isinstance(item, (ast.Name, ast.Attribute)):
                    references.append(item)
                if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store) and hasattr(item, "lineno"):
                    value = getattr(item, "obj", None)
                    if value is not None:
                        _, span = location(fragment, item)
                        definitions.setdefault(id(value), definition(path, span["line"], span["column"]))
            all_functions.append((function, references, path))

    for function, references, path in all_functions:
        snapshot = snapshots[path]
        fragment = function.source_fragment
        original = function.original_node
        bindings = parameter_definitions[id(function)]
        annotation_lines = {node.lineno + fragment.line_delta for node in ast.walk(original)
                            if isinstance(node, ast.AnnAssign)}
        for node in references:
            if not hasattr(node, "lineno") or not hasattr(node, "col_offset"):
                continue
            value = getattr(node, "obj", None)
            if not isinstance(value, (Instance, Function, Class)):
                continue
            _, span = location(fragment, node)
            name = node.id if isinstance(node, ast.Name) else node.attr
            if isinstance(node, ast.Attribute):
                span["line"] = span["endLine"]
                token = name_ends.get((path, span['line'], span['endColumn']))
                span["column"] = token.start[1] if token is not None else span["endColumn"] - len(name)
            if span["column"] < 0 or span["line"] < 1 or span["line"] > len(file_lines[path]):
                continue
            if unicodedata.normalize('NFKC', file_lines[path][span["line"] - 1][span["column"]:span["endColumn"]]) != name:
                continue
            kind = "function" if isinstance(value, Function) else "class" if isinstance(value, Class) else "variable"
            value_type = label(value if isinstance(value, Class) else value.type)
            hint = isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and span["line"] not in annotation_lines
            target = bindings.get(name) if isinstance(node, ast.Name) and name in bindings else definitions.get(id(value))
            snapshot["occurrences"].append({"name": name, "type": value_type, "kind": kind, **span,
                "signature": signatures.get(id(value), name + ": " + value_type),
                "documentation": documentation.get(id(value), ""), "hint": hint,
                **(target or {"definitionPath": "", "definitionLine": 0, "definitionColumn": 0})})
    for snapshot in snapshots.values():
        snapshot["symbols"].sort(key=lambda item: (item["line"], item["name"]))
        unique = {(item["line"], item["column"], item["endLine"], item["endColumn"]): item for item in snapshot["occurrences"]}
        snapshot["occurrences"] = sorted(unique.values(), key=lambda item: (item["line"], item["column"]))
    return snapshots
