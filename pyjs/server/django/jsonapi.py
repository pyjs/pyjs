from collections.abc import Mapping, Sequence

from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist
from django.db.models import Model, Prefetch, QuerySet, prefetch_related_objects
from pydantic import TypeAdapter

from pyjs.server import resolve_include_paths, resource_graph

from .relationship import DjangoRelationship


def _resource_type(metadata) -> str:
    if not metadata.path:
        raise TypeError(
            f"{metadata.resource_type.__name__} must be mounted below an API."
        )
    return metadata.path[-1]


def _include_tree(includes):
    tree = {}
    for include in includes:
        branch = tree
        for relationship in include.relationships:
            child = branch.get(relationship.name)
            if child is None:
                child = (relationship, {})
                branch[relationship.name] = child
            branch = child[1]
    return tree


def _relationship_field(django_model, name):
    try:
        return django_model._meta.get_field(name)
    except FieldDoesNotExist as error:
        raise TypeError(
            f"Cannot resolve Django relationship "
            f"{django_model.__name__}.{name}."
        ) from error


def _relationship_is_many(django_field) -> bool:
    return django_field.one_to_many or django_field.many_to_many


def _relationship_loader(relationship):
    loader = relationship.owner.resource_type.__pyjs_relationship_loaders__.get(
        relationship.name
    )
    if loader is not None and not isinstance(loader, DjangoRelationship):
        raise TypeError(
            f"Relationship {relationship.owner.resource_type.__name__}."
            f"{relationship.name} uses a loader not supported by Django."
        )
    return loader


def _loader_queryset(loader, django_model):
    queryset = loader.queryset
    if callable(queryset) and not isinstance(queryset, QuerySet):
        queryset = queryset()
    if queryset is None:
        queryset = django_model._default_manager.all()
    if not isinstance(queryset, QuerySet):
        raise TypeError("A Django relationship queryset must return a QuerySet.")
    if queryset.model is not django_model:
        raise TypeError(
            f"A Django relationship for {django_model.__name__} cannot use a "
            f"QuerySet for {queryset.model.__name__}."
        )
    return queryset


def _loader_attribute(name: str) -> str:
    return f"_pyjs_relationship_{name}"


def _computed_model(relationship, loader):
    model = loader.model or getattr(
        relationship.target.model_type,
        "__pyjs_django_model__",
        None,
    )
    if model is None:
        raise TypeError(
            f"Computed relationship {relationship.owner.resource_type.__name__}."
            f"{relationship.name} must target a ModelSchema or declare model=."
        )
    return model


def _apply_loading_plan(queryset, django_model, tree):
    selects, prefetches = _loading_plan(django_model, tree)
    if selects:
        queryset = queryset.select_related(*sorted(selects))
    if prefetches:
        queryset = queryset.prefetch_related(*prefetches)
    return queryset


def _loading_plan(django_model, tree, prefix=(), has_many=False):
    select_paths = set()
    prefetch_paths = []
    for name, (relationship, child_tree) in tree.items():
        loader = _relationship_loader(relationship)
        if loader is not None and loader.load is not None:
            continue
        source = name if loader is None or loader.source is None else loader.source
        django_field = _relationship_field(django_model, source)
        many = _relationship_is_many(django_field)
        expected = "to-many" if relationship.many else "to-one"
        actual = "to-many" if many else "to-one"
        if relationship.many != many:
            raise TypeError(
                f"Relationship {relationship.owner.resource_type.__name__}."
                f"{relationship.name} is declared {expected}, but the Django "
                f"relationship is {actual}."
            )

        path = (*prefix, source)
        if loader is not None:
            related_queryset = _loader_queryset(loader, django_field.related_model)
            related_queryset = _apply_loading_plan(
                related_queryset,
                django_field.related_model,
                child_tree,
            )
            if loader.limit is not None:
                related_queryset = related_queryset[: loader.limit]
            prefetch_paths.append(
                Prefetch(
                    "__".join(path),
                    queryset=related_queryset,
                    to_attr=_loader_attribute(name),
                )
            )
            continue
        nested_selects, nested_prefetches = _loading_plan(
            django_field.related_model,
            child_tree,
            path,
            has_many or many,
        )
        select_paths.update(nested_selects)
        prefetch_paths.extend(nested_prefetches)
        lookup = "__".join(path)
        if has_many or many:
            prefetch_paths.append(lookup)
        else:
            select_paths.add(lookup)
    return select_paths, [
        path
        for path in prefetch_paths
        if not isinstance(path, str) or path not in select_paths
    ]


