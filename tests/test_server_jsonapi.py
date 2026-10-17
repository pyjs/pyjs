import pytest
from pydantic import BaseModel, ValidationError

from pyjs import js
from pyjs.server import (
    API,
    ClientTransport,
    Relationship,
    Resource,
    model_identity,
    query,
    resource_identity,
)
from pyjs.server.jsonapi import (
    JSONAPIDocument,
    decode_jsonapi_document,
    encode_jsonapi_values,
    parse_jsonapi_document,
)


@js
class Author(BaseModel):
    id: int
    name: str


@js
class Book(BaseModel):
    id: int
    title: str


@js
class Publisher(BaseModel):
    id: int
    name: str


MODEL_TYPES = {
    "authors": Author,
    "books": Book,
    "publishers": Publisher,
}


class RelatedBookResource(Resource[Book]):
    pass


class RelatedAuthorResource(Resource[Author]):
    books: Relationship[list[Book], RelatedBookResource]


class RelatedAPI(API):
    authors: RelatedAuthorResource


class EncodedBook(BaseModel):
    id: int | None = None
    title: str


class EncodedBookResource(Resource[EncodedBook]):
    @query
    async def list(self) -> list[EncodedBook]:
        return []


class EncodingAPI(API):
    books: EncodedBookResource


def test_encoder_uses_resource_metadata_for_one_many_and_null_values():
    assert encode_jsonapi_values(
        EncodingAPI,
        EncodedBookResource,
        [EncodedBook(id=1, title="Compilers")],
        many=True,
    ) == {
        "data": [
            {
                "type": "books",
                "id": "1",
                "attributes": {"title": "Compilers"},
            }
        ]
    }
    assert encode_jsonapi_values(
        EncodingAPI,
        EncodedBookResource,
        EncodedBook(id=2, title="Machines"),
        many=False,
    ) == {
        "data": {
            "type": "books",
            "id": "2",
            "attributes": {"title": "Machines"},
        }
    }
    assert encode_jsonapi_values(
        EncodingAPI,
        EncodedBookResource,
        None,
        many=False,
    ) == {"data": None}


def test_encoder_requires_a_resource_identifier():
    with pytest.raises(
        TypeError,
        match=r"^EncodedBook must provide an id for JSON:API encoding\.$",
    ):
        encode_jsonapi_values(
            EncodingAPI,
            EncodedBookResource,
            EncodedBook(title="Missing identity"),
            many=False,
        )


def test_resource_identity_is_stable_and_collision_safe():
    authors = RelatedAPI().authors

    assert authors.identity(1) == '["authors","1"]'
    assert authors.identity("1") == '["authors","1"]'
    assert resource_identity("authors", 1) == authors.identity(1)
    assert resource_identity("authors:1", 2) != resource_identity(
        "authors",
        "1:2",
    )


def library_document() -> JSONAPIDocument:
    return {
        "data": [
            {
                "type": "authors",
                "id": "1",
                "attributes": {"name": "Ada"},
                "relationships": {
                    "books": {
                        "data": [
                            {"type": "books", "id": "1"},
                            {"type": "books", "id": "2"},
                        ]
                    }
                },
            }
        ],
        "included": [
            {
                "type": "books",
                "id": "1",
                "attributes": {"title": "Compilers"},
                "relationships": {
                    "publisher": {
                        "data": {"type": "publishers", "id": "1"}
                    }
                },
            },
            {
                "type": "books",
                "id": "2",
                "attributes": {"title": "Machines"},
                "relationships": {"publisher": {"data": None}},
            },
            {
                "type": "publishers",
                "id": "1",
                "attributes": {"name": "Hopper Press"},
            },
            {
                "type": "books",
                "id": "1",
                "attributes": {"title": "Ignored duplicate"},
            },
        ],
    }


def test_resource_resolves_values_from_the_model_document():
    resource = RelatedAPI().authors
    detached = Author(id=1, name="Ada")

    assert resource.related(detached, resource.books) is None

    decoded = decode_jsonapi_document(library_document(), MODEL_TYPES)
    author = decoded.data[0]

    assert resource.related(author, resource.books) == [
        Book(id=1, title="Compilers"),
        Book(id=2, title="Machines"),
    ]


