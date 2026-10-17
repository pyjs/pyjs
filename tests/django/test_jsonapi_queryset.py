import asyncio

import pytest
from asgiref.sync import async_to_sync
from django.db import connection
from django.db.models import Prefetch, Value
from django.test.utils import CaptureQueriesContext
from pydantic import BaseModel

from pyjs.server import (
    API,
    CursorPageRequest,
    OperationResultError,
    Page,
    Relationship,
    Resource,
    dispatch,
    dispatch_operation,
    query,
)
from pyjs.server.django import (
    ModelSchema,
    QuerySetResult,
    encode_jsonapi_queryset,
    queryset_page,
    queryset_result,
    relationship,
)
from pyjs.server.django.queryset import encode_queryset_page
from pyjs.server.jsonapi import decode_jsonapi_document
from tests.django.models import (
    AuthorRecord,
    BookRecord,
    PublisherRecord,
    TagRecord,
)


class Author(BaseModel):
    id: int
    name: str


class AuthorDisplay(BaseModel):
    id: int
    display_name: str


class Publisher(BaseModel):
    id: int
    name: str


class Book(BaseModel):
    id: int
    title: str


class DjangoBook(ModelSchema):
    id: int

    class Meta:
        model = BookRecord
        fields = ("title",)


class Tag(BaseModel):
    id: int
    name: str


class PublisherResource(Resource[Publisher]):
    pass


class TagResource(Resource[Tag]):
    pass


class BookResource(Resource[Book]):
    publisher: Relationship[Publisher | None, PublisherResource]
    tags: Relationship[list[Tag], TagResource]


class AuthorResource(Resource[Author]):
    books: Relationship[list[Book], BookResource]

    @query
    async def list(self) -> list[Author]:
        return queryset_result(AuthorRecord.objects.order_by("id"))


class AuthorDisplayResource(Resource[AuthorDisplay]):
    pass


class LibraryAPI(API):
    authors: AuthorResource


class DisplayAPI(API):
    authors: AuthorDisplayResource


class OptionalAuthorResource(Resource[Author]):
    @query
    async def get(self, author_id: int) -> Author | None:
        return queryset_result(AuthorRecord.objects.filter(id=author_id))

    @query
    async def ambiguous(self) -> Author:
        return queryset_result(AuthorRecord.objects.order_by("id"))


class OptionalAuthorAPI(API):
    authors: OptionalAuthorResource


class AuthorPageResource(Resource[Author]):
    @query
    async def list(self, page: CursorPageRequest) -> Page[Author]:
        return queryset_page(
            AuthorRecord.objects.order_by("id"),
            page,
            order_by=("id",),
        )


class AuthorPageAPI(API):
    authors: AuthorPageResource


class RecentBookResource(Resource[Book]):
    pass


class FeaturedBookResource(Resource[DjangoBook]):
    pass


def featured_books(authors):
    author_ids = [author.pk for author in authors]
    books = BookRecord.objects.filter(author_id__in=author_ids).order_by(
        "author_id",
        "title",
    )
    values = {}
    for book in books:
        values.setdefault(book.author_id, []).append(book)
    return values


class CuratedAuthorResource(Resource[Author]):
    recent_books: Relationship[list[Book], RecentBookResource] = relationship(
        source="books",
        queryset=BookRecord.objects.order_by("-title"),
        limit=1,
    )
    featured_books: Relationship[
        list[DjangoBook], FeaturedBookResource
    ] = relationship(
        load=featured_books,
        limit=1,
    )

    @query
    async def list(self) -> list[Author]:
        return queryset_result(
            AuthorRecord.objects.order_by("id"),
            include_paths=("recent_books", "featured_books"),
        )


class CuratedLibraryAPI(API):
    authors: CuratedAuthorResource


@pytest.fixture(scope="module", autouse=True)
def database_tables():
    with connection.schema_editor() as editor:
        editor.create_model(AuthorRecord)
        editor.create_model(PublisherRecord)
        editor.create_model(TagRecord)
        editor.create_model(BookRecord)
    yield
    with connection.schema_editor() as editor:
        editor.delete_model(BookRecord)
        editor.delete_model(PublisherRecord)
        editor.delete_model(TagRecord)
        editor.delete_model(AuthorRecord)


