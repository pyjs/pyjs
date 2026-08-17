import annotationlib
import asyncio
import importlib
import inspect
import json
import secrets
import sys
import threading
import types
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import MappingProxyType
from typing import Union, get_args, get_origin
from urllib.parse import urlsplit

from websockets.asyncio.server import ServerConnection
from websockets.asyncio.server import serve as websocket_serve
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

from pyjs import js, nojs
from pyjs.javascript import _stringify_unchecked
from pyjs.server import live as _live
from pyjs.server.errors import (
    OperationError,
    OperationIssue,
    parse_operation_error,
)
from pyjs.server.errors import operation_error as operation_error
from pyjs.server.jsonapi import DecodedJSONAPIDocument, JSONAPIDecoder
from pyjs.server.protocol import InvalidationPayload as InvalidationPayload
from pyjs.server.transport import (
    ClientTransport,
    FetchTransport,
)
from pyjs.server.transport import (
    TransportResponse as TransportResponse,
)
from pyjs.server.watch import LiveSession as LiveSession
from pyjs.server.watch import WatchedQuery as WatchedQuery
from pyjs.transpiler import prepare_bundle
from pyjs.web.domx import HTMLElement, tag
from pyjs.web.navigation import NAVIGATION_HEADER, navigation_page
from pyjs.web.ssr import render_document, render_html, write_html

Invalidation = _live.Invalidation
InvalidationHub = _live.InvalidationHub
InvalidationSubscription = _live.InvalidationSubscription
api_topic = _live.api_topic
resource_topic = _live.resource_topic

SESSION_COOKIE_NAME = "pyjs-session"
MAX_REQUEST_BODY_SIZE = 64 * 1024


class Operation:
    def __init__(self, kind: str, function):
        self.kind = kind
        self.function = function
        self.name = function.__name__
        self.signature = inspect.signature(function)
        self.jsonapi = False
        self.jsonapi_many = False
        self.client_model_references = {}


def _operation_argument_names(operation: Operation) -> list[str]:
    return [
        parameter.name
        for parameter in operation.signature.parameters.values()
        if parameter.name != "self"
    ]


def _client_model_map_source(operation: Operation) -> str:
    models = ", ".join(
        f"[{resource_type!r}, {model_reference}]"
        for resource_type, model_reference in (
            operation.client_model_references.items()
        )
    )
    return f"new Map([{models}])"


def _client_operation_source(operation: Operation) -> str:
    function = operation.function
    signature = operation.signature
    arguments = _operation_argument_names(operation)
    payload = ", ".join(f"{name}: {name}" for name in arguments)
    return_type = signature.return_annotation
    validate = getattr(return_type, "model_validate", None)
    request = (
        f"await this._request('{function.__name__}', "
        f"{{{payload}}})"
    )
    if operation.jsonapi:
        return "\n".join(
            (
                f"const $document = new $JSONAPIDecoder(JSON.parse({request}), "
                f"{_client_model_map_source(operation)});",
                "this._document = $document;",
                "return $document.data;",
            )
        )
    lines = [f"const $value = JSON.parse({request});"]
    if validate is not None:
        function.__pyjs_source_dependencies__ = (return_type,)
        lines.append(f"return new {return_type.__name__}($value);")
    else:
        lines.append("return $value;")
    return "\n".join(lines)


def _client_operation_binding_source(
    operation: Operation,
    source: str,
    receiver: str,
) -> str:
    arguments = _operation_argument_names(operation)
    return_type = operation.signature.return_annotation
    if operation.jsonapi:
        decode = (
            "($value) => { const $document = new $JSONAPIDecoder($value, "
            f"{_client_model_map_source(operation)}); "
            f"{receiver}._document = $document; "
            "return $document.data; }"
        )
    elif getattr(return_type, "model_validate", None) is not None:
        decode = f"($value) => new {return_type.__name__}($value)"
    else:
        decode = "($value) => $value"
    return (
        f"Object.assign({source}.bind({receiver}), {{"
        f"$operation: {receiver}._path + '/{operation.function.__name__}', "
        f"$arguments: {arguments!r}, $decode: {decode}"
        "})"
    )


def operation(kind: str):
    def decorate(function):
        if not inspect.iscoroutinefunction(function):
            raise TypeError(f"@{kind} requires an async function")
        remote_operation = Operation(kind, function)
        function.__pyjs_operation__ = remote_operation
        js(function)
        return_type = remote_operation.signature.return_annotation
        if getattr(return_type, "model_validate", None):
            function.__pyjs_source_dependencies__ = (return_type,)
        function.source(lambda: _client_operation_source(remote_operation))
        function.__js_bind_source__ = (
            lambda source, receiver: _client_operation_binding_source(
                remote_operation,
                source,
                receiver,
            )
        )
        return function

    return decorate


