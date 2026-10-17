from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from django.db.models import Model, QuerySet

type RelationshipValues = Mapping[object, Model | Sequence[Model] | None]
type RelationshipLoad = Callable[[Sequence[Model]], RelationshipValues]
type QuerySetFactory = Callable[[], QuerySet]


@dataclass(frozen=True)
class DjangoRelationship:
    """Django loading strategy for one declared resource relationship."""

    source: str | None
    queryset: QuerySet | QuerySetFactory | None
    load: RelationshipLoad | None
    model: type[Model] | None
    limit: int | None


def relationship(
    *,
    source: str | None = None,
    queryset: QuerySet | QuerySetFactory | None = None,
    load: RelationshipLoad | None = None,
    model: type[Model] | None = None,
    limit: int | None = None,
) -> DjangoRelationship:
    """Configure how Django loads a resource relationship.

    Args:
        source: Direct relation field on the source Django model.
        queryset: Queryset or factory used to load related models.
        load: Custom batch loader for a computed relationship.
        model: Django model returned by a custom loader.
        limit: Maximum related values included for each source object.

    Returns:
        Relationship metadata consumed by JSON:API encoding.
    """
    if queryset is not None and load is not None:
        raise TypeError("A Django relationship cannot use both queryset and load.")
    if load is None and model is not None:
        raise TypeError("model is only used with a computed Django relationship.")
    if source is not None and (not source or "__" in source):
        raise ValueError("A Django relationship source must be one field name.")
    if limit is not None and limit < 1:
        raise ValueError("A Django relationship limit must be at least one.")
    return DjangoRelationship(source, queryset, load, model, limit)
