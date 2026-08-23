import json
import re
from dataclasses import dataclass, replace

from .diagnostics import SourceFile

BASE64_DIGITS = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
)


def utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def encode_vlq(value: int) -> str:
    value = ((-value) << 1 | 1) if value < 0 else value << 1
    encoded = []
    while True:
        digit = value & 31
        value >>= 5
        if value:
            digit |= 32
        encoded.append(BASE64_DIGITS[digit])
        if not value:
            return "".join(encoded)


def encode_unsigned_vlq(value: int) -> str:
    encoded = []
    while True:
        digit = value & 31
        value >>= 5
        if value:
            digit |= 32
        encoded.append(BASE64_DIGITS[digit])
        if not value:
            return "".join(encoded)


@dataclass(frozen=True)
class SourceMapping:
    generated_line: int
    generated_column: int
    source: SourceFile
    original_line: int
    original_column: int
    name: str | None = None

    def shifted(self, line: int, column: int = 0) -> SourceMapping:
        generated_column = self.generated_column
        if self.generated_line == 0:
            generated_column += column
        return replace(
            self,
            generated_line=self.generated_line + line,
            generated_column=generated_column,
        )


@dataclass(frozen=True)
class SourceScope:
    source: SourceFile
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    name: str
    variables: tuple[str, ...]
    kind: str = "Function"


@dataclass(frozen=True)
class GeneratedScope:
    scope: SourceScope
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    values: tuple[str | None, ...]

    def shifted(self, line: int, column: int = 0) -> GeneratedScope:
        start_column = (
            self.start_column + column if self.start_line == 0 else self.start_column
        )
        end_column = (
            self.end_column + column if self.end_line == 0 else self.end_column
        )
        return replace(
            self,
            start_line=self.start_line + line,
            start_column=start_column,
            end_line=self.end_line + line,
            end_column=end_column,
        )


def _position(scope, prefix: str) -> tuple[int, int]:
    return getattr(scope, f"{prefix}_line"), getattr(scope, f"{prefix}_column")


def _nested_ranges(values):
    children = {value: [] for value in values}
    roots = []
    stack = []
    for value in sorted(
        values,
        key=lambda item: (*_position(item, "start"), -_position(item, "end")[0]),
    ):
        while stack and _position(value, "start") >= _position(stack[-1], "end"):
            stack.pop()
        if stack and _position(value, "end") <= _position(stack[-1], "end"):
            children[stack[-1]].append(value)
        else:
            roots.append(value)
        stack.append(value)
    return roots, children


