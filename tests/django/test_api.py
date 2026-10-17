import asyncio
import json
from types import MappingProxyType, SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import RequestFactory
from pydantic import BaseModel

from pyjs import js
from pyjs.decorators import is_js_enabled
from pyjs.server import (
    API,
    OperationError,
    Relationship,
    Resource,
    dispatch,
    dispatch_for_request,
    dispatch_operation,
    include_paths,
    mutation,
    query,
    resolve_include_paths,
    resource_graph,
)
from pyjs.server.django import (
    csrf_failure,
    dispatch_for_request_sync,
    dispatch_sync,
    queryset_result,
)
from tests.django.models import AuthorRecord


class PageRequest(BaseModel):
    page: int = 1
    page_size: int = 25


class Task(BaseModel):
    id: int | None = None
    title: str
    completed: bool = False


class TaskPage(BaseModel):
    items: list[Task]
    page: int
    page_size: int
    total: int


class Project(BaseModel):
    id: int
    name: str


class Comment(BaseModel):
    id: int | None = None
    body: str


class CommentResource(Resource[Comment]):
    @mutation
    async def add(self, comment: Comment) -> Comment:
        return comment.model_copy(update={"id": comment.id or 3})


class ProjectResource(Resource[Project]):
    tasks: Relationship[list[Task]]


class TaskResource(Resource[Task]):
    comments: Relationship[list[Comment], CommentResource]

    @query
    async def list(self, request: PageRequest) -> TaskPage:
        assert self.request.method == "POST"
        return TaskPage(
            items=[Task(id=1, title="Write the proof of concept")],
            page=request.page,
            page_size=request.page_size,
            total=1,
        )

    @mutation
    async def save(self, task: Task) -> Task:
        return task.model_copy(update={"id": task.id or 2})

    async def server_only(self) -> None:
        raise AssertionError("Undecorated methods must not be routed")


class ApplicationAPI(API):
    tasks: TaskResource
    projects: ProjectResource


class JSONTaskResource(Resource[Task]):
    @query
    async def list(self) -> list[Task]:
        return [Task(id=1, title="Decode the document")]


class JSONApplicationAPI(API):
    tasks: JSONTaskResource


class FailureResource(Resource[Task]):
    @query
    async def invalid_result(self) -> Task:
        return {"id": 1}

    @query
    async def forbidden(self) -> Task:
        raise PermissionDenied("private implementation detail")

    @query
    async def missing(self) -> Task:
        raise Http404("private lookup detail")

    @query
    async def broken(self) -> Task:
        raise ValueError("private server detail")

    @mutation
    async def invalid_mutation(self) -> Task:
        return {"id": 2}


class FailureAPI(API):
    tasks: FailureResource


json_api = JSONApplicationAPI()


def call(pattern, payload):
    request = RequestFactory().post(
        "/api/" + str(pattern.pattern),
        data=json.dumps(payload),
        content_type="application/json",
    )
    return asyncio.run(pattern.callback(request))


def operation_pattern(api, name: str):
    return next(
        pattern for pattern in api.urls if pattern.callback.__name__ == name
    )


def test_csrf_failures_use_the_typed_operation_error_boundary():
    response = csrf_failure(
        RequestFactory().post("/api/tasks/save"),
        "CSRF token missing.",
    )

    assert response.status_code == 403
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": "csrf_failed",
                "detail": (
                    "The request could not be verified. Reload the page and try again."
                ),
                "status": "403",
                "title": "CSRF verification failed",
            }
        ]
    }


def test_static_api_hierarchy_provides_typed_cached_children():
    api = ApplicationAPI()

    assert isinstance(api.tasks, TaskResource)
    assert api.tasks is api.tasks
    assert api.tasks._path == "/api/tasks"
    assert TaskResource.__pyjs_model__ is Task
    assert set(TaskResource.__pyjs_operations__) == {"list", "save"}
    assert ProjectResource.__pyjs_relationships__ == {"tasks": list[Task]}
    assert TaskResource.__pyjs_relationships__ == {"comments": list[Comment]}
    assert TaskResource.__pyjs_api_children__ == {"comments": CommentResource}
    assert isinstance(api.tasks.comments, CommentResource)
    assert api.tasks.comments is api.tasks.comments
    assert api.tasks.comments._path == "/api/tasks/comments"