query = operation("query")
mutation = operation("mutation")
action = operation("action")


@js
class Relationship[Value, ResourceType = None]:
    pass


@dataclass(frozen=True)
class APIMetadata:
    path: tuple[str, ...]
    api_type: type


@dataclass(frozen=True)
class ResourceMetadata(APIMetadata):
    model_type: type

    @property
    def resource_type(self) -> type:
        return self.api_type


@dataclass(frozen=True)
class OperationMetadata:
    identity: str
    owner: APIMetadata
    name: str
    kind: str
    argument_names: tuple[str, ...]
    operation: Operation


@dataclass(frozen=True)
class RelationshipMetadata:
    name: str
    owner: ResourceMetadata
    value_type: type
    model_type: type
    target: ResourceMetadata
    many: bool
    nullable: bool


@dataclass(frozen=True)
class IncludeMetadata:
    path: str
    relationships: tuple[RelationshipMetadata, ...]

    @property
    def target(self) -> ResourceMetadata:
        return self.relationships[-1].target


@dataclass(frozen=True)
class ResourceGraph:
    root_type: type
    api_nodes: tuple[APIMetadata, ...]
    resources: tuple[ResourceMetadata, ...]
    operations: tuple[OperationMetadata, ...]
    relationships: tuple[RelationshipMetadata, ...]
    api_nodes_by_path: Mapping[tuple[str, ...], APIMetadata]
    resources_by_path: Mapping[tuple[str, ...], ResourceMetadata]
    resources_by_model: Mapping[type, tuple[ResourceMetadata, ...]]
    resources_by_type: Mapping[type, ResourceMetadata]
    operations_by_identity: Mapping[str, OperationMetadata]
    relationships_by_key: Mapping[tuple[type, str], RelationshipMetadata]


def _client_model_types(
    graph: ResourceGraph,
    owner: ResourceMetadata,
) -> dict[str, type]:
    model_types = {}
    pending = deque([owner])
    visited = set()
    while pending:
        resource = pending.popleft()
        if resource.resource_type in visited:
            continue
        visited.add(resource.resource_type)
        model_types[resource.path[-1]] = resource.model_type
        children = resource.resource_type.__pyjs_api_children__
        for relationship in graph.relationships:
            if (
                relationship.owner is resource
                and relationship.name in children
            ):
                pending.append(relationship.target)
    return model_types


def _relationship_shape(value_type: type) -> tuple[type, bool, bool]:
    nullable = False
    origin = get_origin(value_type)
    if origin in (types.UnionType, Union):
        members = list(get_args(value_type))
        if type(None) in members:
            nullable = True
            members.remove(type(None))
        if len(members) != 1:
            raise TypeError(
                "A relationship must identify exactly one related model type."
            )
        value_type = members[0]
        origin = get_origin(value_type)

    many = origin is list
    if many:
        arguments = get_args(value_type)
        if len(arguments) != 1:
            raise TypeError("A to-many relationship requires one item type.")
        model_type = arguments[0]
        if get_origin(model_type) in (types.UnionType, Union):
            raise TypeError("A relationship collection cannot contain null values.")
    else:
        model_type = value_type
    if not isinstance(model_type, type):
        raise TypeError("A relationship target must be a model type.")
    return model_type, many, nullable


def _resource_path(path: tuple[str, ...]) -> str:
    return ".".join(path)


def _contains_forward_reference(annotation: object) -> bool:
    return isinstance(annotation, annotationlib.ForwardRef) or any(
        _contains_forward_reference(argument) for argument in get_args(annotation)
    )


