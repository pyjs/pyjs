import ast
import bisect
import difflib
import inspect
import linecache
import sys
import textwrap
import traceback
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Never

from pyjs.decorators import is_js_enabled


def describe_type(value_type) -> str:
    """Keep valid annotation spelling, adding contracts it cannot express."""
    from .objects import CallableClass, RecursiveTypeAlias, UnionType

    notes, seen, pending = [], set(), [("", value_type)]
    while pending:
        path, value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, CallableClass):
            prefix = f"{path}: " if path else ""
            if value.parameter_types is not None:
                maximum = len(value.parameter_types)
                if value.minimum_arguments > maximum:
                    # Intersecting union domains can leave fewer compatible
                    # positions than any accepted call requires. Not a range.
                    notes.append(f"{prefix}no compatible positional arity "
                                 f"(requires {value.minimum_arguments}, common typed prefix {maximum})")
                elif value.minimum_arguments < maximum:
                    notes.append(f"{prefix}accepts {value.minimum_arguments} to "
                                 f"{maximum} positional arguments")
            if value.required_keywords:
                notes.append(f"{prefix}requires keyword-only arguments: {', '.join(value.required_keywords)}")
            children = [(f"parameter {index + 1}", member)
                        for index, member in enumerate(value.parameter_types or ())]
            children.append(("return", value.return_type))
        elif isinstance(value, RecursiveTypeAlias):
            continue  # A named cycle edge stays named in the diagnostic too.
        elif isinstance(value, UnionType):
            children = [(f"alternative {index + 1}", member) for index, member in enumerate(value.types)]
        else:
            children = list((getattr(value, "generic_types", None) or {}).items())
        pending.extend((f"{path}.{name}" if path else name, member) for name, member in reversed(children))
    annotation = value_type.to_annotation_str()
    return annotation + (f" ({'; '.join(notes)})" if notes else "")


def _inferable_js_value(value: object) -> bool:
    if isinstance(value, (bool, int, float, str, type(None))):
        return True
    if isinstance(value, (list, tuple)):
        return bool(value) and all(_inferable_js_value(item) for item in value)
    if isinstance(value, dict):
        return bool(value) and all(
            _inferable_js_value(key) and _inferable_js_value(item)
            for key, item in value.items()
        )
    return False


def _source_assignment(source: str, name: str) -> tuple[ast.expr, object] | None:
    try:
        module = ast.parse(source)
    except SyntaxError:
        return None
    for statement in module.body:
        value = None
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            value = statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
        ):
            value = statement.value
        if value is None:
            continue
        try:
            return value, ast.literal_eval(value)
        except (TypeError, ValueError):
            return None
    return None


def _client_binding_help(name: str, value: object) -> str:
    if type(value) in (bool, int, float, type(None)):
        try:
            is_literal = ast.literal_eval(repr(value)) == value
        except (SyntaxError, ValueError):
            is_literal = False
        if is_literal:
            return (
                "Import JS from pyjs and declare it as a client value: "
                f"{name}: JS = {value!r}."
            )
    return (
        "Import JS from pyjs and annotate the existing assignment with JS "
        "so its value is available to client code."
    )


def _external_definition(value: object) -> bool:
    module_name = getattr(value, "__module__", "")
    if module_name.partition(".")[0] in sys.stdlib_module_names:
        return True
    try:
        filename = inspect.getsourcefile(value)
    except TypeError:
        return True
    return filename is not None and any(
        part in {"site-packages", "dist-packages"}
        for part in Path(filename).parts
    )


class DiagnosticCode(StrEnum):
    UNDEFINED_NAME = "PYJS1001"
    MISSING_JS_DECORATOR = "PYJS1002"
    UNDEFINED_ATTRIBUTE = "PYJS1003"
    MISSING_JS_BINDING = "PYJS1004"
    UNDEFINED_KEY = "PYJS1005"
    TYPE_ANNOTATION_REQUIRED = "PYJS1101"
    INCOMPATIBLE_ASSIGNMENT = "PYJS1103"
    INCOMPATIBLE_ARGUMENT = "PYJS1104"
    INCOMPATIBLE_RETURN = "PYJS1105"
    UNSUPPORTED_SYNTAX = "PYJS2001"
    INVALID_INLINE_DEPENDENCY = "PYJS2002"
    INLINE_FUNCTION_VALUE = "PYJS2003"
    UNSUPPORTED_CLIENT_RESULT = "PYJS2004"