@pytest.fixture(autouse=True)
def library():
    BookRecord.objects.all().delete()
    AuthorRecord.objects.all().delete()
    PublisherRecord.objects.all().delete()
    TagRecord.objects.all().delete()
    publisher = PublisherRecord.objects.create(id=1, name="Hopper Press")
    compiler = TagRecord.objects.create(id=1, name="compiler")
    history = TagRecord.objects.create(id=2, name="history")
    ada = AuthorRecord.objects.create(id=1, name="Ada")
    grace = AuthorRecord.objects.create(id=2, name="Grace")
    first = BookRecord.objects.create(
        id=1,
        author=ada,
        publisher=publisher,
        title="Compilers",
    )
    first.tags.add(compiler, history)
    BookRecord.objects.create(
        id=2,
        author=ada,
        publisher=publisher,
        title="Machines",
    )
    BookRecord.objects.create(
        id=3,
        author=grace,
        publisher=None,
        title="Systems",
    )


def test_queryset_encoder_projects_nested_relationships_in_three_queries():
    with CaptureQueriesContext(connection) as queries:
        document = encode_jsonapi_queryset(
            LibraryAPI,
            AuthorResource,
            AuthorRecord.objects.order_by("id"),
            ["books.publisher"],
        )

    assert len(queries) == 3
    assert document == {
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
            },
            {
                "type": "authors",
                "id": "2",
                "attributes": {"name": "Grace"},
                "relationships": {
                    "books": {
                        "data": [{"type": "books", "id": "3"}]
                    }
                },
            },
        ],
        "included": [
            {
                "type": "books",
                "id": "1",
                "attributes": {"title": "Compilers"},
                "relationships": {
                    "publisher": {
                        "data": {"type": "publisher", "id": "1"}
                    }
                },
            },
            {
                "type": "books",
                "id": "2",
                "attributes": {"title": "Machines"},
                "relationships": {
                    "publisher": {
                        "data": {"type": "publisher", "id": "1"}
                    }
                },
            },
            {
                "type": "books",
                "id": "3",
                "attributes": {"title": "Systems"},
                "relationships": {"publisher": {"data": None}},
            },
            {
                "type": "publisher",
                "id": "1",
                "attributes": {"name": "Hopper Press"},
            },
        ],
    }


    decoded = decode_jsonapi_document(
        document,
        {
            "authors": Author,
            "books": Book,
            "publisher": Publisher,
        },
    )
    assert decoded.data == [
        Author(id=1, name="Ada"),
        Author(id=2, name="Grace"),
    ]
    assert decoded.related("authors", "1", "books") == [
        Book(id=1, title="Compilers"),
        Book(id=2, title="Machines"),
    ]
    assert decoded.related("books", "1", "publisher") == Publisher(
        id=1,
        name="Hopper Press",
    )


def test_queryset_encoder_uses_bounded_and_computed_relationship_loaders():
    with CaptureQueriesContext(connection) as queries:
        document = encode_jsonapi_queryset(
            CuratedLibraryAPI,
            CuratedAuthorResource,
            AuthorRecord.objects.order_by("id"),
            ["recent_books", "featured_books"],
        )

    assert len(queries) == 3
    assert document == {
        "data": [
            {
                "type": "authors",
                "id": "1",
                "attributes": {"name": "Ada"},
                "relationships": {
                    "recent_books": {
                        "data": [{"type": "recent_books", "id": "2"}]
                    },
                    "featured_books": {
                        "data": [{"type": "featured_books", "id": "1"}]
                    },
                },
            },
            {
                "type": "authors",
                "id": "2",
                "attributes": {"name": "Grace"},
                "relationships": {
                    "recent_books": {
                        "data": [{"type": "recent_books", "id": "3"}]
                    },
                    "featured_books": {
                        "data": [{"type": "featured_books", "id": "3"}]
                    },
                },
            },
        ],
        "included": [
            {
                "type": "recent_books",
                "id": "2",
                "attributes": {"title": "Machines"},
            },
            {
                "type": "recent_books",
                "id": "3",
                "attributes": {"title": "Systems"},
            },
            {
                "type": "featured_books",
                "id": "1",
                "attributes": {"title": "Compilers"},
            },
            {
                "type": "featured_books",
                "id": "3",
                "attributes": {"title": "Systems"},
            },
        ],
    }