def _build_resource_graph(root_type: type) -> ResourceGraph:
    api_nodes = []
    resources = []
    operations = []
    seen_types = {}

    def visit(api_type: type, path: tuple[str, ...]):
        model_type = getattr(api_type, "__pyjs_model__", None)
        if model_type is not None:
            previous_path = seen_types.get(api_type)
            if previous_path is not None:
                raise TypeError(
                    f"{api_type.__name__} is mounted at both "
                    f"'{_resource_path(previous_path)}' and "
                    f"'{_resource_path(path)}'; use distinct resource subclasses."
                )
            seen_types[api_type] = path
            node = ResourceMetadata(path, api_type, model_type)
            resources.append(node)
        else:
            node = APIMetadata(path, api_type)
        api_nodes.append(node)
        for operation_name, remote_operation in api_type.__pyjs_operations__.items():
            remote_operation.jsonapi = False
            remote_operation.jsonapi_many = False
            if isinstance(node, ResourceMetadata):
                try:
                    result_model, many, _nullable = _relationship_shape(
                        remote_operation.signature.return_annotation
                    )
                except TypeError:
                    pass
                else:
                    remote_operation.jsonapi = result_model is node.model_type
            if remote_operation.jsonapi:
                remote_operation.jsonapi_many = many
            identity = ".".join((*path, operation_name))
            argument_names = tuple(
                parameter.name
                for parameter in remote_operation.signature.parameters.values()
                if parameter.name != "self"
            )
            operations.append(
                OperationMetadata(
                    identity=identity,
                    owner=node,
                    name=operation_name,
                    kind=remote_operation.kind,
                    argument_names=argument_names,
                    operation=remote_operation,
                )
            )
        for name, child_type in api_type.__pyjs_api_children__.items():
            visit(child_type, (*path, name))

    visit(root_type, ())
    resources_by_model = {}
    resources_by_type = {}
    for resource in resources:
        resources_by_model.setdefault(resource.model_type, []).append(resource)
        resources_by_type[resource.resource_type] = resource

    relationships = []
    for owner in resources:
        resource_type = owner.resource_type
        declared = dict(resource_type.__pyjs_relationships__)
        selected = dict(resource_type.__pyjs_relationship_resources__)
        unresolved = [
            name
            for name, value_type in declared.items()
            if _contains_forward_reference(value_type)
        ]
        if unresolved:
            try:
                annotations = annotationlib.get_annotations(
                    resource_type,
                    format=annotationlib.Format.VALUE,
                )
            except NameError as error:
                raise TypeError(
                    f"Could not resolve annotations for {resource_type.__name__}: "
                    f"{error}."
                ) from error
            for name in unresolved:
                annotation = annotations.get(name)
                if get_origin(annotation) is Relationship:
                    declared[name], selected[name] = get_args(annotation)
        for name, value_type in declared.items():
            model_type, many, nullable = _relationship_shape(value_type)
            selected_type = selected.get(name)
            candidates = resources_by_model.get(model_type, [])
            if selected_type is not None:
                target = resources_by_type.get(selected_type)
                if target is None:
                    raise TypeError(
                        f"Relationship {resource_type.__name__}.{name} selects "
                        f"{selected_type.__name__}, which is not mounted in "
                        f"{root_type.__name__}."
                    )
                if target.model_type is not model_type:
                    raise TypeError(
                        f"Relationship {resource_type.__name__}.{name} targets "
                        f"{model_type.__name__}, but {selected_type.__name__} "
                        f"exposes {target.model_type.__name__}."
                    )
            elif not candidates:
                raise TypeError(
                    f"Relationship {resource_type.__name__}.{name} targets "
                    f"{model_type.__name__}, but no resource for that model is "
                    f"mounted in {root_type.__name__}."
                )
            elif len(candidates) > 1:
                choices = ", ".join(
                    f"{candidate.resource_type.__name__} at "
                    f"'{_resource_path(candidate.path)}'"
                    for candidate in candidates
                )
                raise TypeError(
                    f"Relationship {resource_type.__name__}.{name} has multiple "
                    f"resources for {model_type.__name__}: {choices}. Select a "
                    "resource type as the second Relationship argument."
                )
            else:
                target = candidates[0]
            relationships.append(
                RelationshipMetadata(
                    name=name,
                    owner=owner,
                    value_type=value_type,
                    model_type=model_type,
                    target=target,
                    many=many,
                    nullable=nullable,
                )
            )

    graph = ResourceGraph(
        root_type=root_type,
        api_nodes=tuple(api_nodes),
        resources=tuple(resources),
        operations=tuple(operations),
        relationships=tuple(relationships),
        api_nodes_by_path=MappingProxyType(
            {node.path: node for node in api_nodes}
        ),
        resources_by_path=MappingProxyType(
            {resource.path: resource for resource in resources}
        ),
        resources_by_model=MappingProxyType(
            {
                model_type: tuple(model_resources)
                for model_type, model_resources in resources_by_model.items()
            }
        ),
        resources_by_type=MappingProxyType(resources_by_type),
        operations_by_identity=MappingProxyType(
            {operation.identity: operation for operation in operations}
        ),
        relationships_by_key=MappingProxyType(
            {
                (relationship.owner.resource_type, relationship.name): relationship
                for relationship in relationships
            }
        ),
    )
    public_types = {}
    for resource in resources:
        public_type = resource.path[-1]
        previous = public_types.get(public_type)
        if previous is not None and previous is not resource.model_type:
            raise TypeError(
                f"JSON:API resource type {public_type!r} is used for both "
                f"{previous.__name__} and {resource.model_type.__name__}."
            )
        public_types[public_type] = resource.model_type
    for operation_metadata in operations:
        remote_operation = operation_metadata.operation
        if not remote_operation.jsonapi:
            continue
        owner = operation_metadata.owner
        model_types = _client_model_types(graph, owner)
        source_imports = {"$JSONAPIDecoder": JSONAPIDecoder}
        source_dependencies = []
        model_references = {}
        namespace = remote_operation.function.__globals__
        for index, (public_type, model_type) in enumerate(model_types.items()):
            model_name = model_type.__name__
            if namespace.get(model_name) is model_type:
                model_reference = model_name
                source_dependencies.append(model_type)
            else:
                model_reference = f"$JSONAPIModel{index}"
                source_imports[model_reference] = model_type
            model_references[public_type] = model_reference
        remote_operation.client_model_references = model_references
        remote_operation.function.__js_source_imports__ = source_imports
        remote_operation.function.__pyjs_source_dependencies__ = tuple(
            source_dependencies
        )
    return graph


