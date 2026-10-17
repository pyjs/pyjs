"""Synchronize editable Web API modules with upstream WebIDL declarations.

Public modules intentionally carry no generated-file warning: their Python source remains the
authoritative, editable API. WebIDL constants remain class attributes, while WebIDL object
attributes are initialized per instance. The synchronizer preserves existing Python declarations
and adds missing WebIDL structure around them.
"""

import argparse
import ast
import builtins
import copy
import json
import keyword
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path.home() / ".cache" / "pyjs" / "webidl"
NODE_ROOT = CACHE / "node" / "node_modules"
REGISTRY_CACHE = CACHE / "web-api-registry.json"
EXTRACTOR = ROOT / "scripts" / "extract_web_api.cjs"
WEBREF_IDL_VERSION = "3.82.1"
BCD_VERSION = "8.0.8"
TARGET_IDL = "dom.idl"
TARGET_BROWSERS = ("chrome", "safari")
TYPESCRIPT_VERSION = "5.9.3"
TYPES_WEB_VERSION = "0.0.354"
DART_DOM = ROOT / "external" / "web-api-research" / "web" / "web" / "lib" / "src" / "dom"
COLLECTION_ITEM_TYPES = {
    "HTMLCollection": "Element",
    "NamedNodeMap": "Attr",
    "NodeList": "Node",
}
PYTHON_BUILTIN_NAMES = frozenset(dir(builtins))

# WebIDL cannot express attributes whose reads become narrower on particular subclasses.
INHERITED_ATTRIBUTE_REFINEMENTS = {
    ("Element", "textContent"): "str",
}

PRIMITIVE_TYPES = {
    "any": "object",
    "boolean": "bool",
    "bigint": "int",
    "byte": "int",
    "ByteString": "str",
    "CSSOMString": "str",
    "DOMHighResTimeStamp": "float",
    "DOMString": "str",
    "double": "float",
    "EventHandler": "callable",
    "float": "float",
    "long": "int",
    "long long": "int",
    "object": "object",
    "octet": "int",
    "short": "int",
    "TrustedType": "object",
    "undefined": "None",
    "unsigned long": "int",
    "unsigned long long": "int",
    "unsigned short": "int",
    "unrestricted double": "float",
    "unrestricted float": "float",
    "USVString": "str",
}

EXTERNAL_TYPE_MODULES = {
    name: "pyjs.javascript"
    for name in (
        "ArrayBuffer",
        "BigInt64Array",
        "BigUint64Array",
        "DataView",
        "Float16Array",
        "Float32Array",
        "Float64Array",
        "Int8Array",
        "Int16Array",
        "Int32Array",
        "SharedArrayBuffer",
        "Uint8Array",
        "Uint8ClampedArray",
        "Uint16Array",
        "Uint32Array",
    )
}


@dataclass
class Argument:
    name: str
    type: str
    default: str | None = None
    variadic: bool = False
    keyword_only: bool = False


@dataclass(frozen=True)
class Compatibility:
    mdn_url: str | None
    spec_urls: tuple[str, ...]
    deprecated: bool
    experimental: bool
    standard_track: bool
    chrome: str | bool | None
    safari: str | bool | None

    @property
    def supported(self) -> bool:
        return self.chrome not in {None, False} or self.safari not in {None, False}


@dataclass
class Member:
    kind: str
    name: str
    type: str
    arguments: list[Argument] = field(default_factory=list)
    value: str | None = None
    static: bool = False
    required: bool = False
    asynchronous: bool = False
    source: str = ""
    compatibility: Compatibility | None = None
    included_by_browser_policy: bool = True
    typescript: list[dict] = field(default_factory=list)
    special: str = ""
    omit_when_none: bool = False
    default_factory: str | None = None


@dataclass
class Definition:
    kind: str
    name: str
    base: str | None = None
    members: list[Member] = field(default_factory=list)
    source: str = ""
    sources: set[str] = field(default_factory=set)
    stub: bool = False
    compatibility: Compatibility | None = None
    included_by_browser_policy: bool = True
    typescript: dict | None = None


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    sources: tuple[str, ...] = ()
    imports: dict[str, tuple[str, ...]] = field(default_factory=dict)
    projections: tuple[str, ...] = ()
    global_instances: dict[str, tuple[str, ...]] = field(default_factory=dict)
    handwritten_global_instances: dict[str, tuple[str, ...]] = field(default_factory=dict)
    additional_members: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        overlapping_globals = set(self.global_instances) & set(
            self.handwritten_global_instances
        )
        if overlapping_globals:
            names = ", ".join(sorted(overlapping_globals))
            raise ValueError(f"{self.name}: global instances declared twice: {names}")
    @property
    def all_global_instances(self) -> dict[str, tuple[str, ...]]:
        return self.global_instances | self.handwritten_global_instances

    @property
    def output(self) -> Path:
        return ROOT / "pyjs" / "web" / f"{self.name}.py"


DEFINITION_MODULE_OVERRIDES = {
    # DOM-facing exceptions whose specification source is broader than their public module.
    "AbortSignal": "events",
    "AddEventListenerOptions": "events",
    "CustomEvent": "events",
    "CustomEventInit": "events",
    "Event": "events",
    "EventInit": "events",
    "EventListener": "events",
    "EventListenerOptions": "events",
    "EventTarget": "events",
    "ErrorEvent": "events",
    "ErrorEventInit": "events",
    "MessageEvent": "events",
    "MessageEventInit": "events",
    "MessagePort": "events",
    "PromiseRejectionEvent": "events",
    "PromiseRejectionEventInit": "events",
    "ProgressEvent": "events",
    "ProgressEventInit": "events",
    "DataTransfer": "dragdrop",
    "DataTransferItem": "dragdrop",
    "DataTransferItemList": "dragdrop",
    "DragEvent": "dragdrop",
    "DragEventInit": "dragdrop",
    "DOMRect": "dom",
    "DOMRectInit": "dom",
    "DOMRectReadOnly": "dom",
    "History": "dom",
    "Location": "dom",
    "Navigator": "dom",
    "Storage": "dom",
    "Window": "dom",
}

# Annotation-only dependency stubs may refer to APIs in either direction. Prefer imports from
# specialized modules toward foundational modules and retain a local type projection otherwise.
MODULE_LAYERS = {
    "events": 0,
    "dom": 1,
    "files": 2,
    "geometry": 2,
    "streams": 2,
    "encoding": 2,
    "crypto": 2,
    "storage": 2,
    "url": 3,
    "svg": 3,
    "html": 4,
    "network": 5,
    "dragdrop": 5,
    "clipboard": 5,
    "indexeddb": 5,
    "serviceworker": 6,
    "webgpu": 7,
}