def test_resource_graph_resolves_relationship_shape_and_target():
    graph = resource_graph(ApplicationAPI)
    relationship = graph.relationships_by_key[(ProjectResource, "tasks")]

    assert graph is ApplicationAPI().resource_graph
    assert graph.resources_by_path == {
        ("projects",): graph.resources_by_path[("projects",)],
        ("tasks",): graph.resources_by_path[("tasks",)],
        ("tasks", "comments"): graph.resources_by_path[("tasks", "comments")],
    }
    assert graph.resources_by_model[Task] == (
        graph.resources_by_path[("tasks",)],
    )
    assert relationship.name == "tasks"
    assert relationship.owner.path == ("projects",)
    assert relationship.value_type == list[Task]
    assert relationship.model_type is Task
    assert relationship.target.path == ("tasks",)
    assert relationship.many is True
    assert relationship.nullable is False
    comments = graph.relationships_by_key[(TaskResource, "comments")]
    assert comments.target.path == ("tasks", "comments")
    assert comments.target.resource_type is CommentResource
    assert comments.many is True
    assert comments.nullable is False
    assert isinstance(graph.resources_by_path, MappingProxyType)
    assert graph.resources_by_type[TaskResource].model_type is Task
    assert isinstance(graph.resources_by_type, MappingProxyType)


def test_include_paths_encode_relationships_relative_to_a_resource():
    api = ApplicationAPI()

    assert include_paths(api.tasks, api.tasks.comments) == ["comments"]


def test_include_paths_encode_nested_relationships_without_strings():
    class Publisher(BaseModel):
        id: int

    class Book(BaseModel):
        id: int

    class Author(BaseModel):
        id: int

    class PublisherResource(Resource[Publisher]):
        pass

    class BookResource(Resource[Book]):
        publisher: Relationship[Publisher, PublisherResource]

    class AuthorResource(Resource[Author]):
        books: Relationship[list[Book], BookResource]

    class LibraryAPI(API):
        authors: AuthorResource

    api = LibraryAPI()

    paths = include_paths(
        api.authors,
        api.authors.books,
        api.authors.books.publisher,
    )
    includes = resolve_include_paths(LibraryAPI, AuthorResource, paths)

    assert paths == ["books", "books.publisher"]
    assert [include.path for include in includes] == paths
    assert [
        relationship.name
        for relationship in includes[1].relationships
    ] == ["books", "publisher"]
    assert includes[0].target.resource_type is BookResource
    assert includes[1].target.resource_type is PublisherResource


def test_include_paths_reject_non_relationship_api_children():
    api = ApplicationAPI()

    with pytest.raises(
        ValueError,
        match=r"^JSON:API includes must reference declared relationships\.$",
    ):
        include_paths(api, api.tasks)


def test_include_paths_reject_relationships_from_another_resource():
    api = ApplicationAPI()

    with pytest.raises(
        ValueError,
        match=r"^JSON:API includes must descend from the base resource\.$",
    ):
        include_paths(api.projects, api.tasks.comments)


@pytest.mark.parametrize("path", ["", ".comments", "comments.", "comments..author"])
def test_resolve_include_paths_reject_invalid_paths(path):
    with pytest.raises(
        ValueError,
        match=f"^Invalid relationship include path: {path!r}\\.$",
    ):
        resolve_include_paths(ApplicationAPI, TaskResource, [path])


def test_resolve_include_paths_reject_unknown_relationships():
    with pytest.raises(
        ValueError,
        match=(
            "^Unknown relationship include 'author' on CommentResource "
            "in path 'comments.author'\\.$"
        ),
    ):
        resolve_include_paths(
            ApplicationAPI,
            TaskResource,
            ["comments.author"],
        )


def test_resolve_include_paths_reject_unmounted_resource_type():
    class OtherResource(Resource[Task]):
        pass

    with pytest.raises(
        TypeError,
        match=r"^OtherResource is not mounted in ApplicationAPI\.$",
    ):
        resolve_include_paths(ApplicationAPI, OtherResource, ["comments"])