def _prepare_loaded_instances(instances, django_model, tree):
    if not instances or not tree:
        return
    selects, prefetches = _loading_plan(django_model, tree)
    prefetch_related_objects(instances, *sorted(selects), *prefetches)


class _QuerySetEncoder:
    def __init__(self, graph):
        self.graph = graph
        self.objects = {}
        self.object_order = []
        self.primary = set()

    def _attributes(self, metadata, django_model):
        relationship_names = {
            relationship.name
            for relationship in self.graph.relationships
            if relationship.owner is metadata
        }
        adapters = {}
        for name, model_field in metadata.model_type.model_fields.items():
            if name == "id" or name in relationship_names:
                continue
            try:
                django_field = django_model._meta.get_field(name)
            except FieldDoesNotExist:
                django_field = None
            if django_field is not None and django_field.is_relation:
                raise TypeError(
                    f"{metadata.model_type.__name__}.{name} maps to a Django "
                    "relationship; declare it as a Resource relationship."
                )
            adapters[name] = (
                model_field.serialization_alias or name,
                TypeAdapter(model_field.annotation),
            )
        return adapters

    def _object(self, metadata, instance, adapters):
        identifier = str(instance.pk)
        key = (metadata.resource_type, identifier)
        resource = self.objects.get(key)
        if resource is None:
            attributes = {}
            for source, (target, adapter) in adapters.items():
                try:
                    source_value = getattr(instance, source)
                except AttributeError as error:
                    raise TypeError(
                        f"Cannot read {metadata.model_type.__name__}.{source} "
                        f"from {type(instance).__name__}."
                    ) from error
                value = adapter.validate_python(source_value)
                attributes[target] = adapter.dump_python(value, mode="json")
            resource = {
                "type": _resource_type(metadata),
                "id": identifier,
                "attributes": attributes,
            }
            self.objects[key] = resource
            self.object_order.append(key)
        return key, resource

    def _link(self, resource, name, metadata, identifiers, many):
        if many:
            data = [
                {"type": _resource_type(metadata), "id": identifier}
                for identifier in identifiers
            ]
        elif identifiers:
            data = {
                "type": _resource_type(metadata),
                "id": identifiers[0],
            }
        else:
            data = None
        resource.setdefault("relationships", {})[name] = {"data": data}

    def _related_instances(self, instance, relationship, loader):
        name = (
            relationship.name
            if loader is None
            else _loader_attribute(relationship.name)
        )
        if relationship.many:
            related = getattr(instance, name)
            if isinstance(related, list):
                return related
            return list(related.all())
        try:
            related = getattr(instance, name)
        except ObjectDoesNotExist:
            related = None
        if related is None:
            if not relationship.nullable:
                raise TypeError(
                    f"Relationship {relationship.owner.resource_type.__name__}."
                    f"{relationship.name} cannot be None."
                )
            return []
        return [related]

    def _computed_relationships(
        self,
        entries,
        relationship,
        loader,
        related_model,
    ):
        instances = [instance for _, instance, _ in entries]
        if not instances:
            return []
        values = loader.load(instances)
        if not isinstance(values, Mapping):
            raise TypeError(
                f"Computed relationship {relationship.owner.resource_type.__name__}."
                f"{relationship.name} must return a mapping keyed by parent ID."
            )
        related_by_entry = []
        for instance in instances:
            value = values.get(instance.pk)
            if relationship.many:
                if value is None:
                    related = []
                elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    related = list(value)
                else:
                    raise TypeError(
                        f"Computed to-many relationship {relationship.name} must "
                        "return a sequence for each parent."
                    )
                if loader.limit is not None:
                    related = related[: loader.limit]
            else:
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    raise TypeError(
                        f"Computed to-one relationship {relationship.name} must "
                        "return one model or None for each parent."
                    )
                if value is None:
                    if not relationship.nullable:
                        raise TypeError(
                            f"Computed relationship {relationship.name} cannot "
                            "return None."
                        )
                    related = []
                else:
                    related = [value]
            for child in related:
                if not isinstance(child, related_model):
                    raise TypeError(
                        f"Computed relationship {relationship.name} returned "
                        f"{type(child).__name__}; expected {related_model.__name__}."
                    )
            related_by_entry.append(related)
        return related_by_entry

    def _load_relationships(self, django_model, entries, tree):
        for name, (relationship, child_tree) in tree.items():
            loader = _relationship_loader(relationship)
            if loader is not None and loader.load is not None:
                related_model = _computed_model(relationship, loader)
                related_by_entry = self._computed_relationships(
                    entries,
                    relationship,
                    loader,
                    related_model,
                )
            else:
                source = (
                    name if loader is None or loader.source is None else loader.source
                )
                django_field = _relationship_field(django_model, source)
                related_model = django_field.related_model
                related_by_entry = []
                for _, instance, _ in entries:
                    related_by_entry.append(
                        self._related_instances(instance, relationship, loader)
                    )
            related_instances = [
                related
                for values in related_by_entry
                for related in values
            ]
            if loader is not None and loader.load is not None:
                _prepare_loaded_instances(
                    related_instances,
                    related_model,
                    child_tree,
                )

            related_entries = self.load_instances(
                relationship.target,
                related_model,
                related_instances,
                child_tree,
            )
            keys_by_instance = {
                id(instance): key for key, instance, _ in related_entries
            }
            for (_, _, resource), related in zip(
                entries,
                related_by_entry,
                strict=True,
            ):
                self._link(
                    resource,
                    relationship.name,
                    relationship.target,
                    [keys_by_instance[id(instance)][1] for instance in related],
                    relationship.many,
                )

    def load_instances(self, metadata, django_model, instances, tree):
        adapters = self._attributes(metadata, django_model)
        entries = []
        for instance in instances:
            key, resource = self._object(metadata, instance, adapters)
            entries.append((key, instance, resource))
        self._load_relationships(django_model, entries, tree)
        return entries

    def load(
        self,
        metadata,
        queryset,
        tree,
        *,
        primary=False,
    ):
        django_model = queryset.model
        queryset = _apply_loading_plan(queryset, django_model, tree)
        entries = self.load_instances(
            metadata,
            django_model,
            list(queryset),
            tree,
        )
        if primary:
            self.primary.update(key for key, _, _ in entries)
        return entries

    def document(self, metadata, queryset, tree, many):
        entries = self.load(metadata, queryset, tree, primary=True)
        if not many and len(entries) > 1:
            raise ValueError("A to-one JSON:API query returned multiple rows.")
        if many:
            data = [resource for _, _, resource in entries]
        else:
            data = None if not entries else entries[0][2]
        included = [
            self.objects[key]
            for key in self.object_order
            if key not in self.primary
        ]
        document = {"data": data}
        if included:
            document["included"] = included
        return document


def encode_jsonapi_queryset(
    root: type | object,
    resource_type: type,
    queryset: QuerySet | Sequence[Model],
    include_paths: Sequence[str] = (),
    *,
    many: bool = True,
) -> dict[str, object]:
    """Encode Django model instances and relationships as a JSON:API document.

    Args:
        root: Root API class or instance containing the resource graph.
        resource_type: Resource describing the queryset's model.
        queryset: Django queryset or materialized model collection.
        include_paths: Validated relationship paths to include.
        many: Encode primary data as a collection when true.

    Returns:
        A JSON-serializable JSON:API document.
    """
    if isinstance(include_paths, str):
        raise TypeError("include_paths must be a sequence, not a string.")
    graph = resource_graph(root)
    metadata = graph.resources_by_type.get(resource_type)
    if metadata is None:
        raise TypeError(
            f"{resource_type.__name__} is not mounted in "
            f"{graph.root_type.__name__}."
        )
    includes = resolve_include_paths(root, resource_type, list(include_paths))
    encoder = _QuerySetEncoder(graph)
    return encoder.document(
        metadata,
        queryset,
        _include_tree(includes),
        many,
    )