PUBLIC_MODULES = (
    ModuleSpec(
        "dom",
        (
            "dom.idl",
            "cssom.idl",
            "cssom-view.idl",
            "intersection-observer.idl",
            "resize-observer.idl",
            "webidl.idl",
        ),
        imports={"pyjs.web.events": ("Event", "EventTarget")},
        global_instances={
            "Document": ("document",),
            "Window": ("window",),
        },
        projections=("Location", "Navigator", "Storage", "Window"),
        handwritten_global_instances={
            "Storage": ("sessionStorage", "localStorage"),
            "Navigator": ("navigator",),
            "Location": ("location",),
        },
        additional_members={
            "Document": ("hidden", "visibilityState"),
            "Window": ("confirm",),
        },
    ),
    ModuleSpec(
        "events",
        (
            "uievents.idl",
            "pointerevents.idl",
            "touch-events.idl",
            "input-device-capabilities.idl",
            "observable.idl",
        ),
    ),
    ModuleSpec(
        "html",
        ("html.idl",),
        imports={
            "pyjs.web.dom": (
                "CSSStyleProperties",
                "DOMRect",
                "DOMTokenList",
                "Document",
                "Element",
                "Node",
                "NodeList",
                "Window",
            ),
            "pyjs.web.files": ("FileList",),
        },
        global_instances={"CustomElementRegistry": ("customElements",)},
    ),
    ModuleSpec(
        "network",
        ("fetch.idl", "xhr.idl", "websockets.idl"),
        imports={
            "pyjs.web.events": ("AbortSignal", "EventTarget"),
            "pyjs.web.files": ("Blob",),
            "pyjs.javascript": (
                "ArrayBuffer",
                "BigInt64Array",
                "BigUint64Array",
                "DataView",
                "Float16Array",
                "Float32Array",
                "Float64Array",
                "Int8Array",
                "Int16Array",
                "Int32Array",
                "Uint8Array",
                "Uint8ClampedArray",
                "Uint16Array",
                "Uint32Array",
            ),
            "pyjs.web.streams": ("ReadableStream",),
            "pyjs.web.url": ("URLSearchParams",),
        },
    ),
    ModuleSpec(
        "serviceworker",
        (
            "service-workers.idl",
            "notifications.idl",
            "push-api.idl",
        ),
        imports={
            "pyjs.web.events": ("Event", "EventInit", "EventTarget"),
            "pyjs.web.network": ("Request", "Response"),
        },
        projections=("Navigator",),
        global_instances={
            "CacheStorage": ("caches",),
            "Navigator": ("navigator",),
        },
    ),
    ModuleSpec(
        "files",
        ("FileAPI.idl",),
        imports={
            "pyjs.web.dom": ("DOMException",),
            "pyjs.web.events": ("EventTarget",),
            "pyjs.javascript": (
                "ArrayBuffer",
                "BigInt64Array",
                "BigUint64Array",
                "DataView",
                "Float16Array",
                "Float32Array",
                "Float64Array",
                "Int8Array",
                "Int16Array",
                "Int32Array",
                "Uint8Array",
                "Uint8ClampedArray",
                "Uint16Array",
                "Uint32Array",
            ),
            "pyjs.web.streams": ("ReadableStream",),
        },
    ),
    ModuleSpec(
        "encoding",
        ("encoding.idl",),
        imports={
            "pyjs.javascript": (
                "ArrayBuffer",
                "BigInt64Array",
                "BigUint64Array",
                "DataView",
                "Float16Array",
                "Float32Array",
                "Float64Array",
                "Int8Array",
                "Int16Array",
                "Int32Array",
                "SharedArrayBuffer",
                "Uint8Array",
                "Uint8ClampedArray",
                "Uint16Array",
                "Uint32Array",
            ),
        },
    ),
    ModuleSpec(
        "crypto",
        ("webcrypto.idl", "webcrypto-modern-algos.idl", "webcrypto-secure-curves.idl"),
        imports={
            "pyjs.javascript": (
                "ArrayBuffer",
                "BigInt64Array",
                "BigUint64Array",
                "DataView",
                "Float16Array",
                "Float32Array",
                "Float64Array",
                "Int8Array",
                "Int16Array",
                "Int32Array",
                "Uint8Array",
                "Uint8ClampedArray",
                "Uint16Array",
                "Uint32Array",
            ),
        },
        global_instances={"Crypto": ("crypto",)},
    ),
    ModuleSpec(
        "url",
        ("url.idl",),
        imports={"pyjs.web.files": ("Blob",)},
    ),
    ModuleSpec(
        "dragdrop",
        imports={
            "pyjs.web.dom": ("Element",),
            "pyjs.web.events": ("MouseEvent", "MouseEventInit"),
            "pyjs.web.files": ("File", "FileList"),
        },
    ),
    ModuleSpec(
        "indexeddb",
        ("IndexedDB.idl",),
        imports={
            "pyjs.web.dom": ("DOMException",),
            "pyjs.web.events": ("Event", "EventInit", "EventTarget"),
            "pyjs.web.html": ("DOMStringList",),
        },
        global_instances={"IDBFactory": ("indexedDB",)},
    ),
    ModuleSpec(
        "geometry",
        ("geometry.idl",),
        imports={
            "pyjs.javascript": ("Float32Array", "Float64Array"),
        },
    ),
    ModuleSpec(
        "svg",
        ("SVG.idl", "svg-paths.idl"),
        imports={
            "pyjs.web.dom": (
                "CSSStyleDeclaration",
                "DOMRect",
                "DOMRectReadOnly",
                "DOMTokenList",
                "Element",
                "Node",
                "NodeList",
            ),
            "pyjs.web.geometry": (
                "DOMMatrix",
                "DOMMatrix2DInit",
                "DOMPoint",
                "DOMPointInit",
            ),
        },
    ),
    ModuleSpec(
        "streams",
        ("streams.idl",),
    ),
    ModuleSpec(
        "storage",
        ("storage.idl",),
        imports={"pyjs.web.events": ("EventTarget",)},
        projections=("Navigator",),
        global_instances={"Navigator": ("navigator",)},
    ),
    ModuleSpec(
        "clipboard",
        ("clipboard-apis.idl",),
        imports={
            "pyjs.web.dragdrop": ("DataTransfer",),
            "pyjs.web.events": ("Event", "EventInit"),
            "pyjs.web.files": ("Blob",),
        },
        projections=("Navigator",),
        global_instances={"Navigator": ("navigator",)},
    ),
    ModuleSpec(
        "webgpu",
        ("webgpu.idl",),
        imports={
            "pyjs.web.events": ("EventTarget",),
            "pyjs.web.html": ("HTMLCanvasElement",),
            "pyjs.javascript": ("Float32Array", "Uint16Array", "Uint32Array"),
        },
        projections=("Navigator",),
        global_instances={"Navigator": ("navigator",)},
    ),
)


def node_package_version(name: str) -> str | None:
    package = NODE_ROOT / name / "package.json"
    if not package.exists():
        return None
    return json.loads(package.read_text())["version"]


def ensure_node_tools() -> None:
    packages = {
        "@webref/idl": WEBREF_IDL_VERSION,
        "@mdn/browser-compat-data": BCD_VERSION,
        "@types/web": TYPES_WEB_VERSION,
        "typescript": TYPESCRIPT_VERSION,
        "webidl2": "24.5.0",
    }
    if all(node_package_version(name) == version for name, version in packages.items()):
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "npm",
            "install",
            "--prefix",
            str(CACHE / "node"),
            "--no-package-lock",
            "--no-save",
            *(f"{name}@{version}" for name, version in packages.items()),
        ],
        check=True,
    )


def extracted_registry() -> dict:
    ensure_node_tools()
    subprocess.run(
        ["node", str(EXTRACTOR), str(NODE_ROOT), str(REGISTRY_CACHE)],
        check=True,
        cwd=ROOT,
    )
    return json.loads(REGISTRY_CACHE.read_text())


def python_name(name: str) -> str:
    if keyword.iskeyword(name):
        return name + "_"
    return name


def can_render_member(member: Member) -> bool:
    return (
        member.kind != "attribute"
        or member.name.isidentifier()
        and not keyword.iskeyword(member.name)
    )


def strip_extended_attributes(value: str) -> str:
    while value.startswith("["):
        depth = 0
        for index, character in enumerate(value):
            if character == "[":
                depth += 1
            elif character == "]":
                depth -= 1
                if depth == 0:
                    value = value[index + 1 :].strip()
                    break
        else:
            break
    return value


def split_top_level(value: str, separator: str) -> list[str]:
    parts = []
    depth = 0
    start = 0
    index = 0
    while index < len(value):
        character = value[index]
        if character in "<([":
            depth += 1
        elif character in ">)]":
            depth -= 1
        elif depth == 0 and value.startswith(separator, index):
            parts.append(value[start:index].strip())
            index += len(separator)
            start = index
            continue
        index += 1
    parts.append(value[start:].strip())
    return parts


def python_type(value: str) -> str:
    value = strip_extended_attributes(value.strip())
    if value.endswith("?"):
        return add_none(python_type(value[:-1]))
    if value.startswith("(") and value.endswith(")"):
        union = split_top_level(value[1:-1], " or ")
        if len(union) > 1:
            return union_type(python_type(part) for part in union)
    generic = re.fullmatch(r"(\w+)<(.*)>", value)
    if generic:
        name, contents = generic.groups()
        arguments = split_top_level(contents, ",")
        if name in {"sequence", "FrozenArray", "ObservableArray"}:
            return f"list[{python_type(arguments[0])}]"
        if name == "record":
            return f"dict[{python_type(arguments[0])}, {python_type(arguments[1])}]"
        if name == "Promise":
            return python_type(arguments[0])
        if name == "async_sequence":
            return "object"
        return f"{name}[{', '.join(python_type(argument) for argument in arguments)}]"
    return PRIMITIVE_TYPES.get(value, value)