def test_relationship_loader_declarations_are_not_client_class_members():
    recent = CuratedAuthorResource.__pyjs_relationship_loaders__["recent_books"]
    featured = CuratedAuthorResource.__pyjs_relationship_loaders__["featured_books"]

    assert recent.source == "books"
    assert recent.limit == 1
    assert featured.load is featured_books
    assert featured.model is None
    assert CuratedAuthorResource.recent_books.child_type is RecentBookResource
    assert CuratedAuthorResource.featured_books.child_type is FeaturedBookResource


def test_relationship_loader_rejects_ambiguous_or_invalid_declarations():
    with pytest.raises(
        TypeError,
        match="^A Django relationship cannot use both queryset and load\\.$",
    ):
        relationship(
            queryset=BookRecord.objects.all(),
            load=featured_books,
            model=BookRecord,
        )
    with pytest.raises(
        ValueError,
        match="^A Django relationship limit must be at least one\\.$",
    ):
        relationship(limit=0)
    with pytest.raises(
        ValueError,
        match="^A Django relationship source must be one field name\\.$",
    ):
        relationship(source="books__publisher")


def test_computed_loader_requires_a_model_schema_or_explicit_model():
    class UnmodeledBookResource(Resource[Book]):
        pass

    class UnmodeledAuthorResource(Resource[Author]):
        books: Relationship[
            list[Book], UnmodeledBookResource
        ] = relationship(load=featured_books)

    class UnmodeledAPI(API):
        authors: UnmodeledAuthorResource

    with pytest.raises(
        TypeError,
        match=(
            "^Computed relationship UnmodeledAuthorResource.books must target "
            "a ModelSchema or declare model=\\.$"
        ),
    ):
        encode_jsonapi_queryset(
            UnmodeledAPI,
            UnmodeledAuthorResource,
            AuthorRecord.objects.order_by("id"),
            ["books"],
        )


def test_computed_relationship_loaders_skip_empty_parent_sets():
    with CaptureQueriesContext(connection) as queries:
        document = encode_jsonapi_queryset(
            CuratedLibraryAPI,
            CuratedAuthorResource,
            AuthorRecord.objects.none(),
            ["recent_books", "featured_books"],
        )

    assert len(queries) == 0
    assert document == {"data": []}


def test_queryset_encoder_reads_same_named_django_properties():
    document = encode_jsonapi_queryset(
        DisplayAPI,
        AuthorDisplayResource,
        AuthorRecord.objects.order_by("id"),
    )

    assert document == {
        "data": [
            {
                "type": "authors",
                "id": "1",
                "attributes": {"display_name": "ADA"},
            },
            {
                "type": "authors",
                "id": "2",
                "attributes": {"display_name": "GRACE"},
            },
        ]
    }


def test_queryset_result_preserves_the_lazy_queryset_for_the_adapter():
    queryset = AuthorRecord.objects.order_by("id")

    with CaptureQueriesContext(connection) as queries:
        result = queryset_result(queryset)

    assert len(queries) == 0
    assert isinstance(result, QuerySetResult)
    assert result.queryset is queryset
    assert result.include_paths == ()


def test_dispatch_materializes_a_queryset_result_to_its_annotated_type():
    with CaptureQueriesContext(connection) as queries:
        result = async_to_sync(dispatch)(LibraryAPI().authors.list)

    assert len(queries) == 1
    assert result == [
        Author(id=1, name="Ada"),
        Author(id=2, name="Grace"),
    ]

    assert async_to_sync(dispatch_operation)(
        LibraryAPI,
        "authors.list",
        {},
    ) == [
        {"id": 1, "name": "Ada"},
        {"id": 2, "name": "Grace"},
    ]