def encode_scopes(
    sources: list[str],
    names: list[str],
    scopes: tuple[SourceScope, ...],
    generated_scopes: tuple[GeneratedScope, ...],
) -> str:
    name_indexes = {name: index for index, name in enumerate(names)}

    def name_index(name: str) -> int:
        if name not in name_indexes:
            name_indexes[name] = len(names)
            names.append(name)
        return name_indexes[name]

    encoded = []
    scope_indexes = {}
    scope_count = 0

    def encode_source_scopes(
        source: SourceFile,
        roots: list[SourceScope],
        children: dict[SourceScope, list[SourceScope]],
    ) -> None:
        nonlocal scope_count
        lines = source.text.splitlines(keepends=True)
        end_line = max(0, len(lines) - 1)
        end_column = utf16_length(lines[-1].rstrip("\r\n")) if lines else 0
        state = {"line": 0, "column": 0, "name": 0, "kind": 0, "variable": 0}

        def original_scope(
            start: tuple[int, int],
            end: tuple[int, int],
            name: str | None,
            kind: str,
            variables: tuple[str, ...],
            nested: list[SourceScope],
            scope: SourceScope | None = None,
        ) -> None:
            nonlocal scope_count
            flags = 2 | (1 if name is not None else 0) | (4 if scope else 0)
            line_delta = start[0] - state["line"]
            column_delta = start[1] - state["column"] if line_delta == 0 else start[1]
            state["line"], state["column"] = start
            item = "B" + encode_unsigned_vlq(flags)
            item += encode_unsigned_vlq(line_delta) + encode_unsigned_vlq(column_delta)
            if name is not None:
                index = name_index(name)
                item += encode_vlq(index - state["name"])
                state["name"] = index
            index = name_index(kind)
            item += encode_vlq(index - state["kind"])
            state["kind"] = index
            encoded.append(item)
            if scope is not None:
                scope_indexes[scope] = scope_count
            scope_count += 1
            if variables:
                item = "D"
                for variable in variables:
                    index = name_index(variable)
                    item += encode_vlq(index - state["variable"])
                    state["variable"] = index
                encoded.append(item)
            for child in nested:
                original_scope(
                    _position(child, "start"),
                    _position(child, "end"),
                    child.name,
                    child.kind,
                    child.variables,
                    children[child],
                    child,
                )
            line_delta = end[0] - state["line"]
            column_delta = end[1] - state["column"] if line_delta == 0 else end[1]
            state["line"], state["column"] = end
            encoded.append(
                "C"
                + encode_unsigned_vlq(line_delta)
                + encode_unsigned_vlq(column_delta)
            )

        original_scope((0, 0), (end_line, end_column), None, "Global", (), roots)

    for source_name in sources:
        source_scopes = tuple(
            scope for scope in scopes if scope.source.filename == source_name
        )
        if not source_scopes:
            encoded.append("A")
            continue
        roots, children = _nested_ranges(source_scopes)
        encode_source_scopes(source_scopes[0].source, roots, children)

    roots, children = _nested_ranges(generated_scopes)
    state = {"line": 0, "column": 0, "scope": 0}

    def generated_range(scope: GeneratedScope) -> None:
        start = _position(scope, "start")
        line_delta = start[0] - state["line"]
        column_delta = start[1] - state["column"] if line_delta == 0 else start[1]
        flags = 2 | 4 | (1 if line_delta else 0)
        item = "E" + encode_unsigned_vlq(flags)
        if line_delta:
            item += encode_unsigned_vlq(line_delta)
        item += encode_unsigned_vlq(column_delta)
        scope_index = scope_indexes[scope.scope]
        item += encode_vlq(scope_index - state["scope"])
        state["line"], state["column"], state["scope"] = (*start, scope_index)
        encoded.append(item)
        if scope.values:
            encoded.append(
                "G"
                + "".join(
                    encode_unsigned_vlq(0 if value is None else name_index(value) + 1)
                    for value in scope.values
                )
            )
        for child in children[scope]:
            generated_range(child)
        end = _position(scope, "end")
        line_delta = end[0] - state["line"]
        column_delta = end[1] - state["column"] if line_delta == 0 else end[1]
        state["line"], state["column"] = end
        encoded.append(
            "F"
            + (encode_unsigned_vlq(line_delta) if line_delta else "")
            + encode_unsigned_vlq(column_delta)
        )

    for root in roots:
        generated_range(root)
    return ",".join(encoded)