def add_none(value: str) -> str:
    parts = [part.strip() for part in value.split("|")]
    if "None" not in parts:
        parts.append("None")
    return " | ".join(parts)


def union_type(values) -> str:
    parts = []
    for value in values:
        for part in value.split("|"):
            part = part.strip()
            if part not in parts:
                parts.append(part)
    return " | ".join(parts)


def default_value(value, type_name: str, optional: bool) -> tuple[str, str | None]:
    if value is None:
        if optional:
            return add_none(type_name), "None"
        return type_name, None
    source = str(value).strip()
    if source.startswith("="):
        source = source[1:].strip()
    values = {
        "false": "False",
        "true": "True",
        "null": "None",
        "{}": "None",
        "[]": "None",
    }
    result = values.get(source, source)
    if result == "None":
        type_name = add_none(type_name)
    return type_name, result


def expanded_aliases(aliases: dict[str, str]) -> dict[str, str]:
    resolved = {}

    def resolve(name: str, active: set[str]) -> str:
        if name in resolved:
            return resolved[name]
        if name in active:
            return aliases[name]
        active.add(name)
        value = re.sub(
            r"\b[A-Za-z_]\w*\b",
            lambda match: (
                resolve(match.group(), active)
                if match.group() in aliases and match.group() != name
                else match.group()
            ),
            aliases[name],
        )
        active.remove(name)
        resolved[name] = value
        return value

    for name in aliases:
        resolve(name, set())
    return resolved


def resolved_aliases(type_name: str, aliases: dict[str, str], pattern: re.Pattern[str]) -> str:
    return pattern.sub(lambda match: aliases[match.group()], type_name)


def compatibility_from_record(value: dict | None) -> Compatibility | None:
    if value is None:
        return None
    status = value["status"]
    support = value["support"]
    return Compatibility(
        value["mdn_url"],
        tuple(value["spec_urls"]),
        status["deprecated"],
        status["experimental"],
        status["standard_track"],
        support["chrome"],
        support["safari"],
    )


def registry_from_json(data: dict) -> dict[str, Definition]:
    aliases = {name: python_type(value) for name, value in data["aliases"].items()}
    aliases.update(
        {
            name: python_type(value)
            for name, value in data.get("typescript_aliases", {}).items()
            if name not in aliases and re.fullmatch(r"[A-Z]\w*", value)
        }
    )
    aliases = expanded_aliases(aliases)
    alias_pattern = re.compile(
        r"\b(?:"
        + "|".join(re.escape(name) for name in sorted(aliases, key=len, reverse=True))
        + r")\b"
    )

    def resolve(type_name: str) -> str:
        result = resolved_aliases(python_type(type_name), aliases, alias_pattern)
        for collection, item_type in COLLECTION_ITEM_TYPES.items():
            result = re.sub(rf"\b{collection}\b(?!\[)", f"{collection}[{item_type}]", result)
        return result

    definitions = {}
    for value in data["definitions"]:
        members = []
        for item in value["members"]:
            type_name = resolve(item["type"])
            if item["name"] == "querySelectorAll":
                type_name = type_name.replace("NodeList[Node]", "NodeList[Element]")
            arguments = []
            for raw_argument in item.get("arguments", ()):
                argument_type, argument_default = default_value(
                    raw_argument["default"],
                    resolve(raw_argument["type"]),
                    raw_argument["optional"],
                )
                arguments.append(
                    Argument(
                        python_name(raw_argument["name"]),
                        argument_type,
                        argument_default,
                        raw_argument["variadic"],
                    )
                )
            member_value = item.get("value")
            required = item.get("required", False)
            omit_when_none = False
            default_factory = None
            if item["kind"] == "field":
                raw_default = item.get("default")
                type_name, member_value = default_value(
                    raw_default, type_name, not required
                )
                omit_when_none = not required and raw_default is None
                if raw_default in {"[]", "{}"}:
                    default_factory = raw_default
            elif item["kind"] == "constant":
                _, member_value = default_value(member_value, type_name, False)
            members.append(
                Member(
                    item["kind"],
                    item["name"],
                    type_name,
                    arguments,
                    member_value,
                    item.get("static", False),
                    required,
                    item.get("asynchronous", False),
                    item["source"],
                    compatibility_from_record(item["compatibility"]),
                    item["included_by_browser_policy"],
                    item["typescript"],
                    item.get("special", ""),
                    omit_when_none,
                    default_factory,
                )
            )
        definitions[value["name"]] = Definition(
            value["kind"],
            value["name"],
            value["base"],
            members,
            value["source"] or "",
            set(value["sources"]),
            False,
            compatibility_from_record(value["compatibility"]),
            value["included_by_browser_policy"],
            value["typescript"],
        )
    return definitions


def target_definitions(registry: dict[str, Definition]) -> dict[str, Definition]:
    selected = {}
    for definition in registry.values():
        if definition.source != TARGET_IDL:
            continue
        if not definition.included_by_browser_policy:
            continue
        members = []
        seen = set()
        for member in definition.members:
            if member.source != TARGET_IDL:
                continue
            if not member.included_by_browser_policy:
                continue
            key = member.kind, member.name
            if key not in seen:
                members.append(member)
                seen.add(key)
        selected[definition.name] = Definition(
            definition.kind,
            definition.name,
            definition.base,
            members,
            definition.source,
            set(definition.sources),
            False,
            definition.compatibility,
            definition.included_by_browser_policy,
            definition.typescript,
        )

    referenced = set()
    for definition in selected.values():
        if definition.base:
            referenced.add(definition.base)
        for member in definition.members:
            referenced.update(annotation_names(member.type))
            for argument in member.arguments:
                referenced.update(annotation_names(argument.type))
    for name in sorted(referenced - selected.keys()):
        definition = registry.get(name)
        if definition is not None:
            selected[name] = Definition(
                definition.kind,
                definition.name,
                source=definition.source,
                sources=set(definition.sources),
                stub=True,
                compatibility=definition.compatibility,
                included_by_browser_policy=definition.included_by_browser_policy,
                typescript=definition.typescript,
            )
        else:
            selected[name] = Definition("interface", name, stub=True)
    return selected


def source_module_map(specs: tuple[ModuleSpec, ...] = PUBLIC_MODULES) -> dict[str, str]:
    owners = {}
    for spec in specs:
        for source in spec.sources:
            if previous := owners.get(source):
                raise ValueError(f"{source} is owned by both {previous} and {spec.name}")
            owners[source] = spec.name
    return owners


def module_dependency_graph(
    specs: tuple[ModuleSpec, ...] = PUBLIC_MODULES,
    registry: dict[str, Definition] | None = None,
) -> dict[str, set[str]]:
    module_names = {spec.name for spec in specs}
    return {
        spec.name: {
            module.rsplit(".", 1)[-1]
            for module in (
                module_imports(registry, spec, source_module_map(specs))
                if registry is not None
                else spec.imports
            )
            if module.startswith("pyjs.web.")
            and module.rsplit(".", 1)[-1] in module_names
        }
        for spec in specs
    }