@dataclass(frozen=True)
class SourcePosition:
    line: int
    column: int


@dataclass(frozen=True)
class SourceFile:
    filename: str
    text: str
    line_starts: tuple[int, ...]

    @classmethod
    def from_text(cls, filename: str, text: str):
        starts = [0]
        offset = 0
        for line in text.splitlines(keepends=True)[:-1]:
            offset += len(line.encode("utf-8"))
            starts.append(offset)
        return cls(filename, text, tuple(starts))

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines(keepends=True)

    def offset(self, line: int, column: int) -> int:
        if line < 1:
            return 0
        line_index = min(line - 1, len(self.line_starts) - 1)
        return self.line_starts[line_index] + column

    def position(self, offset: int) -> SourcePosition:
        line_index = bisect.bisect_right(self.line_starts, offset) - 1
        return SourcePosition(line_index, offset - self.line_starts[line_index])

    def line_text(self, line: int) -> str:
        lines = self.lines
        if not 1 <= line <= len(lines):
            return ""
        return lines[line - 1]

    def character_column(self, line: int, byte_column: int) -> int:
        text = self.line_text(line).encode("utf-8")[:byte_column]
        return len(text.decode("utf-8", errors="replace"))


@dataclass(frozen=True)
class SourceSpan:
    source: SourceFile
    start: int
    end: int

    @property
    def start_position(self) -> SourcePosition:
        return self.source.position(self.start)

    @property
    def end_position(self) -> SourcePosition:
        return self.source.position(self.end)


@dataclass(frozen=True)
class SourceFragment:
    source: SourceFile
    line_delta: int = 0
    column_delta: int = 0

    def span(self, node: ast.AST) -> SourceSpan:
        line = getattr(node, "lineno", 1) + self.line_delta
        end_line = getattr(node, "end_lineno", None) or line - self.line_delta
        end_line += self.line_delta
        column = max(0, getattr(node, "col_offset", 0) + self.column_delta)
        end_column = getattr(node, "end_col_offset", None)
        if end_column is None:
            end_column = column + 1
        else:
            end_column = max(column + 1, end_column + self.column_delta)
        return SourceSpan(
            self.source,
            self.source.offset(line, column),
            self.source.offset(end_line, end_column),
        )


@dataclass(frozen=True)
class Label:
    span: SourceSpan
    message: str | None = None
    primary: bool = False


@dataclass(frozen=True)
class Diagnostic:
    code: DiagnosticCode
    message: str
    primary: Label
    secondary: tuple[Label, ...] = ()
    notes: tuple[str, ...] = ()
    help: tuple[str, ...] = ()
    severity: str = "error"

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "primary": label_to_dict(self.primary),
            "secondary": [label_to_dict(label) for label in self.secondary],
            "notes": list(self.notes),
            "help": list(self.help),
        }


def label_to_dict(label: Label) -> dict[str, object]:
    start = label.span.start_position
    end = label.span.end_position
    source = label.span.source
    return {
        "file": source.filename,
        "start": {
            "line": start.line,
            "column": source.character_column(start.line + 1, start.column),
        },
        "end": {
            "line": end.line,
            "column": source.character_column(end.line + 1, end.column),
        },
        "message": label.message,
    }