def test_transport_dispatch_can_retain_a_deferred_queryset_result():
    result = asyncio.run(
        dispatch_operation(
            LibraryAPI,
            "authors.list",
            {},
            serialize=False,
            defer_result=True,
        )
    )

    assert isinstance(result, QuerySetResult)
    assert result.queryset.model is AuthorRecord
    assert result.queryset.query.order_by == ("id",)


def test_dispatch_materializes_nullable_and_paginated_queryset_results():
    missing = async_to_sync(dispatch_operation)(
        OptionalAuthorAPI,
        "authors.get",
        {"author_id": 99},
        serialize=False,
    )
    page = async_to_sync(dispatch_operation)(
        AuthorPageAPI,
        "authors.list",
        {"page": {"size": 1}},
        serialize=False,
    )

    assert missing is None
    assert page.items == [Author(id=1, name="Ada")]
    assert page.next is not None


def test_invalid_materialized_queryset_result_uses_the_operation_boundary():
    with pytest.raises(
        OperationResultError,
        match=(
            "^Operation 'authors.ambiguous' returned a value that does not "
            "match its annotation\\.$"
        ),
    ):
        async_to_sync(dispatch_operation)(
            OptionalAuthorAPI,
            "authors.ambiguous",
            {},
            serialize=False,
        )


def test_queryset_result_requires_a_django_queryset():
    with pytest.raises(
        TypeError,
        match=r"^queryset_result\(\) requires a Django QuerySet\.$",
    ):
        queryset_result([])


def test_queryset_result_retains_include_paths():
    result = queryset_result(
        AuthorRecord.objects.order_by("id"),
        include_paths=("books.publisher",),
    )
    document = encode_jsonapi_queryset(
        LibraryAPI,
        AuthorResource,
        result.queryset,
        result.include_paths,
    )

    assert document["included"][-1] == {
        "type": "publisher",
        "id": "1",
        "attributes": {"name": "Hopper Press"},
    }


def test_queryset_result_rejects_a_string_include_sequence():
    with pytest.raises(
        TypeError,
        match=r"^include_paths must be a sequence, not a string\.$",
    ):
        queryset_result(
            AuthorRecord.objects.all(),
            include_paths="books",
        )


def test_queryset_page_uses_opaque_bidirectional_keyset_cursors():
    first = encode_queryset_page(
        queryset_page(
            AuthorRecord.objects.all(),
            CursorPageRequest(size=1),
            order_by=("name",),
            include_total=True,
        ),
        Page[Author],
    )

    assert first["items"] == [{"id": 1, "name": "Ada"}]
    assert isinstance(first["next"], str)
    assert first["previous"] is None
    assert first["total"] == 2

    second = encode_queryset_page(
        queryset_page(
            AuthorRecord.objects.all(),
            CursorPageRequest(size=1, after=first["next"]),
            order_by=("name",),
        ),
        Page[Author],
    )

    assert second["items"] == [{"id": 2, "name": "Grace"}]
    assert second["next"] is None
    assert isinstance(second["previous"], str)
    assert second["total"] is None

    previous = encode_queryset_page(
        queryset_page(
            AuthorRecord.objects.all(),
            CursorPageRequest(size=1, before=second["previous"]),
            order_by=("name",),
        ),
        Page[Author],
    )

    assert previous["items"] == [{"id": 1, "name": "Ada"}]
    assert isinstance(previous["next"], str)
    assert previous["previous"] is None


def test_queryset_page_appends_the_primary_key_as_a_stable_tie_breaker():
    AuthorRecord.objects.filter(id=2).update(name="Ada")
    first = encode_queryset_page(
        queryset_page(
            AuthorRecord.objects.all(),
            CursorPageRequest(size=1),
            order_by=("name",),
        ),
        Page[Author],
    )
    second = encode_queryset_page(
        queryset_page(
            AuthorRecord.objects.all(),
            CursorPageRequest(size=1, after=first["next"]),
            order_by=("name",),
        ),
        Page[Author],
    )

    assert first["items"] == [{"id": 1, "name": "Ada"}]
    assert second["items"] == [{"id": 2, "name": "Ada"}]