def test_resource_graph_assigns_stable_operation_and_argument_identities():
    graph = resource_graph(ApplicationAPI)

    assert [operation.identity for operation in graph.operations] == [
        "tasks.list",
        "tasks.save",
        "tasks.comments.add",
    ]
    assert graph.operations_by_identity["tasks.list"].kind == "query"
    assert graph.operations_by_identity["tasks.list"].argument_names == (
        "request",
    )
    assert graph.operations_by_identity["tasks.save"].kind == "mutation"
    assert graph.operations_by_identity["tasks.save"].argument_names == (
        "task",
    )
    assert graph.operations_by_identity["tasks.save"].owner.path == ("tasks",)


def test_transport_independent_dispatch_validates_and_serializes_operations():
    data = asyncio.run(
        dispatch_operation(
            ApplicationAPI,
            "tasks.list",
            {"request": {"page": 3, "page_size": 5}},
            SimpleNamespace(method="POST"),
        )
    )

    assert data == {
        "items": [
            {
                "completed": False,
                "id": 1,
                "title": "Write the proof of concept",
            }
        ],
        "page": 3,
        "page_size": 5,
        "total": 1,
    }


def test_typed_dispatch_uses_a_bound_operation_and_preserves_its_result():
    api = ApplicationAPI()
    data = asyncio.run(
        dispatch_for_request(
            SimpleNamespace(method="POST"),
            api.tasks.list,
            {"page": 3, "page_size": 5},
        )
    )

    assert data == TaskPage(
        items=[Task(id=1, title="Write the proof of concept")],
        page=3,
        page_size=5,
        total=1,
    )


def test_typed_dispatch_accepts_operation_keyword_arguments():
    api = ApplicationAPI()
    saved = asyncio.run(
        dispatch(
            api.tasks.save,
            task=Task(title="Typed server dispatch"),
        )
    )

    assert saved == Task(id=2, title="Typed server dispatch")


def test_django_sync_dispatch_preserves_typed_operation_calls():
    api = ApplicationAPI()

    saved = dispatch_sync(
        api.tasks.save,
        task=Task(title="Synchronous Django view"),
    )
    page = dispatch_for_request_sync(
        SimpleNamespace(method="POST"),
        api.tasks.list,
        PageRequest(page=4, page_size=10),
    )

    assert saved == Task(id=2, title="Synchronous Django view")
    assert page.page == 4
    assert page.page_size == 10


def test_typed_dispatch_rejects_non_operation_callables():
    async def helper(value: int) -> int:
        return value

    with pytest.raises(
        TypeError,
        match=r"^dispatch\(\) requires a bound resource operation$",
    ):
        asyncio.run(dispatch(helper, 1))


def test_typed_dispatch_reports_operation_signature_errors():
    with pytest.raises(
        TypeError,
        match=(
            r"^Cannot dispatch save\(\): missing a required argument: 'task'$"
        ),
    ):
        asyncio.run(dispatch(ApplicationAPI().tasks.save))


def test_api_subclasses_are_server_only_unless_explicitly_marked_for_clients():
    @js
    class ClientTaskResource(Resource[Task]):
        @query
        async def list(self, request: PageRequest) -> TaskPage:
            raise AssertionError("client contract")

    class ServerTaskResource(ClientTaskResource):
        async def list(self, request: PageRequest) -> TaskPage:
            return TaskPage(
                items=[Task(id=4, title="Server implementation")],
                page=request.page,
                page_size=request.page_size,
                total=1,
            )

    @js
    class SpecializedClientResource(ClientTaskResource):
        pass

    class ServerAPI(API):
        tasks: ServerTaskResource

    result = asyncio.run(
        dispatch(
            ServerAPI().tasks.list,
            PageRequest(page=2, page_size=10),
        )
    )

    assert is_js_enabled(ClientTaskResource) is True
    assert is_js_enabled(ServerTaskResource) is False
    assert is_js_enabled(SpecializedClientResource) is True
    assert result == TaskPage(
        items=[Task(id=4, title="Server implementation")],
        page=2,
        page_size=10,
        total=1,
    )