def resource_graph(root: type | object) -> ResourceGraph:
    root_type = root if isinstance(root, type) else type(root)
    graph = root_type.__dict__.get("__pyjs_resource_graph__")
    if graph is None:
        graph = _build_resource_graph(root_type)
        root_type.__pyjs_resource_graph__ = graph
    return graph


def resolve_include_paths(
    root: type | object,
    resource_type: type,
    paths: list[str],
) -> tuple[IncludeMetadata, ...]:
    graph = resource_graph(root)
    owner = graph.resources_by_type.get(resource_type)
    if owner is None:
        raise TypeError(
            f"{resource_type.__name__} is not mounted in {graph.root_type.__name__}."
        )

    includes = []
    for path in paths:
        if not path or any(not segment for segment in path.split(".")):
            raise ValueError(f"Invalid relationship include path: {path!r}.")
        relationships = []
        current = owner
        for segment in path.split("."):
            relationship = graph.relationships_by_key.get(
                (current.resource_type, segment)
            )
            if relationship is None:
                raise ValueError(
                    f"Unknown relationship include '{segment}' on "
                    f"{current.resource_type.__name__} in path {path!r}."
                )
            relationships.append(relationship)
            current = relationship.target
        includes.append(IncludeMetadata(path, tuple(relationships)))
    return tuple(includes)


async def dispatch_operation(
    root: type | object,
    identity: str,
    values: object,
    request: object = None,
    *,
    serialize: bool = True,
) -> object:
    from pydantic import TypeAdapter, ValidationError

    if not isinstance(values, dict):
        raise TypeError("Operation arguments must be a JSON object.")
    graph = resource_graph(root)
    operation_metadata = graph.operations_by_identity.get(identity)
    if operation_metadata is None:
        raise TypeError(f"Unknown operation: {identity}.")

    root_type = root if isinstance(root, type) else type(root)
    resource = root_type()
    for name in operation_metadata.owner.path:
        resource = getattr(resource, name)
    resource.request = request

    operation = operation_metadata.operation
    parameters = list(operation.signature.parameters.values())[1:]
    expected = set(operation_metadata.argument_names)
    unexpected = set(values) - expected
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise TypeError(f"Unexpected argument(s): {names}.")

    arguments = {}
    for parameter in parameters:
        if parameter.name not in values:
            if parameter.default is not inspect.Parameter.empty:
                continue
            raise TypeError(f"Missing argument: {parameter.name}.")
        try:
            arguments[parameter.name] = TypeAdapter(
                parameter.annotation
            ).validate_python(values[parameter.name])
        except ValidationError as error:
            issues = []
            for issue in error.errors(include_url=False):
                location = [parameter.name]
                location.extend(str(part) for part in issue["loc"])
                issues.append(
                    OperationIssue(
                        issue["msg"],
                        location,
                        422,
                        "Validation error",
                        issue["type"],
                    )
                )
            raise OperationError(issues) from error

    result = getattr(resource, operation.name)(**arguments)
    if inspect.isawaitable(result):
        result = await result
    if getattr(result, "__pyjs_deferred_operation_result__", False):
        return result
    result_adapter = TypeAdapter(operation.signature.return_annotation)
    result = result_adapter.validate_python(result)
    if not serialize:
        return result
    return result_adapter.dump_python(result, mode="json")


class ResourceAlias:
    def __init__(self, resource_type, model_type):
        self.resource_type = resource_type
        self.model_type = model_type

    def __mro_entries__(self, bases):
        return (self.resource_type,)


class APIChild:
    def __init__(self, child_type, relationship: bool = False):
        self.child_type = child_type
        self.relationship = relationship
        self.name = ""
        self.storage_name = ""

    def __set_name__(self, owner, name: str):
        self.name = name
        self.storage_name = f"__pyjs_api_{name}"

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        child = instance.__dict__.get(self.storage_name)
        if child is None:
            path = instance._path + "/" + self.name
            child = self.child_type(
                path,
                self.relationship,
                instance._transport,
                instance._timeout_ms,
            )
            instance.__dict__[self.storage_name] = child
        return child