def dependency_cycles(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    cycles = set()

    def visit(module: str, path: tuple[str, ...]) -> None:
        for dependency in graph[module]:
            if dependency in path:
                start = path.index(dependency)
                cycle = path[start:] + (dependency,)
                rotations = [cycle[index:-1] + cycle[:index] for index in range(len(cycle) - 1)]
                cycles.add(min(rotations))
            else:
                visit(dependency, path + (dependency,))

    for module in graph:
        visit(module, (module,))
    return sorted(cycle + (cycle[0],) for cycle in cycles)


def transitive_dependencies(module: str, graph: dict[str, set[str]]) -> set[str]:
    result = set()
    pending = list(graph[module])
    while pending:
        dependency = pending.pop()
        if dependency in result:
            continue
        result.add(dependency)
        pending.extend(graph[dependency])
    return result


def validate_module_specs(
    registry: dict[str, Definition],
    specs: tuple[ModuleSpec, ...] = PUBLIC_MODULES,
    definition_overrides: dict[str, str] = DEFINITION_MODULE_OVERRIDES,
) -> None:
    source_modules = source_module_map(specs)
    module_names = {spec.name for spec in specs}
    registry_sources = {definition.source for definition in registry.values()}
    unknown_sources = set(source_modules) - registry_sources
    if unknown_sources:
        raise ValueError("Unknown WebIDL sources: " + ", ".join(sorted(unknown_sources)))
    unknown_overrides = set(definition_overrides) - registry.keys()
    if unknown_overrides:
        raise ValueError("Unknown definition overrides: " + ", ".join(sorted(unknown_overrides)))
    invalid_override_modules = set(definition_overrides.values()) - module_names
    if invalid_override_modules:
        raise ValueError(
            "Definition overrides use unknown modules: "
            + ", ".join(sorted(invalid_override_modules))
        )
    projections = {name for spec in specs for name in spec.projections}
    unknown_projections = projections - registry.keys()
    if unknown_projections:
        raise ValueError("Unknown projections: " + ", ".join(sorted(unknown_projections)))

    graph = module_dependency_graph(specs, registry)
    if cycles := dependency_cycles(graph):
        paths = (" -> ".join(cycle) for cycle in cycles)
        raise ValueError("Web API module import cycles: " + "; ".join(paths))
    imported_by = {
        module for dependencies in graph.values() for module in dependencies
    }
    isolated_imports = imported_by & {"webgpu"}
    if isolated_imports:
        raise ValueError(
            "Large leaf modules must not be dependencies: "
            + ", ".join(sorted(isolated_imports))
        )


def print_module_report(
    registry: dict[str, Definition], specs: tuple[ModuleSpec, ...] = PUBLIC_MODULES
) -> None:
    source_modules = source_module_map(specs)
    graph = module_dependency_graph(specs, registry)
    owned = 0
    for spec in specs:
        definitions = sum(
            definition.included_by_browser_policy
            and definition_module(definition, source_modules) == spec.name
            for definition in registry.values()
        )
        owned += definitions
        dependencies = transitive_dependencies(spec.name, graph)
        print(
            f"{spec.name}: {definitions} owned definitions; "
            f"{len(dependencies)} transitive module dependencies"
        )
    supported = sum(
        definition.included_by_browser_policy for definition in registry.values()
    )
    print(f"Web API coverage: {owned}/{supported} definitions owned by public modules")
    deferred_attributes = {
        f"{definition.name}.{member.name}"
        for definition in registry.values()
        if definition.included_by_browser_policy
        and definition_module(definition, source_modules) is not None
        for member in definition.members
        if not can_render_member(member)
    }
    if deferred_attributes:
        print(
            f"Deferred non-Python attribute names ({len(deferred_attributes)}): "
            + ", ".join(sorted(deferred_attributes))
        )


def output_dependency_graph(
    specs: tuple[ModuleSpec, ...] = PUBLIC_MODULES,
) -> dict[str, set[str]]:
    module_names = {spec.name for spec in specs}
    graph = {}
    for spec in specs:
        module = ast.parse(spec.output.read_text())
        graph[spec.name] = {
            node.module.rsplit(".", 1)[-1]
            for node in module.body
            if isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("pyjs.web.")
            and node.module.rsplit(".", 1)[-1] in module_names
        }
    return graph


def validate_output_dependencies(
    specs: tuple[ModuleSpec, ...] = PUBLIC_MODULES,
) -> None:
    graph = output_dependency_graph(specs)
    if cycles := dependency_cycles(graph):
        paths = (" -> ".join(cycle) for cycle in cycles)
        raise ValueError("Generated Web API import cycles: " + "; ".join(paths))
    imported_by = {
        module for dependencies in graph.values() for module in dependencies
    }
    if "webgpu" in imported_by:
        raise ValueError("Generated foundational modules must not import webgpu")
    largest_module = max(graph, key=lambda module: len(transitive_dependencies(module, graph)))
    print(
        f"Generated import graph: acyclic; largest closure is {largest_module} with "
        f"{len(transitive_dependencies(largest_module, graph))} dependencies"
    )


def definition_module(definition: Definition, source_modules: dict[str, str]) -> str | None:
    return DEFINITION_MODULE_OVERRIDES.get(
        definition.name, source_modules.get(definition.source)
    )


def module_imports(
    registry: dict[str, Definition],
    spec: ModuleSpec,
    source_modules: dict[str, str],
    additional_definitions: set[str] | None = None,
) -> dict[str, tuple[str, ...]]:
    imports = {module: set(names) for module, names in spec.imports.items()}
    owned_definitions = [
        definition
        for definition in registry.values()
        if definition.included_by_browser_policy
        and (
            definition_module(definition, source_modules) == spec.name
            or definition.name in spec.projections
        )
    ]

    def add_base_import(definition: Definition) -> None:
        base = registry.get(definition.base)
        if base is None:
            return
        owner = definition_module(base, source_modules)
        if owner is None or owner == spec.name:
            return
        imports.setdefault(f"pyjs.web.{owner}", set()).add(base.name)

    for definition in owned_definitions:
        add_base_import(definition)

    if additional_definitions:
        canonical_graph = {}
        public_modules = {module_spec.name for module_spec in PUBLIC_MODULES}
        for module_spec in PUBLIC_MODULES:
            module_import_names = module_imports(
                registry,
                module_spec,
                source_modules,
            )
            canonical_graph[module_spec.name] = {
                module.rsplit(".", 1)[-1]
                for module in module_import_names
                if module.startswith("pyjs.web.")
                and module.rsplit(".", 1)[-1] in public_modules
            }
        for name in additional_definitions:
            if external_module := EXTERNAL_TYPE_MODULES.get(name):
                imports.setdefault(external_module, set()).add(name)
                continue
            definition = registry.get(name)
            if definition is None or definition in owned_definitions:
                continue
            owner = definition_module(definition, source_modules)
            if (
                owner is not None
                and owner != spec.name
                and MODULE_LAYERS.get(owner, 100) < MODULE_LAYERS.get(spec.name, 100)
                and spec.name not in transitive_dependencies(owner, canonical_graph)
            ):
                imports.setdefault(f"pyjs.web.{owner}", set()).add(definition.name)
                continue
            base = registry.get(definition.base)
            if base is None:
                continue
            base_owner = definition_module(base, source_modules)
            if base_owner is None or base_owner == spec.name:
                continue
            if MODULE_LAYERS.get(base_owner, 100) >= MODULE_LAYERS.get(spec.name, 100):
                continue
            if spec.name in transitive_dependencies(base_owner, canonical_graph):
                continue
            imports.setdefault(f"pyjs.web.{base_owner}", set()).add(base.name)
    return {module: tuple(sorted(names)) for module, names in imports.items()}


def selected_definitions(
    registry: dict[str, Definition],
    spec: ModuleSpec,
    source_modules: dict[str, str] | None = None,
    imports: dict[str, tuple[str, ...]] | None = None,
    retained_names: set[str] | None = None,
) -> dict[str, Definition]:
    source_modules = source_modules or source_module_map()
    imports = imports or module_imports(registry, spec, source_modules)
    imported = {name for names in imports.values() for name in names}
    selected = {}

    def include(name: str, *, projection: bool = False) -> None:
        definition = registry[name]
        members = []
        seen = set()
        additional_members = spec.additional_members.get(name, ())
        for member in definition.members:
            if not can_render_member(member):
                continue
            if projection and member.source not in spec.sources:
                continue
            if (
                not projection
                and member.source != definition.source
                and source_modules.get(member.source) != spec.name
                and member.name not in additional_members
            ):
                continue
            if not member.included_by_browser_policy:
                continue
            key = member.kind, member.name
            if key not in seen:
                members.append(member)
                seen.add(key)
        for refinement, type_name in INHERITED_ATTRIBUTE_REFINEMENTS.items():
            class_name, attribute_name = refinement
            if class_name == name and ("attribute", attribute_name) not in seen:
                members.append(Member("attribute", attribute_name, type_name))
        selected[name] = Definition(
            definition.kind,
            definition.name,
            definition.base,
            members,
            definition.source,
            set(definition.sources),
            False,
            definition.compatibility,
            definition.included_by_browser_policy,
            definition.typescript,
        )

    for name, definition in registry.items():
        if not definition.included_by_browser_policy:
            continue
        if definition_module(definition, source_modules) == spec.name:
            include(name)

    for name in spec.projections:
        if name in selected:
            continue
        include(name, projection=True)

    while True:
        referenced = (
            referenced_types(selected.values()) | (retained_names or set())
        ) - selected.keys() - imported
        dependencies = {
            name
            for name in referenced
            if name in registry
            and registry[name].kind == "dictionary"
        }
        if not dependencies:
            break
        for name in sorted(dependencies):
            include(name)

    while True:
        referenced = (
            referenced_types(selected.values()) | (retained_names or set())
        ) - selected.keys() - imported
        if not referenced:
            break
        for name in sorted(referenced):
            definition = registry.get(name)
            if definition is not None:
                selected[name] = Definition(
                    definition.kind,
                    definition.name,
                    base=definition.base,
                    source=definition.source,
                    sources=set(definition.sources),
                    stub=True,
                    compatibility=definition.compatibility,
                    included_by_browser_policy=definition.included_by_browser_policy,
                    typescript=definition.typescript,
                )
            else:
                selected[name] = Definition("interface", name, stub=True)

    selected_names = set(selected)
    missing_globals = set(spec.global_instances) - selected_names
    if missing_globals:
        names = ", ".join(sorted(missing_globals))
        raise ValueError(f"{spec.name}: generated globals have no selected definition: {names}")
    missing_additional_members = set(spec.additional_members) - selected_names
    if missing_additional_members:
        names = ", ".join(sorted(missing_additional_members))
        raise ValueError(f"{spec.name}: additional members have no definition: {names}")
    return selected


def referenced_types(definitions) -> set[str]:
    referenced = set()
    for definition in definitions:
        if definition.base:
            referenced.add(definition.base)
        for member in definition.members:
            referenced.update(annotation_names(member.type))
            for argument in member.arguments:
                referenced.update(annotation_names(argument.type))
    return referenced


def annotation_names(type_name: str) -> set[str]:
    try:
        expression = ast.parse(type_name, mode="eval")
    except SyntaxError:
        return set()
    ignored = {"bool", "callable", "dict", "float", "int", "list", "None", "object", "str"}
    return {
        node.id
        for node in ast.walk(expression)
        if isinstance(node, ast.Name) and node.id not in ignored
    }


def ordered_definitions(definitions: dict[str, Definition]) -> list[Definition]:
    pending = dict(definitions)
    ordered = []
    emitted = set()
    while pending:
        ready = [
            definition
            for definition in pending.values()
            if definition.base is None
            or definition.base in emitted
            or definition.base not in definitions
        ]
        if not ready:
            names = ", ".join(sorted(pending))
            raise RuntimeError(f"WebIDL inheritance cycle involving {names}.")
        ready.sort(key=lambda definition: definition.name.casefold())
        for definition in ready:
            ordered.append(definition)
            emitted.add(definition.name)
            del pending[definition.name]
    return ordered


def complete_dictionary_members(
    definition: Definition, definitions: dict[str, Definition]
) -> list[Member]:
    members = []
    if definition.base in definitions:
        members.extend(complete_dictionary_members(definitions[definition.base], definitions))
    members.extend(definition.members)
    return members


def render_arguments(arguments: list[Argument]) -> str:
    values = []
    keyword_only = False
    positional_default = False
    for argument in arguments:
        requires_keyword = argument.keyword_only or (
            positional_default and argument.default is None
        )
        if requires_keyword and not keyword_only and not argument.variadic:
            values.append("*")
            keyword_only = True
        prefix = "*" if argument.variadic else ""
        value = f"{prefix}{argument.name}: {argument.type}"
        if argument.default is not None:
            value += f" = {argument.default}"
            if not keyword_only:
                positional_default = True
        values.append(value)
        if argument.variadic:
            keyword_only = True
    return ", ".join(values)


def definition_docstring(definition: Definition) -> str:
    lines = [f"WebIDL source: @webref/idl/{definition.source or 'unknown'}"]
    compat = definition.compatibility
    if compat is not None:
        if compat.mdn_url:
            lines.append(f"MDN: {compat.mdn_url}")
        versions = []
        if compat.chrome not in {None, False}:
            versions.append(f"Chrome {compat.chrome}")
        if compat.safari not in {None, False}:
            versions.append(f"Safari {compat.safari}")
        if versions:
            lines.append("Browser support: " + ", ".join(versions))
    return "\n\n".join(lines)


def render_dictionary(definition: Definition, definitions: dict[str, Definition]) -> ast.ClassDef:
    members = complete_dictionary_members(definition, definitions)
    required = [member for member in members if member.required]
    optional = [member for member in members if not member.required]
    members = sorted(required, key=lambda member: member.name.casefold()) + sorted(
        optional, key=lambda member: member.name.casefold()
    )
    arguments = []
    assignments = []
    for member in members:
        argument_name = python_name(member.name)
        value = f"{argument_name}: {member.type}"
        if member.value is not None:
            value += f" = {member.value}"
        arguments.append(value)
        assignment = f"self.{python_name(member.name)} = {argument_name}"
        if member.default_factory == "[]":
            assignment = (
                f"if {argument_name} is None:\n"
                f"            {argument_name} = []\n"
                f"        self.{python_name(member.name)} = {argument_name}"
            )
        elif member.default_factory == "{}":
            concrete_type = next(
                part.strip() for part in member.type.split("|") if part.strip() != "None"
            )
            factory = "{}" if concrete_type.startswith("dict[") else f"{concrete_type}()"
            assignment = (
                f"if {argument_name} is None:\n"
                f"            {argument_name} = {factory}\n"
                f"        self.{python_name(member.name)} = {argument_name}"
            )
        elif member.omit_when_none:
            assignment = (
                f"if {argument_name} is not None:\n"
                f"            self.{python_name(member.name)} = {argument_name}"
            )
        assignments.append(assignment)
    body = "\n        ".join(assignments) or "..."
    self_arguments = "self"
    if arguments:
        self_arguments += f", {', '.join(arguments)}"
    source = f"""
@js.dictionary
class {definition.name}:
    def __init__({self_arguments}):
        {body}
"""
    result = ast.parse(source).body[0]
    result.body.insert(0, ast.Expr(ast.Constant(definition_docstring(definition))))
    return result


def member_sort_key(member: Member) -> tuple[int, str]:
    groups = {"constant": 0, "attribute": 1, "constructor": 2, "method": 3}
    return groups[member.kind], member.name.casefold()


def attribute_default(type_name: str) -> str:
    if "None" in (part.strip() for part in type_name.split("|")):
        return "None"
    if type_name == "bool":
        return "False"
    if type_name == "int":
        return "0"
    if type_name == "float":
        return "0.0"
    if type_name == "str":
        return '""'
    if type_name.startswith("list["):
        return "[]"
    if type_name.startswith("dict["):
        return "{}"
    return "None"


def render_interface(definition: Definition, definitions: dict[str, Definition]) -> ast.ClassDef:
    body = [ast.Expr(ast.Constant(definition_docstring(definition)))]
    members = sorted(definition.members, key=member_sort_key)
    attributes = [member for member in members if member.kind == "attribute"]
    constructor = next((member for member in members if member.kind == "constructor"), None)

    for member in members:
        if member.kind == "constant":
            body.extend(ast.parse(f"{member.name} = {member.value}").body)
    if attributes or constructor is not None:
        constructor_arguments = constructor.arguments if constructor is not None else []
        arguments = render_arguments(constructor_arguments)
        separator = ", " if arguments else ""
        argument_names = {argument.name for argument in constructor_arguments}
        initialization = []
        if definition.base:
            initialization.append("    super().__init__()")
        initialization.extend(
            f"    self.{member.name}: {member.type} = "
            f"{member.name if member.name in argument_names else attribute_default(member.type)}"
            for member in attributes
        )
        initialization = initialization or ["    ..."]
        source = f"def __init__(self{separator}{arguments}):\n" + "\n".join(initialization)
        body.extend(ast.parse(source).body)

    for member in members:
        if member.kind == "method":
            arguments = member.arguments
            first = arguments[0].name if arguments else "key"
            second = arguments[1].name if len(arguments) > 1 else "value"
            inline = {
                "getter": f"{{self}}[{{{first}}}]",
                "setter": f"{{self}}[{{{first}}}] = {{{second}}}",
                "deleter": f"delete {{self}}[{{{first}}}]",
            }.get(member.special)
            method_name = python_name(member.name)
            if method_name != member.name:
                inline = f"{{self}}.{member.name}({{_args_joined}})"
            decorators = "@staticmethod\n" if member.static else ""
            if inline:
                decorators += f'@js.inline("{inline}")\n'
            self_argument = "" if member.static else "self"
            rendered_arguments = render_arguments(arguments)
            separator = ", " if self_argument and rendered_arguments else ""
            return_type = f" -> {member.type}"
            async_prefix = "async " if member.asynchronous else ""
            source = (
                f"{decorators}{async_prefix}def {method_name}"
                f"({self_argument}{separator}{rendered_arguments}){return_type}:\n"
                "    ...\n"
            )
            body.extend(ast.parse(source).body)
    if len(body) == 1:
        body.append(ast.Pass())
    base = definition.base
    if base in COLLECTION_ITEM_TYPES:
        base = f"{base}[{COLLECTION_ITEM_TYPES[base]}]"
    bases = [ast.parse(base, mode="eval").body] if base else []
    return ast.ClassDef(
        name=definition.name,
        bases=bases,
        keywords=[],
        body=body,
        decorator_list=[
            ast.Attribute(ast.Name("js"), "native", ast.Load())
        ],
        type_params=[ast.TypeVar("T")] if definition.name in COLLECTION_ITEM_TYPES else [],
    )


def generated_public_module(
    registry: dict[str, Definition],
    spec: ModuleSpec,
    retained_names: set[str] | None = None,
) -> tuple[ast.Module, dict[str, Definition]]:
    source_modules = source_module_map()
    imports = module_imports(registry, spec, source_modules, retained_names)
    while True:
        definitions = selected_definitions(
            registry,
            spec,
            source_modules,
            imports,
            retained_names,
        )
        required_names = (retained_names or set()) | referenced_types(definitions.values())
        updated_imports = module_imports(registry, spec, source_modules, required_names)
        if updated_imports == imports:
            break
        imports = updated_imports
    module = render_module(definitions, None, imports)
    return module, definitions


def render_module(
    definitions: dict[str, Definition],
    documentation: str | None,
    imports: dict[str, tuple[str, ...]] | None = None,
) -> ast.Module:
    body = []
    if documentation is not None:
        body.append(ast.Expr(ast.Constant(documentation)))
    body.append(ast.ImportFrom("pyjs", [ast.alias("js")], 0))
    for module, names in (imports or {}).items():
        body.append(ast.ImportFrom(module, [ast.alias(name) for name in names], 0))
    for definition in ordered_definitions(definitions):
        if definition.kind == "dictionary":
            body.append(render_dictionary(definition, definitions))
        else:
            body.append(render_interface(definition, definitions))
    return ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))