def test_models_keep_relationship_context_across_later_queries():
    resource = RelatedAPI().authors
    first = decode_jsonapi_document(library_document(), MODEL_TYPES)
    second_source = library_document()
    second_source["included"][0]["attributes"] = {"title": "New edition"}
    second = decode_jsonapi_document(second_source, MODEL_TYPES)

    assert resource.related(first.data[0], resource.books) == [
        Book(id=1, title="Compilers"),
        Book(id=2, title="Machines"),
    ]
    assert resource.related(second.data[0], resource.books) == [
        Book(id=1, title="New edition"),
        Book(id=2, title="Machines"),
    ]
    assert model_identity(first.data[0]) == model_identity(second.data[0])
    assert model_identity(first.data[0]) == '["authors","1"]'


def test_identity_is_only_attached_to_materialized_resource_models():
    assert model_identity(Author(id=1, name="Ada")) is None

    decoded = decode_jsonapi_document(library_document(), MODEL_TYPES)

    assert model_identity(decoded.get("authors", "1")) == '["authors","1"]'
    assert model_identity(decoded.get("books", "1")) == '["books","1"]'


def test_api_children_inherit_transport_and_timeout():
    transport = ClientTransport()
    api = RelatedAPI(transport=transport, timeout_ms=2500)

    assert api.authors._transport is transport
    assert api.authors._timeout_ms == 2500
    assert api.authors.books._transport is transport
    assert api.authors.books._timeout_ms == 2500


def test_decoder_builds_typed_values_and_deduplicated_identity_map():
    decoded = decode_jsonapi_document(library_document(), MODEL_TYPES)

    assert decoded.data == [Author(id=1, name="Ada")]
    assert decoded.resources == {
        "authors": {"1": Author(id=1, name="Ada")},
        "books": {
            "1": Book(id=1, title="Compilers"),
            "2": Book(id=2, title="Machines"),
        },
        "publishers": {
            "1": Publisher(id=1, name="Hopper Press"),
        },
    }
    assert decoded.get("books", "1") == Book(id=1, title="Compilers")
    assert decoded.get("missing", "1") is None
    assert decoded.get("books", "99") is None


def test_decoder_retains_to_many_to_one_and_nullable_linkage():
    decoded = decode_jsonapi_document(library_document(), MODEL_TYPES)

    author_books = decoded.linkage("authors", "1", "books")
    assert author_books is not None
    assert author_books.many is True
    assert author_books.identifiers == [
        {"type": "books", "id": "1"},
        {"type": "books", "id": "2"},
    ]
    assert decoded.related("authors", "1", "books") == [
        Book(id=1, title="Compilers"),
        Book(id=2, title="Machines"),
    ]

    publisher = decoded.linkage("books", "1", "publisher")
    assert publisher is not None
    assert publisher.many is False
    assert publisher.identifiers == [{"type": "publishers", "id": "1"}]
    assert decoded.related("books", "1", "publisher") == Publisher(
        id=1,
        name="Hopper Press",
    )

    no_publisher = decoded.linkage("books", "2", "publisher")
    assert no_publisher is not None
    assert no_publisher.many is False
    assert no_publisher.identifiers == []
    assert decoded.related("books", "2", "publisher") is None
    assert decoded.linkage("books", "2", "missing") is None


def test_decoder_distinguishes_empty_and_unmaterialized_to_many_relations():
    document: JSONAPIDocument = {
        "data": [
            {
                "type": "authors",
                "id": "1",
                "attributes": {"name": "Ada"},
                "relationships": {"books": {"data": []}},
            },
            {
                "type": "authors",
                "id": "2",
                "attributes": {"name": "Grace"},
                "relationships": {
                    "books": {
                        "data": [{"type": "books", "id": "99"}]
                    }
                },
            },
        ]
    }

    decoded = decode_jsonapi_document(document, MODEL_TYPES)

    assert decoded.related("authors", "1", "books") == []
    assert decoded.related("authors", "2", "books") is None
    missing = decoded.linkage("authors", "2", "books")
    assert missing is not None
    assert missing.identifiers == [{"type": "books", "id": "99"}]


