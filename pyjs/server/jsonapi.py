import json
from typing import NotRequired, TypedDict

from pydantic import BaseModel

from pyjs import js


class ResourceIdentifier(TypedDict):
    type: str
    id: str


class ResourceObject(TypedDict):
    type: str
    id: str
    attributes: object
    relationships: NotRequired[object]


class RelationshipObject(TypedDict):
    data: object


class JSONAPIDocument(TypedDict):
    data: object
    included: NotRequired[list[ResourceObject]]


@js.inline("JSON.parse({source})")
def parse_jsonapi_document(source: str) -> JSONAPIDocument:
    return json.loads(source)


@js.inline("{value}")
def _resource_object(value: object) -> ResourceObject:
    return value


@js.inline("{value}")
def _resource_identifier(value: object) -> ResourceIdentifier:
    return value


@js.inline("{value}")
def _relationship_object(value: object) -> RelationshipObject:
    return value


@js.inline("Object.entries({value})")
def _object_items(value: object) -> list[tuple[str, object]]:
    return list(value.items())


@js.inline(
    "new {model_type}(Object.assign({{}}, {attributes}, {{id: {identifier}}}))"
)
def _model_value(
    model_type: type,
    attributes: object,
    identifier: str,
) -> BaseModel:
    values = dict(attributes)
    values["id"] = identifier
    return model_type.model_validate(values)


@js
class ResourceLinkage:
    def __init__(
        self,
        many: bool,
        identifiers: list[ResourceIdentifier],
    ):
        self.many = many
        self.identifiers = identifiers


@js
class DecodedJSONAPIDocument:
    def __init__(
        self,
        data: BaseModel | list[BaseModel] | None,
        resources: dict[str, dict[str, BaseModel]],
        relationships: dict[str, dict[str, dict[str, ResourceLinkage]]],
    ):
        self.data = data
        self.resources = resources
        self.relationships = relationships

    def get(self, resource_type: str, identifier: str) -> BaseModel | None:
        resources = self.resources.get(resource_type, None)
        if resources is None:
            return None
        return resources.get(identifier, None)

    def linkage(
        self,
        resource_type: str,
        identifier: str,
        relationship: str,
    ) -> ResourceLinkage | None:
        resources = self.relationships.get(resource_type, None)
        if resources is None:
            return None
        relationships = resources.get(identifier, None)
        if relationships is None:
            return None
        return relationships.get(relationship, None)

    def related(
        self,
        resource_type: str,
        identifier: str,
        relationship: str,
    ) -> BaseModel | list[BaseModel] | None:
        linkage = self.linkage(resource_type, identifier, relationship)
        if linkage is None:
            return None
        values: list[BaseModel] = []
        for target in linkage.identifiers:
            value = self.get(target["type"], target["id"])
            if value is None:
                return None
            values.append(value)
        if linkage.many:
            return values
        if not values:
            return None
        return values[0]


@js
def _identifiers(value: object) -> ResourceLinkage:
    if value is None:
        return ResourceLinkage(False, [])
    if isinstance(value, list):
        identifiers: list[ResourceIdentifier] = []
        for item in value:
            identifiers.append(_resource_identifier(item))
        return ResourceLinkage(True, identifiers)
    return ResourceLinkage(False, [_resource_identifier(value)])


@js
class JSONAPIDecoder(DecodedJSONAPIDocument):
    def __init__(
        self,
        document: JSONAPIDocument,
        model_types: dict[str, type],
    ):
        primary_value = document["data"]
        primary: list[ResourceObject] = []
        if isinstance(primary_value, list):
            for item in primary_value:
                primary.append(_resource_object(item))
        elif primary_value is not None:
            primary.append(_resource_object(primary_value))

        resources: dict[str, dict[str, BaseModel]] = {}
        relationships: dict[str, dict[str, dict[str, ResourceLinkage]]] = {}
        all_resources: list[ResourceObject] = []
        all_resources.extend(primary)
        included = document.get("included", None)
        if included is not None:
            all_resources.extend(included)
        for resource in all_resources:
            resource_type = resource["type"]
            identifier = resource["id"]
            values_by_id = resources.get(resource_type, None)
            if values_by_id is None:
                values_by_id = {}
                resources[resource_type] = values_by_id
            if identifier not in values_by_id:
                model_type = model_types.get(resource_type, None)
                if model_type is None:
                    raise TypeError(
                        f"No model is registered for JSON:API resource type "
                        f"{resource_type}."
                    )
                values_by_id[identifier] = _model_value(
                    model_type,
                    resource["attributes"],
                    identifier,
                )

            raw_relationships = resource.get("relationships", None)
            if raw_relationships is None:
                continue
            relationships_by_id = relationships.get(resource_type, None)
            if relationships_by_id is None:
                relationships_by_id = {}
                relationships[resource_type] = relationships_by_id
            resource_relationships = relationships_by_id.get(identifier, None)
            if resource_relationships is None:
                resource_relationships = {}
                relationships_by_id[identifier] = resource_relationships
            for name, relationship_value in _object_items(raw_relationships):
                relationship = _relationship_object(relationship_value)
                resource_relationships[name] = _identifiers(
                    relationship["data"]
                )

        primary_models: list[BaseModel] = []
        for resource in primary:
            value = resources[resource["type"]][resource["id"]]
            primary_models.append(value)
        data: BaseModel | list[BaseModel] | None = None
        if isinstance(primary_value, list):
            data = primary_models
        elif primary_value is not None:
            data = primary_models[0]
        super().__init__(data, resources, relationships)


@js
def decode_jsonapi_document(
    document: JSONAPIDocument,
    model_types: dict[str, type],
) -> DecodedJSONAPIDocument:
    return JSONAPIDecoder(document, model_types)


def encode_jsonapi_values(
    root,
    resource_type,
    values,
    *,
    many: bool,
) -> dict[str, object]:
    from pyjs.server import resource_graph

    graph = resource_graph(root)
    metadata = graph.resources_by_type.get(resource_type)
    if metadata is None:
        raise TypeError(
            f"{resource_type.__name__} is not mounted in "
            f"{graph.root_type.__name__}."
        )
    relationship_names = {
        relationship.name
        for relationship in graph.relationships
        if relationship.owner is metadata
    }

    def encode(value):
        model = metadata.model_type.model_validate(value)
        attributes = model.model_dump(mode="json")
        identifier = attributes.pop("id", None)
        if identifier is None:
            raise TypeError(
                f"{metadata.model_type.__name__} must provide an id for "
                "JSON:API encoding."
            )
        for name in relationship_names:
            attributes.pop(name, None)
        return {
            "type": metadata.path[-1],
            "id": str(identifier),
            "attributes": attributes,
        }

    if many:
        data = [encode(value) for value in values]
    else:
        data = None if values is None else encode(values)
    return {"data": data}