def node_key(node: ast.stmt) -> tuple[str, str] | None:
    if isinstance(node, ast.ClassDef):
        return "class", node.name
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "function", node.name
    if isinstance(node, ast.AnnAssign):
        if isinstance(node.target, ast.Name):
            return "attribute", node.target.id
        if (
            isinstance(node.target, ast.Attribute)
            and isinstance(node.target.value, ast.Name)
            and node.target.value.id == "self"
        ):
            return "self-attribute", node.target.attr
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name):
            return "assignment", target.id
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
        ):
            return "self-attribute", target.attr
    if isinstance(node, ast.ImportFrom):
        return "import", f"{node.module}:{','.join(alias.name for alias in node.names)}"
    if is_super_init_call(node):
        return "call", "super.__init__"
    return None


def is_super_init_call(node: ast.stmt) -> bool:
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    function = node.value.func
    return (
        isinstance(function, ast.Attribute)
        and function.attr == "__init__"
        and isinstance(function.value, ast.Call)
        and isinstance(function.value.func, ast.Name)
        and function.value.func.id == "super"
    )


def insert_missing(existing: list[ast.stmt], generated: list[ast.stmt]) -> None:
    for node in generated:
        if not isinstance(node, ast.ImportFrom):
            continue
        matching = next(
            (
                statement
                for statement in existing
                if isinstance(statement, ast.ImportFrom)
                and statement.module == node.module
                and statement.level == node.level
            ),
            None,
        )
        if matching is None:
            continue
        imported = {(alias.name, alias.asname) for alias in matching.names}
        matching.names.extend(
            alias for alias in node.names if (alias.name, alias.asname) not in imported
        )
    existing_keys = {key for node in existing if (key := node_key(node)) is not None}
    generated_keys = [node_key(node) for node in generated]
    for generated_index, node in enumerate(generated):
        key = generated_keys[generated_index]
        if isinstance(node, ast.ImportFrom) and any(
            isinstance(statement, ast.ImportFrom)
            and statement.module == node.module
            and statement.level == node.level
            and all(
                (alias.name, alias.asname) in {(item.name, item.asname) for item in statement.names}
                for alias in node.names
            )
            for statement in existing
        ):
            continue
        if key is None or key in existing_keys:
            continue
        following = next(
            (
                candidate
                for candidate in generated_keys[generated_index + 1 :]
                if candidate in existing_keys
            ),
            None,
        )
        if following is None:
            insertion = len(existing)
        else:
            insertion = next(
                index
                for index, candidate in enumerate(existing)
                if node_key(candidate) == following
            )
        if isinstance(node, ast.ClassDef):
            base_names = {base.id for base in node.bases if isinstance(base, ast.Name)}
            base_indices = [
                index
                for index, candidate in enumerate(existing)
                if isinstance(candidate, ast.ClassDef) and candidate.name in base_names
            ]
            if base_indices:
                insertion = max(insertion, max(base_indices) + 1)
        existing.insert(insertion, node)
        existing_keys.add(key)