class CompilationError(SyntaxError):
    def __init__(self, diagnostic: Diagnostic):
        self.diagnostic = diagnostic
        span = diagnostic.primary.span
        start = span.start_position
        end = span.end_position
        source = span.source
        line = start.line + 1
        end_line = end.line + 1
        offset = source.character_column(line, start.column) + 1
        end_offset = source.character_column(end_line, end.column) + 1
        message = f"{diagnostic.message} [{diagnostic.code}]"
        super().__init__(
            message,
            (
                source.filename,
                line,
                offset,
                source.line_text(line),
                end_line,
                end_offset,
            ),
        )
        for label in diagnostic.secondary:
            position = label.span.start_position
            detail = label.message or "related location"
            column = label.span.source.character_column(
                position.line + 1,
                position.column,
            )
            self.add_note(
                f"note: {label.span.source.filename}:{position.line + 1}:"
                f"{column + 1}: {detail}"
            )
        for note in diagnostic.notes:
            self.add_note(f"note: {note}")
        for help_text in diagnostic.help:
            self.add_note(f"help: {help_text}")


def format_compilation_error(error: CompilationError) -> str:
    rendered = "".join(traceback.format_exception_only(error))
    qualified_name = f"{CompilationError.__module__}.{CompilationError.__qualname__}:"
    return "".join(
        line.replace(qualified_name, "pyjs.CompilationError:", 1)
        if line.startswith(qualified_name)
        else line
        for line in rendered.splitlines(keepends=True)
    )


class SourceManager:
    def __init__(self):
        self.files: dict[str, SourceFile] = {}

    def register(self, filename: str, text: str | None = None) -> SourceFile:
        filename = str(filename)
        if source := self.files.get(filename):
            return source
        if text is None:
            lines = linecache.getlines(filename)
            if lines:
                text = "".join(lines)
            else:
                try:
                    text = Path(filename).read_text(encoding="utf-8")
                except OSError:
                    text = ""
        source = SourceFile.from_text(filename, text)
        self.files[filename] = source
        return source

    def fragment_for(self, obj: object, line_delta: int = 0) -> SourceFragment:
        obj = getattr(obj, "__func__", obj)
        obj = inspect.unwrap(obj)
        filename = inspect.getsourcefile(obj) or inspect.getfile(obj)
        return SourceFragment(self.register(filename), line_delta)

    def definition_span(self, obj: object) -> SourceSpan | None:
        obj = getattr(obj, "__func__", obj)
        obj = inspect.unwrap(obj)
        try:
            lines, start_line = inspect.getsourcelines(obj)
            filename = inspect.getsourcefile(obj) or inspect.getfile(obj)
        except (OSError, TypeError):
            return None
        source = self.register(filename)
        try:
            module = ast.parse(textwrap.dedent("".join(lines)))
        except SyntaxError:
            return None
        definition = next(
            (
                node
                for node in module.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ),
            None,
        )
        if definition is None:
            return None
        line = start_line + definition.lineno - 1
        source_line = source.line_text(line)
        name = getattr(obj, "__name__", "")
        column = source_line.find(name)
        if column < 0:
            column = definition.col_offset
        byte_column = len(source_line[:column].encode("utf-8"))
        return SourceSpan(
            source,
            source.offset(line, byte_column),
            source.offset(line, byte_column + len(name.encode("utf-8"))),
        )