def _api_javascript(
    class_name: str,
    children: dict[str, type],
    relationship_children: set[str],
    included: set[str],
) -> str:
    lines = []
    for name, child_type in children.items():
        if name not in included:
            continue
        storage = f"__pyjs_api_{name}"
        options = (
            f"path: this._path + '/{name}', transport: this._transport, "
            "timeout_ms: this._timeout_ms"
        )
        if name in relationship_children:
            options += ", relationship: true"
        lines.append(
            f"Object.defineProperty({class_name}.prototype, {name!r}, {{get() {{"
            f" return this.{storage} ||= new {child_type.__name__}"
            f"({{{options}}}); }} }});"
        )
    return "\n".join(lines)


class APIMetaclass(type):
    def __call__(cls, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)
        if (
            not args
            and not kwargs
            and getattr(cls, "__pyjs_model__", None) is None
        ):
            resource_graph(cls)
        return instance

    def __new__(mcls, name, bases, namespace, /, **kwargs):
        children = {}
        operations = {}
        relationships = {}
        relationship_resources = {}
        for base in bases:
            children.update(getattr(base, "__pyjs_api_children__", {}))
            operations.update(getattr(base, "__pyjs_operations__", {}))
            relationships.update(getattr(base, "__pyjs_relationships__", {}))
            relationship_resources.update(
                getattr(base, "__pyjs_relationship_resources__", {})
            )

        annotate = annotationlib.get_annotate_from_class_namespace(namespace)
        annotations = (
            annotationlib.call_annotate_function(
                annotate,
                annotationlib.Format.FORWARDREF,
            )
            if annotate is not None
            else {}
        )
        for attribute, annotation in annotations.items():
            origin = get_origin(annotation)
            if origin is Relationship:
                value_type, selected_resource = get_args(annotation)
                relationships[attribute] = value_type
                relationship_resources[attribute] = selected_resource
                if selected_resource is not None:
                    resource_type = globals().get("Resource")
                    try:
                        is_resource = issubclass(selected_resource, resource_type)
                    except TypeError:
                        is_resource = False
                    if not is_resource:
                        selected_name = getattr(
                            selected_resource,
                            "__name__",
                            repr(selected_resource),
                        )
                        raise TypeError(
                            f"Relationship {name}.{attribute} selects "
                            f"{selected_name}, which is not a Resource type."
                        )
                    children[attribute] = selected_resource
                    namespace[attribute] = APIChild(
                        selected_resource,
                        relationship=True,
                    )
                continue
            try:
                is_api = issubclass(annotation, API)
            except TypeError, NameError:
                is_api = False
            if is_api:
                children[attribute] = annotation
                namespace[attribute] = APIChild(annotation)

        for attribute, value in namespace.items():
            remote_operation = getattr(value, "__pyjs_operation__", None)
            if remote_operation is not None:
                operations[attribute] = remote_operation

        namespace["__pyjs_api_children__"] = children
        namespace["__pyjs_instance_annotations__"] = children
        namespace["__pyjs_operations__"] = operations
        namespace["__pyjs_relationships__"] = relationships
        namespace["__pyjs_relationship_resources__"] = relationship_resources
        for base in namespace.get("__orig_bases__", ()):
            if isinstance(base, ResourceAlias):
                namespace["__pyjs_model__"] = base.model_type
                js(base.model_type)
        namespace["__js_append__"] = lambda included: _api_javascript(
            name,
            children,
            set(relationships) & set(children),
            included,
        )
        namespace["__js_member_dependencies__"] = children
        return super().__new__(mcls, name, bases, namespace, **kwargs)


@js
class API(metaclass=APIMetaclass):
    def __init__(
        self,
        path: str = "/api",
        relationship: bool = False,
        transport: ClientTransport | None = None,
        timeout_ms: int = 0,
    ):
        self._path = path
        self._relationship = relationship
        self._transport: ClientTransport = (
            FetchTransport() if transport is None else transport
        )
        self._timeout_ms = timeout_ms
        self._document: DecodedJSONAPIDocument | None = None

    def related(
        self,
        identifier: str,
        relationship: API,
    ) -> object | None:
        if self._document is None:
            return None
        resource_type = self._path.split("/")[-1]
        relationship_name = relationship._path.split("/")[-1]
        return self._document.related(
            resource_type,
            identifier,
            relationship_name,
        )

    @js.keep
    async def _request(self, operation_name: str, values: object) -> str:
        response = await self._transport.request(
            self._path + "/" + operation_name,
            _stringify_unchecked(values),
            self._timeout_ms,
        )
        if not response.ok:
            raise parse_operation_error(response.body, response.status)
        return response.body

    @property
    @nojs
    def urls(self):
        from pyjs.server.django.api import urls_for

        resource_graph(self)
        return urls_for(self)

    @property
    @nojs
    def resource_graph(self):
        return resource_graph(self)


@js
class Resource(API):
    @nojs
    @classmethod
    def __class_getitem__(cls, model_type: type):
        return ResourceAlias(cls, model_type)