def docstring_node(body: list[ast.stmt]) -> ast.Expr | None:
    if not body:
        return None
    node = body[0]
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
        if isinstance(node.value.value, str):
            return node
    return None


def insert_docstring(existing: list[ast.stmt], generated: list[ast.stmt]) -> None:
    if docstring_node(existing) is None and (node := docstring_node(generated)) is not None:
        existing.insert(0, node)


def is_placeholder_function(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = function.body[1:] if docstring_node(function.body) is not None else function.body
    return len(body) == 1 and (
        isinstance(body[0], ast.Pass)
        or (
            isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and body[0].value.value is Ellipsis
        )
    )


def is_generated_dictionary(node: ast.ClassDef) -> bool:
    return any(
        isinstance(decorator, ast.Attribute)
        and isinstance(decorator.value, ast.Name)
        and decorator.value.id == "js"
        and decorator.attr == "dictionary"
        for decorator in node.decorator_list
    )


def mark_dictionary(node: ast.ClassDef) -> None:
    for index, decorator in enumerate(node.decorator_list):
        if isinstance(decorator, ast.Name) and decorator.id == "js":
            node.decorator_list[index] = ast.Attribute(
                value=ast.Name(id="js", ctx=ast.Load()),
                attr="dictionary",
                ctx=ast.Load(),
            )
            return


def assigned_argument(statement: ast.stmt) -> tuple[str, str] | None:
    key = node_key(statement)
    if key is None or key[0] != "self-attribute":
        return None
    value = statement.value if isinstance(statement, (ast.Assign, ast.AnnAssign)) else None
    if isinstance(value, ast.IfExp):
        if isinstance(value.orelse, ast.Name):
            value = value.orelse
        elif isinstance(value.body, ast.Name):
            value = value.body
    if not isinstance(value, ast.Name):
        return None
    return key[1], value.id


def assigned_arguments(statement: ast.stmt) -> dict[str, str]:
    return {
        assignment[0]: assignment[1]
        for node in ast.walk(statement)
        if isinstance(node, ast.stmt)
        and (assignment := assigned_argument(node)) is not None
    }


def assigned_local_names(statement: ast.stmt) -> set[str]:
    return {
        target.id
        for node in ast.walk(statement)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else (node.target,)
        )
        if isinstance(target, ast.Name)
    }