def test_server_operation_overrides_must_preserve_the_client_contract():
    @js
    class ClientTaskResource(Resource[Task]):
        @query
        async def list(self, request: PageRequest) -> TaskPage:
            raise AssertionError("client contract")

    with pytest.raises(
        TypeError,
        match=r"^Operation override SyncResource\.list must be async\.$",
    ):
        class SyncResource(ClientTaskResource):
            def list(self, request: PageRequest) -> TaskPage:
                raise AssertionError("invalid server implementation")

    with pytest.raises(
        TypeError,
        match=(
            r"^Operation override MismatchedResource\.list must preserve "
            r"its inherited signature\.$"
        ),
    ):
        class MismatchedResource(ClientTaskResource):
            async def list(self) -> TaskPage:
                raise AssertionError("invalid server implementation")


def test_transport_dispatch_retains_argument_paths_in_validation_errors():
    with pytest.raises(OperationError) as raised:
        asyncio.run(
            dispatch_operation(
                ApplicationAPI,
                "tasks.save",
                {"task": {"completed": False}},
            )
        )

    assert raised.value.payload() == {
        "errors": [
            {
                "code": "missing",
                "detail": "Field required",
                "source": {"pointer": "/task/title"},
                "status": "422",
                "title": "Validation error",
            }
        ]
    }


def test_transport_dispatch_can_retain_validated_models_for_an_adapter():
    data = asyncio.run(
        dispatch_operation(
            JSONApplicationAPI,
            "tasks.list",
            {},
            serialize=False,
        )
    )

    assert data == [Task(id=1, title="Decode the document")]


def test_transport_independent_dispatch_rejects_unknown_operations():
    with pytest.raises(OperationError) as raised:
        asyncio.run(
            dispatch_operation(
                ApplicationAPI,
                "tasks.remove",
                {},
            )
        )

    assert raised.value.payload() == {
        "errors": [
            {
                "code": "unknown_operation",
                "detail": "Unknown operation: tasks.remove.",
                "status": "400",
                "title": "Invalid request",
            }
        ]
    }


def test_resource_graph_rejects_missing_relationship_targets():
    class Missing(BaseModel):
        id: int

    class BrokenProjectResource(Resource[Project]):
        missing: Relationship[Missing]

    class BrokenAPI(API):
        projects: BrokenProjectResource

    with pytest.raises(
        TypeError,
        match=(
            r"^Relationship BrokenProjectResource\.missing targets Missing, but "
            r"no resource for that model is mounted in BrokenAPI\.$"
        ),
    ):
        resource_graph(BrokenAPI)


def test_model_results_on_plain_api_branches_use_plain_json():
    class Branch(API):
        @query
        async def first(self) -> Task:
            return Task(title="Plain JSON")

    class PlainAPI(API):
        branch: Branch

    graph = resource_graph(PlainAPI)
    api = PlainAPI()

    assert graph.operations_by_identity["branch.first"].operation.jsonapi is False
    assert api.branch._path == "/api/branch"
    assert "__pyjs_resource_graph__" not in Branch.__dict__


def test_other_model_results_on_resources_use_plain_json():
    class SummaryResource(Resource[Task]):
        @query
        async def project(self) -> Project:
            return Project(id=1, name="Plain JSON")

    class SummaryAPI(API):
        tasks: SummaryResource

    graph = resource_graph(SummaryAPI)

    assert graph.operations_by_identity["tasks.project"].operation.jsonapi is False


def test_resource_graph_requires_selection_for_ambiguous_models():
    class PublicTaskResource(Resource[Task]):
        pass

    class AdminTaskResource(Resource[Task]):
        pass

    class AmbiguousProjectResource(Resource[Project]):
        tasks: Relationship[list[Task]]

    class AmbiguousAPI(API):
        projects: AmbiguousProjectResource
        public_tasks: PublicTaskResource
        admin_tasks: AdminTaskResource

    with pytest.raises(
        TypeError,
        match=(
            r"^Relationship AmbiguousProjectResource\.tasks has multiple resources "
            r"for Task: PublicTaskResource at 'public_tasks', AdminTaskResource at "
            r"'admin_tasks'\. Select a resource type as the second Relationship "
            r"argument\.$"
        ),
    ):
        resource_graph(AmbiguousAPI)