def test_queryset_page_rejects_tampered_and_foreign_query_cursors():
    first = encode_queryset_page(
        queryset_page(
            AuthorRecord.objects.all(),
            CursorPageRequest(size=1),
        ),
        Page[Author],
    )
    cursor = first["next"]
    assert isinstance(cursor, str)

    with pytest.raises(ValueError, match=r"^Invalid pagination cursor\.$"):
        encode_queryset_page(
            queryset_page(
                AuthorRecord.objects.all(),
                CursorPageRequest(size=1, after=cursor + "x"),
            ),
            Page[Author],
        )

    with pytest.raises(ValueError, match=r"^Invalid pagination cursor\.$"):
        encode_queryset_page(
            queryset_page(
                AuthorRecord.objects.all(),
                CursorPageRequest(size=1, after=""),
            ),
            Page[Author],
        )

    with pytest.raises(
        ValueError,
        match=r"^Pagination cursor does not match this query\.$",
    ):
        encode_queryset_page(
            queryset_page(
                AuthorRecord.objects.filter(name="Grace"),
                CursorPageRequest(size=1, after=cursor),
            ),
            Page[Author],
        )


def test_queryset_page_validates_request_and_operation_shapes():
    with pytest.raises(
        ValueError,
        match=r"^Use either an after or before cursor, not both\.$",
    ):
        encode_queryset_page(
            queryset_page(
                AuthorRecord.objects.all(),
                CursorPageRequest(after="after", before="before"),
            ),
            Page[Author],
        )

    with pytest.raises(
        TypeError,
        match=r"^queryset_page\(\) requires an operation returning Page\[T\]\.$",
    ):
        encode_queryset_page(
            queryset_page(
                AuthorRecord.objects.all(),
                CursorPageRequest(),
            ),
            list[Author],
        )


def test_queryset_encoder_preserves_existing_django_prefetches():
    with CaptureQueriesContext(connection) as queries:
        document = encode_jsonapi_queryset(
            LibraryAPI,
            AuthorResource,
            AuthorRecord.objects.order_by("id").prefetch_related(
                Prefetch(
                    "books",
                    queryset=BookRecord.objects.filter(title="Compilers"),
                )
            ),
            ["books"],
        )

    assert len(queries) == 2
    assert document == {
        "data": [
            {
                "type": "authors",
                "id": "1",
                "attributes": {"name": "Ada"},
                "relationships": {
                    "books": {
                        "data": [{"type": "books", "id": "1"}]
                    }
                },
            },
            {
                "type": "authors",
                "id": "2",
                "attributes": {"name": "Grace"},
                "relationships": {"books": {"data": []}},
            },
        ],
        "included": [
            {
                "type": "books",
                "id": "1",
                "attributes": {"title": "Compilers"},
            }
        ],
    }


def test_queryset_encoder_serializes_calculated_model_properties():
    class CalculatedAuthor(BaseModel):
        id: int
        name: str
        display_name: str

    class CalculatedAuthorResource(Resource[CalculatedAuthor]):
        pass

    class CalculatedAPI(API):
        authors: CalculatedAuthorResource

    document = encode_jsonapi_queryset(
        CalculatedAPI,
        CalculatedAuthorResource,
        AuthorRecord.objects.filter(name="Ada"),
    )

    assert document == {
        "data": [
            {
                "type": "authors",
                "id": "1",
                "attributes": {
                    "name": "Ada",
                    "display_name": "ADA",
                },
            }
        ]
    }


def test_queryset_encoder_preserves_queryset_annotations():
    class RankedAuthor(BaseModel):
        id: int
        name: str
        rank: int

    class RankedAuthorResource(Resource[RankedAuthor]):
        pass

    class RankedAPI(API):
        authors: RankedAuthorResource

    document = encode_jsonapi_queryset(
        RankedAPI,
        RankedAuthorResource,
        AuthorRecord.objects.filter(name="Ada").annotate(rank=Value(7)),
    )

    assert document == {
        "data": [
            {
                "type": "authors",
                "id": "1",
                "attributes": {"name": "Ada", "rank": 7},
            }
        ]
    }


