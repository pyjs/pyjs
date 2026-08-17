import annotationlib
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.db import models
from django.db.models.fields import NOT_PROVIDED
from pydantic import BaseModel, ConfigDict, Field

from pyjs import js

ALL_FIELDS = "__all__"


def _names(
    value,
    option: str,
    *,
    allow_all: bool = False,
) -> tuple[str, ...] | None:
    if value is None or (allow_all and value == ALL_FIELDS):
        return None
    if isinstance(value, str):
        raise TypeError(
            f"ModelSchema.Meta.{option} must be a sequence, not a string."
        )
    return tuple(value)


def _django_field(model: type[models.Model], name: str):
    for field in model._meta.fields:
        if name in (field.name, field.attname):
            return field
    raise TypeError(f"Unknown {model.__name__} field: {name}.")


def _field_name(field) -> str:
    return field.attname


def _python_type(field, *, auto_nullable: bool = True) -> type:
    if isinstance(field, models.AutoField):
        value_type = int
    elif isinstance(field, models.BooleanField):
        value_type = bool
    elif isinstance(field, models.IntegerField):
        value_type = int
    elif isinstance(field, models.FloatField):
        value_type = float
    elif isinstance(field, models.DecimalField):
        value_type = Decimal
    elif isinstance(field, models.DateTimeField):
        value_type = datetime
    elif isinstance(field, models.DateField):
        value_type = date
    elif isinstance(field, (models.CharField, models.TextField)):
        value_type = str
    elif isinstance(field, models.UUIDField):
        value_type = UUID
    elif isinstance(field, models.BinaryField):
        value_type = bytes
    elif isinstance(field, models.JSONField):
        value_type = object
    elif isinstance(field, models.ForeignKey):
        value_type = _python_type(field.target_field, auto_nullable=False)
    else:
        raise TypeError(
            f"Cannot infer a Pydantic type for "
            f"{field.model.__name__}.{field.name} ({type(field).__name__}); "
            "declare the field annotation explicitly."
        )
    if field.null or (auto_nullable and isinstance(field, models.AutoField)):
        return value_type | None
    return value_type


def _default(field):
    if isinstance(field, models.AutoField):
        return None
    if field.default is not NOT_PROVIDED and not callable(field.default):
        return field.default
    if field.null:
        return None
    return NOT_PROVIDED


class ModelSchemaMetaclass(type(BaseModel)):
    def __new__(mcls, name, bases, namespace, /, **kwargs):
        meta = namespace.pop("Meta", None)
        if meta is None:
            return super().__new__(mcls, name, bases, namespace, **kwargs)

        django_model = getattr(meta, "model", None)
        if not isinstance(django_model, type) or not issubclass(
            django_model, models.Model
        ):
            raise TypeError(f"{name}.Meta.model must be a Django model.")

        annotate = namespace.pop("__annotate_func__", None)
        declared = dict(namespace.get("__annotations__", {}))
        if annotate is not None:
            declared.update(
                annotationlib.call_annotate_function(
                    annotate,
                    annotationlib.Format.FORWARDREF,
                )
            )
        fields_option = getattr(meta, "fields", None)
        exclude = _names(getattr(meta, "exclude", None), "exclude") or ()
        if fields_option is None and not exclude:
            raise TypeError(f"{name}.Meta must define fields or exclude.")
        for field_name in exclude:
            if field_name not in declared:
                _django_field(django_model, field_name)
        fields = _names(fields_option, "fields", allow_all=True)
        if fields is None:
            selected = [_field_name(field) for field in django_model._meta.fields]
        else:
            selected = list(fields)
        pk_name = _field_name(django_model._meta.pk)
        if pk_name not in selected and pk_name not in exclude:
            selected.insert(0, pk_name)
        selected.extend(name for name in declared if name not in selected)

        conflicting = set(declared) & set(exclude)
        if conflicting:
            names = ", ".join(sorted(conflicting))
            raise TypeError(
                f"{name} explicitly declares excluded field(s): {names}."
            )

        annotations = {}
        for field_name in selected:
            if field_name in exclude:
                continue
            if field_name in declared:
                annotations[field_name] = declared[field_name]
                continue
            field = _django_field(django_model, field_name)
            generated_name = _field_name(field)
            if field.name in exclude or generated_name in exclude:
                continue
            annotations[generated_name] = _python_type(field)
            default = _default(field)
            field_options = {"title": str(field.verbose_name)}
            if (
                isinstance(field, (models.CharField, models.TextField))
                and field.max_length is not None
            ):
                field_options["max_length"] = field.max_length
            if field_options:
                namespace[generated_name] = Field(
                    ... if default is NOT_PROVIDED else default,
                    **field_options,
                )
            elif default is not NOT_PROVIDED:
                namespace[generated_name] = default
        namespace["__annotations__"] = annotations
        model_config = dict(namespace.get("model_config", {}))
        model_config["from_attributes"] = True
        namespace["model_config"] = ConfigDict(**model_config)

        cls = super().__new__(mcls, name, bases, namespace, **kwargs)
        meta.__js__ = False
        type.__setattr__(cls, "Meta", meta)
        cls.__pyjs_django_model__ = django_model
        return cls


@js
class ModelSchema(BaseModel, metaclass=ModelSchemaMetaclass):
    pass