@js
def include_paths(resource: API, *relationships: API) -> list[str]:
    prefix = resource._path + "/"
    paths: list[str] = []
    for relationship in relationships:
        if not relationship._relationship:
            raise ValueError(
                "JSON:API includes must reference declared relationships."
            )
        if not relationship._path.startswith(prefix):
            raise ValueError(
                "JSON:API includes must descend from the base resource."
            )
        paths.append(relationship._path[len(prefix) :].replace("/", "."))
    return paths


def _server_url(host, port):
    if not host or host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    elif ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}/"


def _module_name(module):
    path = Path(module)
    if not path.is_file():
        return module

    source = path.resolve()
    for loaded_module in tuple(sys.modules.values()):
        spec = getattr(loaded_module, "__spec__", None)
        loaded_file = getattr(loaded_module, "__file__", None)
        if spec is not None and loaded_file is not None and Path(loaded_file).resolve() == source:
            return spec.name
    return path.stem


class ServerRequest:
    def __init__(self, method, path, headers, body, session, session_id, new_session):
        self.method = method
        self.path = path
        self.headers = headers
        self.body = body
        self.session = session
        self.session_id = session_id
        self.new_session = new_session

    def json(self):
        return json.loads(self.body.decode("utf-8"))


class ServerResponse:
    def __init__(self, body="", status=200, content_type="text/plain", headers=None):
        self.body = body
        self.status = status
        self.content_type = content_type
        self.headers = headers or {}


class NavigationPage:
    def __init__(self, body, title, status=200, headers=None):
        self.body = body
        self.title = title
        self.status = status
        self.headers = headers or {}


def websocket_response(response, request=None):
    body = response.body
    if isinstance(body, str):
        body = body.encode("utf-8")
    headers = Headers()
    if response.content_type is not None:
        headers["Content-Type"] = response.content_type
    headers["Content-Length"] = str(len(body))
    if request is not None and request.new_session:
        headers["Set-Cookie"] = (
            f"{SESSION_COOKIE_NAME}={request.session_id}; HttpOnly; Path=/; SameSite=Lax"
        )
    for name, value in response.headers.items():
        headers[name] = value
    status = HTTPStatus(response.status)
    return Response(status.value, status.phrase, headers, body)


def html(body, js, css, script_type, title=""):
    return tag(
        "html",
        tag(
            "head",
            tag("meta", {"charset": "utf-8"}),
            tag("title", title),
            tag("link", {"rel": "stylesheet", "href": css}),
        ),
        tag("body", body),
        tag("script", {"type": script_type, "src": js}, " "),
    )


def page(body, js, css, script_type="module", title=""):
    return render_document(html(body, js, css, script_type, title))


def navigation_fragment(body, title, layout_id):
    return render_html(
        tag(
            "div",
            tag("title", title),
            navigation_page(body, layout_id),
        )
    )


def write(parent: HTMLElement, src):
    write_html(parent, src)


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        server: PyjsServer = self.server
        server.refresh()
        path = urlsplit(self.path).path
        if path == "/" and ("GET", path) in server.routes:
            request = server.create_request("GET", path, self.headers, b"")
            self.send_server_response(server.dispatch(request), request)
        elif path == "/":
            request = server.create_request("GET", path, self.headers, b"")
            response = ServerResponse(
                page(
                    server.get_html(request),
                    f"{server.entry_point.container.name}.js",
                    "index.css",
                ),
                content_type="text/html",
            )
            self.send_server_response(response, request)
        elif path == "/index.css":
            self.send_server_response(ServerResponse(server.get_css(), content_type="text/css"))
        elif ("GET", path) in server.routes:
            request = server.create_request("GET", path, self.headers, b"")
            self.send_server_response(server.dispatch(request), request)
        elif path.endswith(".js"):
            module_name = Path(path).stem
            if module_name not in server.package:
                self.send_error(404)
                return
            self.send_server_response(
                ServerResponse(server.package[module_name], content_type="application/javascript")
            )
        else:
            self.send_error(404)

    def do_POST(self):
        server: PyjsServer = self.server
        server.refresh()
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return
        if content_length < 0:
            self.send_error(400, "Invalid Content-Length")
            return
        if content_length > MAX_REQUEST_BODY_SIZE:
            self.send_error(413, "Request body is too large")
            return

        path = urlsplit(self.path).path
        request = server.create_request(
            "POST",
            path,
            self.headers,
            self.rfile.read(content_length),
        )
        try:
            response = server.dispatch(request)
        except ValueError as error:
            response = ServerResponse(str(error), status=400)
        self.send_server_response(response, request)

    def send_server_response(self, response, request=None):
        body = response.body
        if isinstance(body, str):
            body = body.encode("utf-8")

        self.send_response(response.status)
        if response.content_type is not None:
            self.send_header("Content-Type", response.content_type)
        if body:
            self.send_header("Content-Length", str(len(body)))
        if request is not None and request.new_session:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE_NAME}={request.session_id}; HttpOnly; Path=/; SameSite=Lax",
            )
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        if body:
            self.wfile.write(body)