def test_resource_graph_accepts_an_explicit_relationship_resource():
    class PublicTaskResource(Resource[Task]):
        pass

    class AdminTaskResource(Resource[Task]):
        pass

    class SelectedProjectResource(Resource[Project]):
        tasks: Relationship[list[Task], PublicTaskResource]

    class SelectedAPI(API):
        projects: SelectedProjectResource
        admin_tasks: AdminTaskResource

    graph = resource_graph(SelectedAPI)
    relationship = graph.relationships_by_key[(SelectedProjectResource, "tasks")]

    assert relationship.target.resource_type is PublicTaskResource
    assert relationship.target.path == ("projects", "tasks")
    assert SelectedProjectResource.__pyjs_api_children__ == {
        "tasks": PublicTaskResource
    }


def test_relationship_rejects_a_non_resource_second_argument():
    with pytest.raises(
        TypeError,
        match=(
            r"^Relationship InvalidProjectResource\.tasks selects "
            r"Task, which is not a Resource type\.$"
        ),
    ):

        class InvalidProjectResource(Resource[Project]):
            tasks: Relationship[list[Task], Task]


def test_resource_graph_rejects_a_relationship_resource_for_another_model():
    class WrongTaskResource(Resource[Project]):
        pass

    class WrongProjectResource(Resource[Project]):
        tasks: Relationship[list[Task], WrongTaskResource]

    class WrongAPI(API):
        projects: WrongProjectResource

    with pytest.raises(
        TypeError,
        match=(
            r"^Relationship WrongProjectResource\.tasks targets Task, but "
            r"WrongTaskResource exposes Project\.$"
        ),
    ):
        resource_graph(WrongAPI)


def test_resource_graph_resolves_deferred_relationship_annotations():
    class Source(BaseModel):
        id: int

    class SourceResource(Resource[Source]):
        destination: Relationship[Destination | None]

    class Destination(BaseModel):
        id: int

    class DestinationResource(Resource[Destination]):
        pass

    class DeferredAPI(API):
        sources: SourceResource
        destinations: DestinationResource

    relationship = resource_graph(DeferredAPI).relationships_by_key[
        (SourceResource, "destination")
    ]

    assert relationship.model_type is Destination
    assert relationship.target.resource_type is DestinationResource
    assert relationship.many is False
    assert relationship.nullable is True


def test_resource_graph_rejects_repeated_resource_mounts():
    class RepeatedAPI(API):
        primary_tasks: TaskResource
        secondary_tasks: TaskResource

    with pytest.raises(
        TypeError,
        match=(
            r"^TaskResource is mounted at both 'primary_tasks' and "
            r"'secondary_tasks'; use distinct resource subclasses\.$"
        ),
    ):
        resource_graph(RepeatedAPI)


