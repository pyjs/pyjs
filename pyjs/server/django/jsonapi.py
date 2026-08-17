from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist
from pydantic import TypeAdapter

from pyjs.server import resolve_include_paths, resource_graph


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


def _loading_plan(django_model, tree, prefix=(), has_many=False):
    select_paths = set()
    prefetch_paths = set()
    for name, (relationship, child_tree) in tree.items():
        django_field = _relationship_field(django_model, name)
        many = _relationship_is_many(django_field)
        expected = "to-many" if relationship.many else "to-one"
        actual = "to-many" if many else "to-one"
        if relationship.many != many:
            raise TypeError(
                f"Relationship {relationship.owner.resource_type.__name__}."
                f"{relationship.name} is declared {expected}, but the Django "
                f"relationship is {actual}."
            )

        path = (*prefix, name)
        nested_selects, nested_prefetches = _loading_plan(
            django_field.related_model,
            child_tree,
            path,
            has_many or many,
        )
        select_paths.update(nested_selects)
        prefetch_paths.update(nested_prefetches)
        lookup = "__".join(path)
        if has_many or many:
            prefetch_paths.add(lookup)
        else:
            select_paths.add(lookup)
    prefetch_paths.difference_update(select_paths)
    return select_paths, prefetch_paths


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

    def _related_instances(self, instance, relationship):
        if relationship.many:
            return list(getattr(instance, relationship.name).all())
        try:
            related = getattr(instance, relationship.name)
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

    def _load_relationships(self, django_model, entries, tree):
        for name, (relationship, child_tree) in tree.items():
            django_field = _relationship_field(django_model, name)
            related_by_entry = []
            related_instances = []
            for _, instance, _ in entries:
                related = self._related_instances(
                    instance,
                    relationship,
                )
                related_by_entry.append(related)
                related_instances.extend(related)

            related_entries = self.load_instances(
                relationship.target,
                django_field.related_model,
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
        select_paths, prefetch_paths = _loading_plan(
            django_model,
            tree,
        )
        if select_paths:
            queryset = queryset.select_related(*sorted(select_paths))
        if prefetch_paths:
            queryset = queryset.prefetch_related(*sorted(prefetch_paths))
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
    root,
    resource_type,
    queryset,
    include_paths=(),
    *,
    many: bool = True,
) -> dict[str, object]:
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
