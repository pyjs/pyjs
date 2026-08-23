import annotationlib
import inspect
import json
import types
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, Union, cast, get_args, get_origin, runtime_checkable

from pyjs import js, nojs
from pyjs.javascript import _stringify_unchecked
from pyjs.server import live as _live
from pyjs.server.application import ApplicationPage as ApplicationPage
from pyjs.server.application import ApplicationSection as ApplicationSection
from pyjs.server.atomic import AtomicBatch as AtomicBatch
from pyjs.server.errors import (
    OperationError,
    OperationIssue,
    OperationResultError,
    parse_operation_error,
)
from pyjs.server.errors import operation_error as operation_error
from pyjs.server.jsonapi import (
    DecodedJSONAPIDocument,
    JSONAPIDecoder,
    JSONAPIDocument,
    model_document,
)
from pyjs.server.pagination import (
    CursorPageRequest as CursorPageRequest,
)
from pyjs.server.pagination import OffsetPageRequest as OffsetPageRequest
from pyjs.server.pagination import Page as Page
from pyjs.server.protocol import InvalidationPayload as InvalidationPayload
from pyjs.server.rendering import NavigationPage as NavigationPage
from pyjs.server.rendering import html as html
from pyjs.server.rendering import navigation_fragment as navigation_fragment
from pyjs.server.rendering import page as page
from pyjs.server.rendering import write as write
from pyjs.server.transport import (
    ClientTransport,
    FetchTransport,
)
from pyjs.server.transport import (
    TransportResponse as TransportResponse,
)
from pyjs.server.watch import LiveSession as LiveSession
from pyjs.server.watch import WatchedQuery as WatchedQuery

Invalidation = _live.Invalidation
InvalidationBackend = _live.InvalidationBackend
InvalidationHub = _live.InvalidationHub
InvalidationSubscription = _live.InvalidationSubscription
ReplayInvalidationBackend = _live.ReplayInvalidationBackend
api_topic = _live.api_topic
resource_topic = _live.resource_topic

class Operation:
    def __init__(self, kind: str, function):
        self.kind = kind
        self.function = function
        self.name = function.__name__
        self.signature = inspect.signature(function)
        self.jsonapi = False
        self.jsonapi_many = False
        self.client_model_references = {}


@runtime_checkable
class DeferredOperationResult(Protocol):
    def materialize_operation_result(
        self,
        result_type: object,
    ) -> object | Awaitable[object]: ...


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


def _client_result_source(analyzed_function, value: str, receiver: str) -> str:
    from pyjs.transpiler.objects import (
        client_result_requires_decoding,
        client_type_descriptor,
    )

    if not client_result_requires_decoding(analyzed_function.return_type):
        return value
    descriptor = json.dumps(
        client_type_descriptor(analyzed_function.return_type),
        separators=(",", ":"),
    )
    return f"{receiver}._decode_result({value}, {descriptor})"


def _client_operation_source(operation: Operation, analyzed_function) -> str:
    function = operation.function
    arguments = _operation_argument_names(operation)
    payload = ", ".join(f"{name}: {name}" for name in arguments)
    request = (
        f"await this._request('{function.__name__}', "
        f"{{{payload}}})"
    )
    if operation.jsonapi:
        return "\n".join(
            (
                f"const $document = new $JSONAPIDecoder(JSON.parse({request}), "
                f"{_client_model_map_source(operation)});",
                "return $document.data;",
            )
        )
    return "\n".join(
        (
            f"const $value = JSON.parse({request});",
            f"return {_client_result_source(analyzed_function, '$value', 'this')};",
        )
    )