@dataclass(frozen=True)
class SourceMap:
    mappings: tuple[SourceMapping, ...] = ()
    file: str | None = None
    scopes: tuple[SourceScope, ...] = ()
    generated_scopes: tuple[GeneratedScope, ...] = ()

    def shifted(self, line: int, column: int = 0) -> SourceMap:
        return SourceMap(
            tuple(mapping.shifted(line, column) for mapping in self.mappings),
            self.file,
            self.scopes,
            tuple(scope.shifted(line, column) for scope in self.generated_scopes),
        )

    def with_file(self, filename: str) -> SourceMap:
        return replace(self, file=filename)

    def lookup(self, line: int, column: int) -> SourceMapping | None:
        candidate = None
        for mapping in self.ordered_mappings():
            if mapping.generated_line > line:
                break
            if mapping.generated_line == line and mapping.generated_column > column:
                break
            candidate = mapping
        if candidate is None or candidate.generated_line != line:
            return None
        return candidate

    def ordered_mappings(self) -> tuple[SourceMapping, ...]:
        return tuple(
            sorted(
                set(self.mappings),
                key=lambda mapping: (
                    mapping.generated_line,
                    mapping.generated_column,
                    mapping.source.filename,
                    mapping.original_line,
                    mapping.original_column,
                    mapping.name or "",
                ),
            )
        )

    def to_dict(self) -> dict[str, object]:
        mappings = self.ordered_mappings()
        sources = list(
            dict.fromkeys(
                [mapping.source.filename for mapping in mappings]
                + [scope.source.filename for scope in self.scopes]
            )
        )
        source_indexes = {source: index for index, source in enumerate(sources)}
        source_files = {
            source.filename: source
            for source in (
                *(mapping.source for mapping in mappings),
                *(scope.source for scope in self.scopes),
            )
        }
        names = list(
            dict.fromkeys(
                mapping.name for mapping in mappings if mapping.name is not None
            )
        )
        name_indexes = {name: index for index, name in enumerate(names)}

        encoded_lines = []
        previous_source = 0
        previous_original_line = 0
        previous_original_column = 0
        previous_name = 0
        current_line = 0
        line_segments = []
        previous_generated_column = 0

        for mapping in mappings:
            while current_line < mapping.generated_line:
                encoded_lines.append(",".join(line_segments))
                line_segments = []
                previous_generated_column = 0
                current_line += 1

            source_index = source_indexes[mapping.source.filename]
            fields = [
                mapping.generated_column - previous_generated_column,
                source_index - previous_source,
                mapping.original_line - previous_original_line,
                mapping.original_column - previous_original_column,
            ]
            previous_generated_column = mapping.generated_column
            previous_source = source_index
            previous_original_line = mapping.original_line
            previous_original_column = mapping.original_column
            if mapping.name is not None:
                name_index = name_indexes[mapping.name]
                fields.append(name_index - previous_name)
                previous_name = name_index
            line_segments.append("".join(encode_vlq(field) for field in fields))

        if mappings:
            encoded_lines.append(",".join(line_segments))
        result: dict[str, object] = {
            "version": 3,
            "sources": [source.replace("\\", "/") for source in sources],
            "sourcesContent": [source_files[source].text for source in sources],
            "names": names,
            "mappings": ";".join(encoded_lines),
        }
        if self.file is not None:
            result["file"] = self.file
        if self.scopes or self.generated_scopes:
            result["scopes"] = encode_scopes(
                sources,
                names,
                self.scopes,
                self.generated_scopes,
            )
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


@dataclass(frozen=True)
class TranspiledJavaScript:
    javascript: str
    source_map: SourceMap

    def with_source_mapping_url(
        self,
        url: str,
        *,
        source_url: str | None = None,
    ) -> str:
        separator = "" if self.javascript.endswith("\n") else "\n"
        source_directive = ""
        if source_url is not None:
            source_directive = f"//# sourceURL={source_url}\n"
        return (
            f"{self.javascript}{separator}{source_directive}"
            f"//# sourceMappingURL={url}\n"
        )


def map_stack_trace(stack: str, source_map: SourceMap) -> str:
    if source_map.file is None:
        return stack
    location = re.compile(
        rf"(?:(?:https?://[^/\s()]+)?/)?{re.escape(source_map.file)}"
        r"(?:\?[^\s():]*)?:(?P<line>\d+):(?P<column>\d+)"
    )
    mapped_lines = []
    for line in stack.splitlines():
        match = location.search(line)
        if match is None:
            mapped_lines.append(line)
            continue
        mapping = source_map.lookup(
            int(match.group("line")) - 1,
            int(match.group("column")) - 1,
        )
        if mapping is None:
            mapped_lines.append(line)
            continue
        python_location = (
            f"{mapping.source.filename}:"
            f"{mapping.original_line + 1}:{mapping.original_column + 1}"
        )
        mapped_lines.append(
            line[: match.start()] + python_location + line[match.end() :]
        )
    trailing_newline = "\n" if stack.endswith("\n") else ""
    return "\n".join(mapped_lines) + trailing_newline