class PyjsApplication:
    def __init__(
        self,
        module: str,
        css: str,
        entry_point: str,
        *entry_point_args,
        render=None,
        routes=None,
        layout=None,
        layout_id="main",
        page_entry_points=(),
    ):
        self.module_name = _module_name(module)
        self.module = importlib.import_module(self.module_name)
        self.module_path = Path(self.module.__file__)
        self.module_last_modified = None
        self.package = None
        self.css_provided = bool(css)
        self.css = css
        self.entry_point = None
        self.entry_point_name = entry_point or "main"
        self.entry_point_args = entry_point_args
        self.render_name = self.callback_name(render) if render is not None else None
        self.layout_name = self.callback_name(layout) if layout is not None else None
        self.layout_id = layout_id
        self.page_entry_point_names = tuple(
            self.callback_name(callback) for callback in page_entry_points
        )
        self.routes = {
            (method.upper(), path): self.callback_name(callback)
            for (method, path), callback in (routes or {}).items()
        }
        self.sessions = {}
        self.refresh()

    def callback_name(self, callback):
        if isinstance(callback, str):
            return callback
        name = callback.__name__
        if not hasattr(self.module, name):
            raise ValueError("server callbacks must be module-level functions in the served module")
        return name

    def resolve_callback(self, name):
        return getattr(self.module, name)

    def create_request(self, method, path, headers, body):
        cookies = SimpleCookie(headers.get("Cookie", ""))
        session_cookie = cookies.get(SESSION_COOKIE_NAME)
        session_id = session_cookie.value if session_cookie is not None else None
        new_session = session_id not in self.sessions
        if new_session:
            session_id = secrets.token_urlsafe(24)
            self.sessions[session_id] = {}
        return ServerRequest(
            method,
            path,
            headers,
            body,
            self.sessions[session_id],
            session_id,
            new_session,
        )

    def dispatch(self, request):
        callback_name = self.routes.get((request.method, request.path))
        if callback_name is None:
            return ServerResponse("Not found", status=404)
        response = self.resolve_callback(callback_name)(request)
        if response is None:
            return ServerResponse(status=204, content_type=None)
        if isinstance(response, NavigationPage):
            return self.render_navigation_response(request, response)
        if not isinstance(response, ServerResponse):
            raise TypeError(
                "server route callbacks must return NavigationPage, ServerResponse, or None"
            )
        return response

    def render_navigation_response(self, request, response):
        if self.layout_name is None:
            raise TypeError("NavigationPage responses require a layout callback")

        headers = dict(response.headers)
        vary = headers.get("Vary")
        if vary is None:
            headers["Vary"] = NAVIGATION_HEADER
        elif NAVIGATION_HEADER.lower() not in vary.lower():
            headers["Vary"] = f"{vary}, {NAVIGATION_HEADER}"

        if request.headers.get(NAVIGATION_HEADER) == "1":
            body = navigation_fragment(response.body, response.title, self.layout_id)
        else:
            layout = self.resolve_callback(self.layout_name)(
                request,
                response.body,
                self.layout_id,
            )
            body = page(
                layout,
                f"{self.entry_point.container.name}.js",
                "index.css",
                title=response.title,
            )
        return ServerResponse(
            body,
            status=response.status,
            content_type="text/html",
            headers=headers,
        )

    def refresh(self):
        last_modified = self.module_path.stat().st_mtime
        if self.module_last_modified != last_modified:
            self.module_last_modified = last_modified
            importlib.reload(self.module)
            entry_point_py_func = getattr(self.module, self.entry_point_name)
            additional_entry_points = tuple(
                getattr(self.module, name) for name in self.page_entry_point_names
            )
            self.package, self.entry_point, css = prepare_bundle(
                entry_point_py_func,
                additional_entry_points=additional_entry_points,
            )
            if not self.css_provided:
                self.css = css
            for package_name, js in self.package.items():
                self.package[package_name] = js.encode("utf-8")

    def get_html(self, request=None):
        if self.render_name is not None:
            return self.resolve_callback(self.render_name)(request)
        return self.entry_point.py_func(*self.entry_point_args)

    def get_css(self):
        return self.css


class PyjsServer(HTTPServer, PyjsApplication):
    def __init__(
        self,
        module: str,
        css: str,
        entry_point: str,
        *entry_point_args,
        render=None,
        routes=None,
        layout=None,
        layout_id="main",
        page_entry_points=(),
        host="",
        port=8000,
    ):
        HTTPServer.__init__(self, (host, port), RequestHandler)
        PyjsApplication.__init__(
            self,
            module,
            css,
            entry_point,
            *entry_point_args,
            render=render,
            routes=routes,
            layout=layout,
            layout_id=layout_id,
            page_entry_points=page_entry_points,
        )

    def serve_forever(self, poll_interval=0.5):
        print(f"Serving at {_server_url(self.server_address[0], self.server_port)}")
        super().serve_forever(poll_interval)