def _client_operation_binding_source(
    operation: Operation,
    source: str,
    receiver: str,
    analyzed_function,
) -> str:
    arguments = _operation_argument_names(operation)
    if operation.jsonapi:
        decode = (
            f"($value) => {receiver}._decode_jsonapi("
            f"$value, {_client_model_map_source(operation)})"
        )
    else:
        decode = (
            "($value) => "
            + _client_result_source(analyzed_function, "$value", receiver)
        )
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
        function.source(
            lambda analyzed: _client_operation_source(remote_operation, analyzed)
        )
        function.__js_bind_source__ = (
            lambda source, receiver, analyzed: _client_operation_binding_source(
                remote_operation,
                source,
                receiver,
                analyzed,
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


async def _dispatch_resource_operation(
    resource: object,
    operation: Operation,
    identity: str,
    values: dict[str, object],
    request: object,
    *,
    serialize: bool = True,
    defer_result: bool = False,
) -> object:
    from pydantic import TypeAdapter, ValidationError

    resource.request = request
    parameters = list(operation.signature.parameters.values())[1:]
    expected = {parameter.name for parameter in parameters}
    unexpected = set(values) - expected
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise operation_error(
            f"Unexpected argument(s): {names}.",
            status=400,
            title="Invalid request",
            code="unexpected_arguments",
        )

    arguments = {}
    for parameter in parameters:
        if parameter.name not in values:
            if parameter.default is not inspect.Parameter.empty:
                continue
            raise operation_error(
                f"Missing argument: {parameter.name}.",
                parameter.name,
                status=400,
                title="Invalid request",
                code="missing_argument",
            )
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
    return_type = operation.signature.return_annotation
    try:
        if isinstance(result, DeferredOperationResult):
            if defer_result:
                return result
            result = result.materialize_operation_result(return_type)
            if inspect.isawaitable(result):
                result = await result
        result_adapter = TypeAdapter(return_type)
        result = result_adapter.validate_python(result)
    except ValidationError as error:
        raise OperationResultError(
            f"Operation {identity!r} returned a value that does not match "
            "its annotation."
        ) from error
    if not serialize:
        return result
    return result_adapter.dump_python(result, mode="json")


async def dispatch_operation(
    root: type | object,
    identity: str,
    values: object,
    request: object = None,
    *,
    serialize: bool = True,
    defer_result: bool = False,
) -> object:
    if not isinstance(values, dict):
        raise operation_error(
            "Operation arguments must be a JSON object.",
            status=400,
            title="Invalid request",
            code="invalid_arguments",
        )
    graph = resource_graph(root)
    operation_metadata = graph.operations_by_identity.get(identity)
    if operation_metadata is None:
        raise operation_error(
            f"Unknown operation: {identity}.",
            status=400,
            title="Invalid request",
            code="unknown_operation",
        )

    root_type = root if isinstance(root, type) else type(root)
    resource = root_type()
    for name in operation_metadata.owner.path:
        resource = getattr(resource, name)
    return await _dispatch_resource_operation(
        resource,
        operation_metadata.operation,
        identity,
        values,
        request,
        serialize=serialize,
        defer_result=defer_result,
    )


async def _dispatch_bound_operation(
    remote_operation: object,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    request: object,
) -> object:
    function = getattr(remote_operation, "__func__", None)
    operation = getattr(function, "__pyjs_operation__", None)
    resource = getattr(remote_operation, "__self__", None)
    if operation is None and resource is not None and function is not None:
        operation = getattr(type(resource), "__pyjs_operations__", {}).get(
            function.__name__
        )
    if not isinstance(operation, Operation) or resource is None:
        raise TypeError("dispatch() requires a bound resource operation")
    try:
        bound = operation.signature.bind(resource, *args, **kwargs)
    except TypeError as error:
        raise TypeError(f"Cannot dispatch {operation.name}(): {error}") from error
    values = {
        name: value
        for name, value in bound.arguments.items()
        if name != "self"
    }
    return await _dispatch_resource_operation(
        resource,
        operation,
        f"{type(resource).__name__}.{operation.name}",
        values,
        request,
        serialize=False,
    )


async def dispatch[**Arguments, Result](
    remote_operation: Callable[Arguments, Awaitable[Result]],
    *args: Arguments.args,
    **kwargs: Arguments.kwargs,
) -> Result:
    return cast(
        Result,
        await _dispatch_bound_operation(remote_operation, args, kwargs, None),
    )


async def dispatch_for_request[**Arguments, Result](
    request: object,
    remote_operation: Callable[Arguments, Awaitable[Result]],
    *args: Arguments.args,
    **kwargs: Arguments.kwargs,
) -> Result:
    return cast(
        Result,
        await _dispatch_bound_operation(remote_operation, args, kwargs, request),
    )


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
        # API subclasses are server-only unless their own declaration is
        # explicitly marked @js. Do not inherit the client marker from API or
        # a client-visible contract base.
        namespace.setdefault("__js__", False)
        children = {}
        operations = {}
        relationships = {}
        relationship_resources = {}
        relationship_loaders = {}
        for base in bases:
            children.update(getattr(base, "__pyjs_api_children__", {}))
            operations.update(getattr(base, "__pyjs_operations__", {}))
            relationships.update(getattr(base, "__pyjs_relationships__", {}))
            relationship_resources.update(
                getattr(base, "__pyjs_relationship_resources__", {})
            )
            relationship_loaders.update(
                getattr(base, "__pyjs_relationship_loaders__", {})
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
                if attribute in namespace:
                    loader = namespace[attribute]
                    if loader is None:
                        relationship_loaders.pop(attribute, None)
                    else:
                        relationship_loaders[attribute] = loader
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
                else:
                    namespace.pop(attribute, None)
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
            elif attribute in operations:
                inherited = operations[attribute]
                if not inspect.iscoroutinefunction(value):
                    raise TypeError(
                        f"Operation override {name}.{attribute} must be async."
                    )
                if inspect.signature(value) != inherited.signature:
                    raise TypeError(
                        f"Operation override {name}.{attribute} must preserve "
                        "its inherited signature."
                    )

        namespace["__pyjs_api_children__"] = children
        namespace["__pyjs_instance_annotations__"] = children
        namespace["__pyjs_operations__"] = operations
        namespace["__pyjs_relationships__"] = relationships
        namespace["__pyjs_relationship_resources__"] = relationship_resources
        namespace["__pyjs_relationship_loaders__"] = relationship_loaders
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
    __pyjs_generated_methods__ = ("_decode_jsonapi", "_request")

    @nojs
    @classmethod
    def __pyjs_prepare_client__(cls):
        resource_graph(cls)

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

    @js
    def related(
        self,
        model: object,
        relationship: API,
    ) -> object | None:
        document = model_document(model)
        if not isinstance(document, DecodedJSONAPIDocument):
            return None
        relationship_name = relationship._path.split("/")[-1]
        return document.related_model(
            model,
            relationship_name,
        )

    @related.analyze
    def related(call):
        return call.receiver_mapped_annotation_type(
            "__pyjs_relationships__",
            1,
            optional=True,
        )

    async def _request(self, operation_name: str, values: object) -> str:
        response = await self._transport.request(
            self._path + "/" + operation_name,
            _stringify_unchecked(values),
            self._timeout_ms,
        )
        if not response.ok:
            raise parse_operation_error(response.body, response.status)
        return response.body

    def _decode_jsonapi(
        self,
        value: JSONAPIDocument,
        model_types: dict[str, type],
    ) -> object:
        document = JSONAPIDecoder(value, model_types)
        return document.data

    @js
    def _decode_result(self, value: object, descriptor: object) -> object:
        return value

    def live_session(self, autostart: bool = True) -> LiveSession:
        return LiveSession(
            self._path,
            transport=self._transport,
            autostart=autostart,
        )

    def atomic(self) -> AtomicBatch:
        return AtomicBatch(self)

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


API._decode_result.source(
    """
    if (Array.isArray(descriptor)) {
        const [kind, ...members] = descriptor;
        if (kind === 'model') {
            const model = globalThis.$pyjsModels?.get(members[0]);
            if (model === undefined) {
                throw new TypeError(`Client model ${members[0]} is unavailable`);
            }
            return value instanceof model ? value : new model(value);
        }
        if (kind === 'union') {
            if (!members.includes('NoneType')) return value;
            if (value === null || value === undefined) return null;
            const member = members.find((candidate) => candidate !== 'NoneType');
            return this._decode_result(value, member);
        }
        if (kind === 'list') {
            return value.map((item) => this._decode_result(item, members[0]));
        }
        if (kind === 'tuple') {
            return value.map((item, index) =>
                this._decode_result(item, members[index])
            );
        }
        if (kind === 'set') {
            const items = value instanceof Set ? [...value] : value;
            return new Set(items.map((item) =>
                this._decode_result(item, members[0])
            ));
        }
        if (kind === 'dict') {
            const entries = value instanceof Map
                ? [...value.entries()]
                : Object.entries(value);
            return new Map(entries.map(([key, item]) => [
                this._decode_result(key, members[0]),
                this._decode_result(item, members[1]),
            ]));
        }
        return value;
    }
    if (descriptor === 'Date') {
        if (value instanceof Date) return value;
        const source = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value)
            ? `${value}T00:00:00`
            : value;
        return new Date(source);
    }
    if ((descriptor === 'int' || descriptor === 'float')
            && typeof value === 'string') {
        return Number(value);
    }
    if (descriptor === 'bool' && typeof value === 'string') {
        return value === 'true';
    }
    return value;
    """
)


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