def function_arguments(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, ast.arg]:
    arguments = (
        function.args.posonlyargs + function.args.args + function.args.kwonlyargs
    )
    return {argument.arg: argument for argument in arguments if argument.arg != "self"}


def synchronize_dictionary_initializer(
    existing: ast.FunctionDef | ast.AsyncFunctionDef,
    generated: ast.FunctionDef | ast.AsyncFunctionDef,
) -> None:
    """Add WebIDL fields without changing an editable dictionary's Python API."""
    existing_fields = {
        field
        for statement in existing.body
        for field in assigned_arguments(statement)
    }
    generated_fields = {
        field: argument
        for statement in generated.body
        for field, argument in assigned_arguments(statement).items()
    }
    generated_arguments = function_arguments(generated)
    generated_kw_defaults = dict(
        zip(
            (argument.arg for argument in generated.args.kwonlyargs),
            generated.args.kw_defaults,
            strict=True,
        )
    )
    positional_defaults = dict(
        zip(
            (argument.arg for argument in generated.args.args[-len(generated.args.defaults) :]),
            generated.args.defaults,
            strict=True,
        )
        if generated.args.defaults
        else ()
    )

    for field_name, generated_argument_name in generated_fields.items():
        generated_argument = generated_arguments[generated_argument_name]
        if field_name in existing_fields:
            continue

        existing.args.kwonlyargs.append(copy.deepcopy(generated_argument))
        default = generated_kw_defaults.get(
            generated_argument_name, positional_defaults.get(generated_argument_name)
        )
        existing.args.kw_defaults.append(copy.deepcopy(default))
        assignment_index, assignment = next(
            (index, statement)
            for index, statement in enumerate(generated.body)
            if assigned_arguments(statement).get(field_name) == generated_argument_name
        )
        existing.body.extend(
            copy.deepcopy(statement)
            for statement in generated.body[:assignment_index]
            if generated_argument_name in assigned_local_names(statement)
        )
        existing.body.append(copy.deepcopy(assignment))

    insert_docstring(existing.body, generated.body)


def remove_legacy_webidl_attributes(node: ast.ClassDef) -> None:
    helper = next(
        (
            statement
            for statement in node.body
            if isinstance(statement, ast.FunctionDef) and statement.name == "_webidl_attributes"
        ),
        None,
    )
    if helper is None:
        return
    attributes = {
        key[1]
        for statement in helper.body
        if (key := node_key(statement)) is not None and key[0] == "self-attribute"
    }
    class_attributes = {
        target.id
        for statement in node.body
        if isinstance(statement, ast.Assign)
        for target in statement.targets
        if isinstance(target, ast.Name)
    }
    initializer = next(
        (
            statement
            for statement in node.body
            if isinstance(statement, ast.FunctionDef) and statement.name == "__init__"
        ),
        None,
    )
    if initializer is None:
        initializer = ast.parse("def __init__(self): ...").body[0]
        node.body.insert(node.body.index(helper), initializer)
    if is_placeholder_function(initializer):
        initializer.body = []
    insert_missing(
        initializer.body,
        [
            statement
            for statement in helper.body
            if (key := node_key(statement)) is None
            or key[0] != "self-attribute"
            or key[1] not in class_attributes
        ],
    )
    node.body = [
        statement
        for statement in node.body
        if statement is not helper
        and not (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id in attributes
        )
    ]


def assigned_class_names(body: list[ast.stmt]) -> set[str]:
    names = set()
    for statement in body:
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            names.add(statement.target.id)
        elif isinstance(statement, ast.Assign):
            names.update(target.id for target in statement.targets if isinstance(target, ast.Name))
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            isinstance(decorator, ast.Name) and decorator.id == "property"
            for decorator in statement.decorator_list
        ):
            names.add(statement.name)
    return names


def preserve_explicit_class_attributes(existing: ast.ClassDef, generated: ast.ClassDef) -> None:
    class_attributes = assigned_class_names(existing.body)
    initializer = next(
        (
            statement
            for statement in generated.body
            if isinstance(statement, ast.FunctionDef) and statement.name == "__init__"
        ),
        None,
    )
    if initializer is None:
        return
    initializer.body = [
        statement
        for statement in initializer.body
        if not (
            (key := node_key(statement)) is not None
            and key[0] == "self-attribute"
            and key[1] in class_attributes
        )
    ]
    if not initializer.body:
        initializer.body.append(ast.Expr(ast.Constant(Ellipsis)))