def test_decoder_preserves_to_one_and_null_primary_shapes():
    one: JSONAPIDocument = {
        "data": {
            "type": "authors",
            "id": "1",
            "attributes": {"name": "Ada"},
        }
    }
    empty: JSONAPIDocument = {"data": None}

    assert decode_jsonapi_document(one, MODEL_TYPES).data == Author(
        id=1,
        name="Ada",
    )
    assert decode_jsonapi_document(empty, MODEL_TYPES).data is None


def test_decoder_reports_unknown_resource_types():
    document: JSONAPIDocument = {
        "data": {
            "type": "unknown",
            "id": "1",
            "attributes": {},
        }
    }

    with pytest.raises(
        TypeError,
        match=(
            r"^No model is registered for JSON:API resource type unknown\.$"
        ),
    ):
        decode_jsonapi_document(document, MODEL_TYPES)


def test_decoder_preserves_pydantic_validation_errors():
    document: JSONAPIDocument = {
        "data": {
            "type": "authors",
            "id": "1",
            "attributes": {},
        }
    }

    with pytest.raises(ValidationError):
        decode_jsonapi_document(document, MODEL_TYPES)


@js
class BrowserTask(BaseModel):
    id: str
    title: str


@js
class BrowserRelatedTaskResource(Resource[BrowserTask]):
    pass


@js
class BrowserTaskResource(Resource[BrowserTask]):
    children: Relationship[list[BrowserTask], BrowserRelatedTaskResource]


@js
class BrowserAPI(API):
    tasks: BrowserTaskResource


@pytest.mark.pyjs_web
@js
def test_decoder_reconstructs_relationships_in_the_browser():
    document = parse_jsonapi_document(
        '{"data":{"type":"tasks","id":"1","attributes":'
        '{"title":"Decode JSON:API"},"relationships":{"children":'
        '{"data":[{"type":"tasks","id":"2"}]}}},"included":['
        '{"type":"tasks","id":"2","attributes":{"title":"Test it"}},'
        '{"type":"tasks","id":"2","attributes":{"title":"Ignored"}}]}'
    )

    decoded = decode_jsonapi_document(
        document,
        {"tasks": BrowserTask},
    )
    task = decoded.data
    assert isinstance(task, BrowserTask)
    assert task.id == "1"
    assert task.title == "Decode JSON:API"
    assert model_identity(task) == '["tasks","1"]'
    assert BrowserAPI().tasks.identity(task.id) == model_identity(task)

    resource = BrowserAPI().tasks
    related = resource.related(task, resource.children)
    if not isinstance(related, list):
        raise ValueError("Expected a to-many relationship")
    assert len(related) == 1
    related_task = related[0]
    assert isinstance(related_task, BrowserTask)
    assert related_task.id == "2"
    assert related_task.title == "Test it"
    assert model_identity(related_task) == '["tasks","2"]'

    newer = decode_jsonapi_document(
        parse_jsonapi_document(
            '{"data":{"type":"tasks","id":"1","attributes":'
            '{"title":"New query"},"relationships":{"children":'
            '{"data":[{"type":"tasks","id":"2"}]}}},"included":['
            '{"type":"tasks","id":"2","attributes":{"title":"New child"}}]}'
        ),
        {"tasks": BrowserTask},
    )
    newer_task = newer.data
    assert isinstance(newer_task, BrowserTask)
    newer_related = resource.related(newer_task, resource.children)
    if not isinstance(newer_related, list):
        raise ValueError("Expected a newer to-many relationship")
    newer_related_task = newer_related[0]
    assert isinstance(newer_related_task, BrowserTask)
    assert newer_related_task.title == "New child"
    earlier_related = resource.related(task, resource.children)
    if not isinstance(earlier_related, list):
        raise ValueError("Expected the earlier to-many relationship")
    assert earlier_related[0] is related_task