@dataclass
class CompilationContext:
    sources: SourceManager = field(default_factory=SourceManager)

    def error(
        self,
        fragment: SourceFragment,
        node: ast.AST,
        code: DiagnosticCode,
        message: str,
        *,
        label: str | None = None,
        help: str | None = None,
        secondary: tuple[Label, ...] = (),
    ) -> Never:
        diagnostic = Diagnostic(
            code,
            message,
            Label(fragment.span(node), label, primary=True),
            secondary=secondary,
            help=(help,) if help else (),
        )
        raise CompilationError(diagnostic)

    def definition_error(
        self,
        obj: object,
        code: DiagnosticCode,
        message: str,
        *,
        help: str | None = None,
    ) -> Never:
        span = self.sources.definition_span(obj)
        if span is None:
            raise TypeError(message)
        raise CompilationError(
            Diagnostic(
                code,
                message,
                Label(span, primary=True),
                help=(help,) if help else (),
            )
        )

    def name_lookup_error(
        self,
        fragment: SourceFragment,
        node: ast.Name,
        namespace: object,
        visible_names: set[str],
    ) -> Never:
        missing = object()
        values = vars(namespace)
        python_value = values.get(node.id, missing)
        if python_value is not missing and (
            inspect.isfunction(python_value) or inspect.isclass(python_value)
        ):
            kind = "Class" if inspect.isclass(python_value) else "Function"
            nojs = is_js_enabled(python_value) is False
            external = _external_definition(python_value)
            if external:
                module_name = getattr(python_value, "__module__", "")
                help_text = (
                    f"{node.id!r} comes from external module {module_name!r}. "
                    "Use a supported PyJS API or add a client binding for that "
                    "library."
                )
            elif nojs:
                help_text = (
                    f"Remove @nojs from {node.id!r} if it should run in the browser."
                )
            elif "js" in values:
                help_text = f"Decorate {node.id!r} with @js."
            else:
                help_text = (
                    f"Import js from pyjs and decorate {node.id!r} with @js."
                )
            definition = self.sources.definition_span(python_value)
            secondary = (
                (Label(definition, "defined here without client compilation enabled"),)
                if definition is not None and not external
                else ()
            )
            self.error(
                fragment,
                node,
                DiagnosticCode.MISSING_JS_DECORATOR,
                f"{kind} {node.id!r} is not available to client code",
                secondary=secondary,
                help=help_text,
            )
        if python_value is not missing:
            if _inferable_js_value(python_value):
                help_text = _client_binding_help(node.id, python_value)
            else:
                help_text = (
                    f"Annotate {node.id!r} with JS[...] if it is needed by "
                    "client code."
                )
            self.error(
                fragment,
                node,
                DiagnosticCode.MISSING_JS_BINDING,
                f"Name {node.id!r} is a Python value, not a client value",
                help=help_text,
            )
        original_source = getattr(
            namespace,
            "__pyjs_original_source__",
            fragment.source.text,
        )
        source_assignment = _source_assignment(original_source, node.id)
        if source_assignment is not None:
            _, value = source_assignment
            if _inferable_js_value(value):
                self.error(
                    fragment,
                    node,
                    DiagnosticCode.MISSING_JS_BINDING,
                    f"Name {node.id!r} is a Python value, not a client value",
                    help=_client_binding_help(node.id, value),
                )
        close_names = difflib.get_close_matches(
            node.id,
            sorted(visible_names),
            n=1,
            cutoff=0.75,
        )
        self.error(
            fragment,
            node,
            DiagnosticCode.UNDEFINED_NAME,
            f"Name {node.id!r} is not defined",
            help=f"Did you mean {close_names[0]!r}?" if close_names else None,
        )

    def attribute_lookup_error(
        self,
        fragment: SourceFragment,
        node: ast.Attribute,
        class_name: str,
        available_names: set[str],
        receiver: str,
        initializer: object | None,
        *,
        can_define: bool,
    ) -> Never:
        close_names = difflib.get_close_matches(
            node.attr,
            sorted(available_names),
            n=1,
            cutoff=0.75,
        )
        suggestion = None
        if close_names:
            suggestion = close_names[0]
            if isinstance(node.value, (ast.Name, ast.Attribute)):
                suggestion = f"{receiver}.{suggestion}"
        help_text = (
            f"Did you mean {suggestion!r}?"
            if suggestion is not None
            else (
                f"Define self.{node.attr} in {class_name}.__init__()."
                if can_define
                else (
                    f"Use an attribute supported by PyJS for {class_name!r} or "
                    "implement an equivalent client helper."
                )
            )
        )
        definition = (
            self.sources.definition_span(initializer)
            if initializer is not None
            else None
        )
        secondary = (
            (Label(definition, "initialize instance attributes here"),)
            if definition is not None
            else ()
        )
        self.error(
            fragment,
            node,
            DiagnosticCode.UNDEFINED_ATTRIBUTE,
            f"Attribute {node.attr!r} is not defined on {class_name!r}",
            secondary=secondary,
            help=help_text,
        )