def is_generated_initializer(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    def generated_statement(statement: ast.stmt) -> bool:
        return (
            isinstance(statement, (ast.Assign, ast.AnnAssign, ast.Pass))
            or is_super_init_call(statement)
            or isinstance(statement, ast.If)
            and all(generated_statement(child) for child in statement.body + statement.orelse)
            or (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and statement.value.value is Ellipsis
            )
        )

    return function.name == "__init__" and all(
        generated_statement(statement) for statement in function.body
    )


def is_generated_only_class(node: ast.ClassDef) -> bool:
    documentation = docstring_node(node.body)
    if documentation is None or not documentation.value.value.startswith("WebIDL source:"):
        return False
    return all(
        statement is documentation
        or isinstance(statement, (ast.Assign, ast.AnnAssign, ast.Pass))
        or isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and (is_placeholder_function(statement) or is_generated_initializer(statement))
        for statement in node.body
    )


def module_annotation_names(module: ast.Module) -> set[str]:
    annotations = []
    for node in ast.walk(module):
        if isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        elif isinstance(node, ast.arg) and node.annotation is not None:
            annotations.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns:
            annotations.append(node.returns)
        elif isinstance(node, ast.ClassDef):
            annotations.extend(node.bases)
    return {
        child.id
        for annotation in annotations
        for child in ast.walk(annotation)
        if isinstance(child, ast.Name)
    }


def retained_webidl_names(module: ast.Module, registry: dict[str, Definition]) -> set[str]:
    """Return WebIDL references without mistaking Python built-ins for Web APIs."""
    return (module_annotation_names(module) - PYTHON_BUILTIN_NAMES) & registry.keys()


def synchronize(existing: ast.Module, generated: ast.Module) -> ast.Module:
    generated_classes = {
        node.name: node for node in generated.body if isinstance(node, ast.ClassDef)
    }
    generated_imports = {
        alias.asname or alias.name
        for node in generated.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    referenced_names = module_annotation_names(existing) - PYTHON_BUILTIN_NAMES
    existing.body = [
        node
        for node in existing.body
        if not (
            isinstance(node, ast.ClassDef)
            and node.name not in generated_classes
            and is_generated_only_class(node)
            and (node.name in generated_imports or node.name not in referenced_names)
        )
    ]
    for node in existing.body:
        if isinstance(node, ast.ClassDef):
            remove_legacy_webidl_attributes(node)
    insert_docstring(existing.body, generated.body)
    insert_missing(existing.body, generated.body)
    for node in existing.body:
        if isinstance(node, ast.ClassDef) and node.name in generated_classes:
            generated_class = generated_classes[node.name]
            generated_dictionary = is_generated_dictionary(generated_class)
            if generated_dictionary:
                mark_dictionary(node)
            preserve_explicit_class_attributes(node, generated_class)
            insert_docstring(node.body, generated_class.body)
            insert_missing(node.body, generated_class.body)
            generated_functions = {
                function.name: function
                for function in generated_class.body
                if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for function in node.body:
                if (
                    isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and function.name in generated_functions
                ):
                    generated_function = generated_functions[function.name]
                    if generated_dictionary and function.name == "__init__":
                        synchronize_dictionary_initializer(function, generated_function)
                    else:
                        insert_docstring(function.body, generated_function.body)
                        insert_missing(function.body, generated_function.body)
    return ast.fix_missing_locations(existing)


def order_module_classes(module: ast.Module) -> ast.Module:
    classes = [node for node in module.body if isinstance(node, ast.ClassDef)]
    class_names = {node.name for node in classes}
    pending = list(classes)
    ordered = []
    emitted = set()
    while pending:
        ready = [
            node
            for node in pending
            if all(
                not isinstance(base, ast.Name)
                or base.id not in class_names
                or base.id in emitted
                for base in node.bases
            )
        ]
        if not ready:
            names = ", ".join(node.name for node in pending)
            raise RuntimeError(f"Python class inheritance cycle involving {names}.")
        for node in ready:
            ordered.append(node)
            emitted.add(node.name)
            pending.remove(node)
    replacements = iter(ordered)
    module.body = [
        next(replacements) if isinstance(node, ast.ClassDef) else node for node in module.body
    ]
    return ast.fix_missing_locations(module)


def order_module_imports(module: ast.Module) -> ast.Module:
    documentation = docstring_node(module.body)
    imports = [
        node for node in module.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    body = [
        node for node in module.body if not isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    insertion = 1 if documentation is not None else 0
    body[insertion:insertion] = imports
    module.body = body
    return ast.fix_missing_locations(module)


def native_instance(node: ast.stmt) -> str | None:
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return None
    call = node.value
    if not (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "js"
        and call.func.attr == "native"
        and call.args
    ):
        return None
    instance = call.args[0]
    return instance.id if isinstance(instance, ast.Name) else None


def place_global_instances(
    module: ast.Module, global_instances: dict[str, tuple[str, ...]]
) -> ast.Module:
    if not global_instances:
        return module

    instance_names = {
        instance_name for names in global_instances.values() for instance_name in names
    }
    assignment_keys = {("assignment", name) for name in instance_names}
    module.body = [
        node
        for node in module.body
        if node_key(node) not in assignment_keys and native_instance(node) not in instance_names
    ]

    pyjs_import = next(
        (
            node
            for node in module.body
            if isinstance(node, ast.ImportFrom) and node.module == "pyjs" and node.level == 0
        ),
        None,
    )
    if pyjs_import is None:
        pyjs_import = ast.ImportFrom("pyjs", [ast.alias("js")], 0)
        module.body.insert(0, pyjs_import)
    elif not any(alias.name == "js" for alias in pyjs_import.names):
        pyjs_import.names.append(ast.alias("js"))

    for class_name, names in global_instances.items():
        class_index = next(
            index
            for index, node in enumerate(module.body)
            if isinstance(node, ast.ClassDef) and node.name == class_name
        )
        nodes = []
        for name in names:
            nodes.extend(
                ast.parse(f"{name} = {class_name}()\njs.native({name})\n").body
            )
        module.body[class_index + 1 : class_index + 1] = nodes
    return ast.fix_missing_locations(module)


def format_source(source: str, output: Path) -> str:
    ruff = Path(sys.executable).with_name("ruff")
    formatted = subprocess.run(
        [ruff, "format", "--stdin-filename", str(output), "-"],
        input=source,
        text=True,
        capture_output=True,
        check=True,
        cwd=ROOT,
    ).stdout
    organized = subprocess.run(
        [ruff, "check", "--fix-only", "--stdin-filename", str(output), "-"],
        input=formatted,
        text=True,
        capture_output=True,
        check=True,
        cwd=ROOT,
    ).stdout
    return subprocess.run(
        [ruff, "format", "--stdin-filename", str(output), "-"],
        input=organized,
        text=True,
        capture_output=True,
        check=True,
        cwd=ROOT,
    ).stdout


def named_blocks(source: str, pattern: str) -> dict[str, tuple[str, str]]:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    blocks = {}
    for match in re.finditer(pattern, source, re.MULTILINE):
        depth = 1
        index = match.end()
        while index < len(source) and depth:
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
            index += 1
        blocks[match.group("name")] = (
            match.groupdict().get("bases") or "",
            source[match.end() : index - 1],
        )
    return blocks


def dart_surface(path: Path) -> dict[str, set[str]]:
    source = "\n".join(file.read_text() for file in sorted(path.glob("*.dart")))
    blocks = named_blocks(
        source,
        r"^extension\s+type\s+(?P<name>[A-Za-z_$][\w$]*)\._\([^\n]*\)\s+"
        r"implements\s+(?P<bases>[^\{]+)\{",
    )
    result = {}
    for name, (_, body) in blocks.items():
        members = set(re.findall(r"\b(?:get|set)\s+([A-Za-z_$][\w$]*)", body))
        for statement in re.findall(r"\bexternal\b[^;]+;", body, re.DOTALL):
            matches = re.findall(r"\b([A-Za-z_$][\w$]*)\s*(?:<[^;()]*>)?\s*\(", statement)
            if matches:
                member = matches[-1]
                members.add("__init__" if member == name else member)
        members.update(re.findall(r"\bstatic\s+const\s+\S+\s+([A-Za-z_$][\w$]*)", body))
        result[name] = members
    return result


def validate_surface(
    label: str, actual: dict[str, set[str]], definitions: dict[str, Definition]
) -> None:
    expected = {name: definition for name, definition in definitions.items() if not definition.stub}
    missing_definitions = sorted(expected.keys() - actual.keys())
    missing_members = []
    for name, definition in expected.items():
        if name not in actual:
            continue
        expected_members = {
            member.name for member in definition.members if member.kind != "constructor"
        }
        for member in sorted(expected_members - actual[name]):
            missing_members.append(f"{name}.{member}")
    print(
        f"{label}: {len(expected) - len(missing_definitions)}/{len(expected)} definitions; "
        f"{sum(len(value) for value in actual.values())} reference members"
    )
    if missing_definitions:
        missing = ", ".join(missing_definitions[:12])
        print(f"  missing definitions ({len(missing_definitions)}): {missing}")
    if missing_members:
        print(f"  missing members ({len(missing_members)}): {', '.join(missing_members[:12])}")


def validate_external(definitions: dict[str, Definition], data: dict) -> None:
    if data["unhandled"]:
        print("WebIDL constructs deferred by this slice: " + ", ".join(data["unhandled"]))
    validation = data["validation"]
    for label, key in (
        ("TypeScript-only definitions", "typescript_only_definitions"),
        ("WebIDL-only definitions", "webidl_only_definitions"),
    ):
        values = validation[key]
        print(f"{label} ({len(values)}): {', '.join(values[:12])}")
    typescript = {
        name: {member.name for member in definition.members if member.typescript}
        for name, definition in definitions.items()
        if definition.typescript is not None
    }
    validate_surface(
        "TypeScript "
        f"{data['generator']['typescript_version']} / @types/web "
        f"{data['generator']['types_web_version']}",
        typescript,
        definitions,
    )
    if DART_DOM.exists():
        validate_surface("Dart", dart_surface(DART_DOM), definitions)
    else:
        print(f"Dart: skipped; no generated DOM directory at {DART_DOM}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronize WebIDL browser bindings.")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="compare the emitted surface with local TypeScript and Dart checkouts",
    )
    arguments = parser.parse_args()

    data = extracted_registry()
    registry = registry_from_json(data)
    validate_module_specs(registry)
    print_module_report(registry)
    for spec in PUBLIC_MODULES:
        source = spec.output.read_text() if spec.output.exists() else None
        for _ in range(5):
            existing = ast.parse(source) if source is not None else None
            retained_names = (
                retained_webidl_names(existing, registry)
                if existing is not None
                else set()
            )
            generated, _ = generated_public_module(registry, spec, retained_names)
            result = synchronize(existing, generated) if existing is not None else generated
            result = order_module_imports(result)
            result = order_module_classes(result)
            result = place_global_instances(result, spec.all_global_instances)
            updated_source = format_source(ast.unparse(result) + "\n", spec.output)
            if updated_source == source:
                break
            source = updated_source
        else:
            raise RuntimeError(f"{spec.name}: WebIDL synchronization did not converge")
        spec.output.write_text(source)
    validate_output_dependencies()
    if arguments.validate:
        definitions = target_definitions(registry)
        validate_external(definitions, data)


if __name__ == "__main__":
    main()