class WebSocketPyjsServer(PyjsApplication):
    def __init__(
        self,
        module: str,
        css: str,
        entry_point: str,
        *entry_point_args,
        render=None,
        routes=None,
        layout=None,
        layout_id="main",
        page_entry_points=(),
        websocket_routes=None,
        host="",
        port=8000,
    ):
        super().__init__(
            module,
            css,
            entry_point,
            *entry_point_args,
            render=render,
            routes=routes,
            layout=layout,
            layout_id=layout_id,
            page_entry_points=page_entry_points,
        )
        self.websocket_routes = {
            path: self.callback_name(callback)
            for path, callback in (websocket_routes or {}).items()
        }
        self.host = host
        self.server_port = port
        self.started = threading.Event()
        self._loop = None
        self._shutdown_event = None
        self._shutdown_requested = False

    async def process_request(
        self,
        connection: ServerConnection,
        request: Request,
    ) -> Response | None:
        self.refresh()
        path = urlsplit(request.path).path
        if path in self.websocket_routes:
            return None
        if path == "/" and ("GET", path) in self.routes:
            server_request = self.create_request("GET", path, request.headers, b"")
            return websocket_response(self.dispatch(server_request), server_request)
        if path == "/":
            server_request = self.create_request("GET", path, request.headers, b"")
            response = ServerResponse(
                page(
                    self.get_html(server_request),
                    f"{self.entry_point.container.name}.js",
                    "index.css",
                ),
                content_type="text/html",
            )
            return websocket_response(response, server_request)
        if path == "/index.css":
            return websocket_response(ServerResponse(self.get_css(), content_type="text/css"))
        if ("GET", path) in self.routes:
            server_request = self.create_request("GET", path, request.headers, b"")
            return websocket_response(self.dispatch(server_request), server_request)
        if path.endswith(".js"):
            module_name = Path(path).stem
            if module_name not in self.package:
                return websocket_response(ServerResponse("Not found", status=404))
            return websocket_response(
                ServerResponse(self.package[module_name], content_type="application/javascript")
            )

        server_request = self.create_request("GET", path, request.headers, b"")
        return websocket_response(self.dispatch(server_request), server_request)

    async def handle_websocket(self, connection: ServerConnection):
        path = urlsplit(connection.request.path).path
        callback_name = self.websocket_routes.get(path)
        if callback_name is None:
            await connection.close(1008, "Unknown WebSocket route")
            return
        await self.resolve_callback(callback_name)(connection)

    async def run(self):
        self._loop = asyncio.get_running_loop()
        self._shutdown_event = asyncio.Event()
        if self._shutdown_requested:
            self._shutdown_event.set()
        async with websocket_serve(
            self.handle_websocket,
            self.host,
            self.server_port,
            process_request=self.process_request,
        ) as server:
            self.server_port = server.sockets[0].getsockname()[1]
            self.started.set()
            print(f"Serving at {_server_url(self.host, self.server_port)}")
            await self._shutdown_event.wait()

    def serve_forever(self):
        asyncio.run(self.run())

    def shutdown(self):
        self._shutdown_requested = True
        if self._loop is not None and self._shutdown_event is not None:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)

    def server_close(self):
        pass


def create_server(
    module,
    css="",
    entry_point=None,
    *args,
    render=None,
    routes=None,
    layout=None,
    layout_id="main",
    page_entry_points=(),
    websocket_routes=None,
    host="",
    port=8000,
):
    if websocket_routes:
        return WebSocketPyjsServer(
            module,
            css,
            entry_point,
            *args,
            render=render,
            routes=routes,
            layout=layout,
            layout_id=layout_id,
            page_entry_points=page_entry_points,
            websocket_routes=websocket_routes,
            host=host,
            port=port,
        )
    return PyjsServer(
        module,
        css,
        entry_point,
        *args,
        render=render,
        routes=routes,
        layout=layout,
        layout_id=layout_id,
        page_entry_points=page_entry_points,
        host=host,
        port=port,
    )


def serve(
    module,
    css="",
    entry_point=None,
    *args,
    render=None,
    routes=None,
    layout=None,
    layout_id="main",
    page_entry_points=(),
    websocket_routes=None,
    host="",
    port=8000,
):
    httpd = create_server(
        module,
        css,
        entry_point,
        *args,
        render=render,
        routes=routes,
        layout=layout,
        layout_id=layout_id,
        page_entry_points=page_entry_points,
        websocket_routes=websocket_routes,
        host=host,
        port=port,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        httpd.server_close()