def test_queryset_encoder_supports_to_one_primary_data():
    document = encode_jsonapi_queryset(
        LibraryAPI,
        AuthorResource,
        AuthorRecord.objects.filter(name="Ada"),
        many=False,
    )

    assert document == {
        "data": {
            "type": "authors",
            "id": "1",
            "attributes": {"name": "Ada"},
        }
    }


def test_queryset_encoder_loads_many_to_many_targets_and_flat_linkage():
    with CaptureQueriesContext(connection) as queries:
        document = encode_jsonapi_queryset(
            LibraryAPI,
            AuthorResource,
            AuthorRecord.objects.filter(name="Ada"),
            ["books.tags"],
        )

    assert len(queries) == 3
    assert document == {
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
                    "tags": {
                        "data": [
                            {"type": "tags", "id": "1"},
                            {"type": "tags", "id": "2"},
                        ]
                    }
                },
            },
            {
                "type": "books",
                "id": "2",
                "attributes": {"title": "Machines"},
                "relationships": {"tags": {"data": []}},
            },
            {
                "type": "tags",
                "id": "1",
                "attributes": {"name": "compiler"},
            },
            {
                "type": "tags",
                "id": "2",
                "attributes": {"name": "history"},
            },
        ],
    }


def test_queryset_encoder_encodes_a_missing_primary_resource_as_null():
    document = encode_jsonapi_queryset(
        LibraryAPI,
        AuthorResource,
        AuthorRecord.objects.none(),
        many=False,
    )

    assert document == {"data": None}


def test_queryset_encoder_rejects_multiple_rows_for_to_one_data():
    with pytest.raises(
        ValueError,
        match=r"^A to-one JSON:API query returned multiple rows\.$",
    ):
        encode_jsonapi_queryset(
            LibraryAPI,
            AuthorResource,
            AuthorRecord.objects.all(),
            many=False,
        )


def test_queryset_encoder_reports_fields_that_cannot_be_read():
    class DetailedAuthor(BaseModel):
        id: int
        name: str
        biography: str

    class DetailedAuthorResource(Resource[DetailedAuthor]):
        pass

    class DetailedAPI(API):
        authors: DetailedAuthorResource

    with pytest.raises(
        TypeError,
        match=(
            r"^Cannot read DetailedAuthor\.biography from "
            r"AuthorRecord\.$"
        ),
    ):
        encode_jsonapi_queryset(
            DetailedAPI,
            DetailedAuthorResource,
            AuthorRecord.objects.all(),
        )


def test_queryset_encoder_reports_missing_django_relationships():
    class MissingBookResource(Resource[Book]):
        pass

    class MissingAuthorResource(Resource[Author]):
        publications: Relationship[list[Book], MissingBookResource]

    class MissingAPI(API):
        authors: MissingAuthorResource

    with pytest.raises(
        TypeError,
        match=(
            r"^Cannot resolve Django relationship "
            r"AuthorRecord\.publications\.$"
        ),
    ):
        encode_jsonapi_queryset(
            MissingAPI,
            MissingAuthorResource,
            AuthorRecord.objects.all(),
            ["publications"],
        )


def test_queryset_encoder_reports_relationship_cardinality_mismatches():
    class SingleBookResource(Resource[Book]):
        pass

    class SingleBookAuthorResource(Resource[Author]):
        books: Relationship[Book | None, SingleBookResource]

    class SingleBookAPI(API):
        authors: SingleBookAuthorResource

    with pytest.raises(
        TypeError,
        match=(
            r"^Relationship SingleBookAuthorResource\.books is declared "
            r"to-one, but the Django relationship is to-many\.$"
        ),
    ):
        encode_jsonapi_queryset(
            SingleBookAPI,
            SingleBookAuthorResource,
            AuthorRecord.objects.all(),
            ["books"],
        )