def test_django_urls_dispatch_and_validate_typed_operations():
    patterns = ApplicationAPI().urls

    assert [str(pattern.pattern) for pattern in patterns] == [
        "atomic",
        "tasks/list",
        "tasks/save",
        "tasks/comments/add",
        "_live/events",
        "_live/poll",
        "_live/refresh",
        "_live/subscribe",
    ]

    response = call(
        operation_pattern(ApplicationAPI(), "tasks_list"),
        {"request": {"page": 2, "page_size": 10}},
    )
    assert response.status_code == 200
    assert json.loads(response.content) == {
        "items": [
            {
                "completed": False,
                "id": 1,
                "title": "Write the proof of concept",
            }
        ],
        "page": 2,
        "page_size": 10,
        "total": 1,
    }
    response = call(
        operation_pattern(ApplicationAPI(), "tasks_save"),
        {"task": {"completed": True, "title": "Test the dispatcher"}},
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/vnd.api+json"
    assert json.loads(response.content) == {
        "data": {
            "type": "tasks",
            "id": "2",
            "attributes": {
                "completed": True,
                "title": "Test the dispatcher",
            },
        }
    }

    response = call(
        operation_pattern(ApplicationAPI(), "tasks_comments_add"),
        {"comment": {"body": "Nested resource"}},
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "application/vnd.api+json"
    assert json.loads(response.content) == {
        "data": {
            "type": "comments",
            "id": "3",
            "attributes": {"body": "Nested resource"},
        }
    }


def test_django_jsonapi_operation_encodes_a_resource_document():
    patterns = json_api.urls

    assert [str(pattern.pattern) for pattern in patterns] == [
        "atomic",
        "tasks/list",
        "_live/events",
        "_live/poll",
        "_live/refresh",
        "_live/subscribe",
    ]
    response = call(operation_pattern(json_api, "tasks_list"), {})
    assert response.status_code == 200
    assert response["Content-Type"] == "application/vnd.api+json"
    assert json.loads(response.content) == {
        "data": [
            {
                "type": "tasks",
                "id": "1",
                "attributes": {
                    "completed": False,
                    "title": "Decode the document",
                },
            }
        ]
    }


def test_django_rejects_queryset_results_for_plain_json_operations():
    class PageResource(Resource[Task]):
        @query
        async def page(self) -> TaskPage:
            return queryset_result(AuthorRecord.objects.none())

    class PageAPI(API):
        tasks: PageResource

    response = call(operation_pattern(PageAPI(), "tasks_page"), {})

    assert response.status_code == 500
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": "server_error",
                "detail": "The server could not complete the operation.",
                "status": "500",
                "title": "Server error",
            }
        ]
    }


def test_django_urls_return_structured_argument_errors():
    save = operation_pattern(ApplicationAPI(), "tasks_save")

    response = call(save, {"task": {"completed": False}})

    assert response.status_code == 422
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": "missing",
                "detail": "Field required",
                "source": {"pointer": "/task/title"},
                "status": "422",
                "title": "Validation error",
            }
        ]
    }


def test_django_urls_reject_unknown_arguments():
    list_tasks = operation_pattern(ApplicationAPI(), "tasks_list")

    response = call(
        list_tasks,
        {"request": {"page": 1}, "unexpected": True},
    )

    assert response.status_code == 400
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": "unexpected_arguments",
                "detail": "Unexpected argument(s): unexpected.",
                "status": "400",
                "title": "Invalid request",
            }
        ]
    }


@pytest.mark.parametrize(
    ("name", "status", "code", "detail", "title"),
    [
        (
            "tasks_invalid_result",
            500,
            "server_error",
            "The server could not complete the operation.",
            "Server error",
        ),
        (
            "tasks_forbidden",
            403,
            "permission_denied",
            "You do not have permission to perform this operation.",
            "Permission denied",
        ),
        (
            "tasks_missing",
            404,
            "not_found",
            "The requested resource was not found.",
            "Not found",
        ),
        (
            "tasks_broken",
            500,
            "server_error",
            "The server could not complete the operation.",
            "Server error",
        ),
    ],
)
def test_django_urls_sanitize_server_failures(
    name,
    status,
    code,
    detail,
    title,
):
    response = call(operation_pattern(FailureAPI(), name), {})

    assert response.status_code == status
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": code,
                "detail": detail,
                "status": str(status),
                "title": title,
            }
        ]
    }


def test_atomic_result_validation_is_a_sanitized_server_failure():
    response = call(
        operation_pattern(FailureAPI(), "atomic"),
        {
            "operations": [
                {
                    "operation": "tasks.invalid_mutation",
                    "arguments": {},
                }
            ]
        },
    )

    assert response.status_code == 500
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": "server_error",
                "detail": "The server could not complete the operation.",
                "status": "500",
                "title": "Server error",
            }
        ]
    }


def test_django_urls_reject_non_post_requests():
    pattern = operation_pattern(ApplicationAPI(), "tasks_list")
    request = RequestFactory().get("/api/tasks/list")

    response = asyncio.run(pattern.callback(request))

    assert response.status_code == 405
    assert json.loads(response.content) == {
        "errors": [
            {
                "code": "invalid",
                "detail": "RPC operations require POST.",
                "status": "405",
                "title": "Invalid request",
            }
        ]
    }
