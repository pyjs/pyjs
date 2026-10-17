import pytest

from pyjs import js
from pyjs.server.django import ModelSchema
from tests.django.models import AuthorRecord, BookRecord, ChoiceRecord


@js
class AuthorSchema(ModelSchema):
    display_name: str

    class Meta:
        model = AuthorRecord
        fields = ("name",)


def test_model_schema_generates_fields_and_keeps_explicit_fields_additive():
    assert list(AuthorSchema.model_fields) == ["id", "name", "display_name"]
    assert AuthorSchema.model_fields["id"].annotation == int | None
    assert AuthorSchema.model_fields["id"].default is None
    assert AuthorSchema.model_fields["name"].annotation is str
    assert AuthorSchema.model_fields["name"].title == "name"
    assert AuthorSchema.model_fields["name"].metadata[0].max_length == 100

    author = AuthorSchema.model_validate(AuthorRecord(id=7, name="Ada"))

    assert author == AuthorSchema(id=7, name="Ada", display_name="ADA")

    unsaved = AuthorRecord(name="Grace")
    assert AuthorSchema.model_validate(unsaved).id is None


def test_model_schema_supports_all_fields_with_exclusions():
    class DisplaySchema(ModelSchema):
        display_name: str

        class Meta:
            model = AuthorRecord
            fields = "__all__"
            exclude = ("name",)

    assert list(DisplaySchema.model_fields) == ["id", "display_name"]

    class BookSchema(ModelSchema):
        class Meta:
            model = BookRecord
            fields = "__all__"

    assert list(BookSchema.model_fields) == [
        "id",
        "author_id",
        "publisher_id",
        "title",
    ]
    assert BookSchema.model_fields["author_id"].annotation is int
    assert BookSchema.model_fields["publisher_id"].annotation == int | None


def test_model_schema_uses_the_value_of_a_django_choices_default():
    class ChoiceSchema(ModelSchema):
        class Meta:
            model = ChoiceRecord
            fields = ("state",)

    assert ChoiceSchema.model_fields["state"].default == "draft"


def test_model_schema_rejects_unknown_and_conflicting_fields():
    with pytest.raises(TypeError, match=r"^Unknown AuthorRecord field: missing\.$"):

        class UnknownSchema(ModelSchema):
            class Meta:
                model = AuthorRecord
                fields = ("missing",)

    with pytest.raises(TypeError, match=r"^Unknown AuthorRecord field: missing\.$"):

        class UnknownExcludeSchema(ModelSchema):
            class Meta:
                model = AuthorRecord
                exclude = ("missing",)

    with pytest.raises(
        TypeError,
        match=r"^ConflictingSchema explicitly declares excluded field\(s\): name\.$",
    ):

        class ConflictingSchema(ModelSchema):
            name: str

            class Meta:
                model = AuthorRecord
                fields = "__all__"
                exclude = ("name",)

    with pytest.raises(
        TypeError,
        match=r"^MissingOptionsSchema.Meta must define fields or exclude\.$",
    ):

        class MissingOptionsSchema(ModelSchema):
            class Meta:
                model = AuthorRecord
