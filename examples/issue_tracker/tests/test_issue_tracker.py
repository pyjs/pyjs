import asyncio
import json
from datetime import date

import pytest
from django.test import RequestFactory
from pyjs.server import OperationError
from pyjs_examples.issue_tracker import models as db
from pyjs_examples.issue_tracker.api import (
    ApplicationAPI,
    CommentResource,
    IssueResource,
    LabelResource,
    ProjectResource,
    UserResource,
    issue_detail,
    issue_page,
)
from pyjs_examples.issue_tracker.core import (
    Comment,
    CommentDraft,
    Issue,
    IssueDraft,
    IssueListRequest,
    IssueStatusRequest,
    Label,
    Milestone,
    Project,
    UserSummary,
)


def test_fixture_data_exercises_nested_and_optional_model_fields():
    page = issue_page(IssueListRequest())
    first = page.items[0]
    closed = page.items[2]

    assert first.model_dump() == {
        "assignee": {
            "id": 2,
            "initials": "GH",
            "name": "Grace Hopper",
        },
        "author": {
            "id": 1,
            "initials": "AL",
            "name": "Ada Lovelace",
        },
        "comment_count": 2,
        "created_at": "Aug 10, 2026",
        "description": (
            "Keep generated API bundles focused on the branches used by each "
            "screen."
        ),
        "id": 101,
        "labels": [
            {"color": "violet", "id": 1, "name": "compiler"},
            {"color": "emerald", "id": 2, "name": "django"},
        ],
        "milestone": {
            "due_date": date(2026, 8, 30),
            "id": 1,
            "title": "0.0.3",
        },
        "number": 41,
        "priority": "high",
        "project": {
            "description": "Build Python applications for every JavaScript runtime.",
            "id": 1,
            "key": "PYJS",
            "name": "PyJS",
        },
        "status": "open",
        "title": "Tree-shake unused client API operations",
        "updated_at": "Aug 12, 2026",
    }
    assert closed.assignee is None
    assert closed.milestone is None
    assert page.open_count == 2
    assert page.closed_count == 1


def test_django_models_define_normal_relations_and_constraints():
    issue = db.Issue.objects.get(pk=101)

    assert issue.project.key == "PYJS"
    assert issue.author.name == "Ada Lovelace"
    assert issue.assignee.name == "Grace Hopper"
    assert list(issue.labels.values_list("name", flat=True)) == [
        "compiler",
        "django",
    ]
    assert issue.milestone.title == "0.0.3"
    assert issue.comments.count() == 2
    assert db.Issue._meta.constraints[0].fields == ("project", "number")


def test_project_query_encodes_its_lazy_queryset_as_jsonapi():
    pattern = ApplicationAPI().urls[0]
    request = RequestFactory().post(
        "/api/projects/list",
        data="{}",
        content_type="application/json",
    )

    response = asyncio.run(pattern.callback(request))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/vnd.api+json"
    assert json.loads(response.content) == {
        "data": [
            {
                "type": "projects",
                "id": "1",
                "attributes": {
                    "description": (
                        "Build Python applications for every JavaScript runtime."
                    ),
                    "key": "PYJS",
                    "name": "PyJS",
                },
                "relationships": {
                    "milestones": {
                        "data": [{"type": "milestones", "id": "1"}]
                    }
                },
            }
        ],
        "included": [
            {
                "type": "milestones",
                "id": "1",
                "attributes": {
                    "due_date": "2026-08-30",
                    "title": "0.0.3",
                },
            }
        ],
    }


def test_resources_keep_relationships_separate_from_models():
    assert ApplicationAPI.__pyjs_api_children__ == {
        "issues": IssueResource,
        "labels": LabelResource,
        "projects": ProjectResource,
        "users": UserResource,
    }
    assert IssueResource.__pyjs_api_children__ == {"comments": CommentResource}
    assert IssueResource.__pyjs_relationships__ == {
        "assignee": UserSummary | None,
        "comments": list[Comment],
        "labels": list[Label],
        "milestone": Milestone | None,
        "project": Project,
    }
    assert Issue.model_fields["project"].annotation is Project


def test_resource_graph_resolves_the_issue_tracker_relationships():
    graph = ApplicationAPI().resource_graph

    assert [resource.path for resource in graph.resources] == [
        ("projects",),
        ("projects", "milestones"),
        ("issues",),
        ("issues", "comments"),
        ("users",),
        ("labels",),
    ]
    assert {
        (relationship.owner.resource_type.__name__, relationship.name): (
            relationship.target.path,
            relationship.many,
            relationship.nullable,
        )
        for relationship in graph.relationships
    } == {
        ("IssueResource", "assignee"): (("users",), False, True),
        ("IssueResource", "comments"): (
            ("issues", "comments"),
            True,
            False,
        ),
        ("IssueResource", "labels"): (("labels",), True, False),
        ("IssueResource", "milestone"): (
            ("projects", "milestones"),
            False,
            True,
        ),
        ("IssueResource", "project"): (("projects",), False, False),
        ("ProjectResource", "issues"): (("issues",), True, False),
        ("ProjectResource", "milestones"): (
            ("projects", "milestones"),
            True,
            False,
        ),
    }
    assert [operation.identity for operation in graph.operations] == [
        "projects.list",
        "issues.list",
        "issues.get",
        "issues.save",
        "issues.set_status",
        "issues.comments.add",
    ]


def test_issue_queries_filter_and_return_related_detail():
    closed = issue_page(IssueListRequest(status="closed"))
    searched = issue_page(IssueListRequest(query="stream"))
    detail = issue_detail(101)

    assert [issue.title for issue in closed.items] == [
        "Document resource permissions"
    ]
    assert [issue.title for issue in searched.items] == [
        "Stream project activity to connected clients"
    ]
    assert [comment.body for comment in detail.comments] == [
        "The generated bundle now contains only this branch.",
        "Great. The exact-output tests cover sibling resources too.",
    ]
    assert [event.kind for event in detail.activity] == ["created", "assigned"]


def test_issue_mutations_update_the_authoritative_database():
    async def mutate():
        resources = ApplicationAPI().issues
        result = await resources.save(
            IssueDraft(
                title="Exercise the resource graph",
                description="Created by the server-side API test.",
                priority="high",
            )
        )
        issue = result.issue
        comment = await resources.comments.add(
            CommentDraft(issue_id=issue.id, body="Nested mutation complete.")
        )
        closed = await resources.set_status(
            IssueStatusRequest(issue_id=issue.id, status="closed")
        )
        return issue, comment, closed.issue

    issue, comment, closed = asyncio.run(mutate())
    stored = db.Issue.objects.get(pk=issue.id)

    assert issue.number == 43
    assert issue.project.key == "PYJS"
    assert issue.assignee.name == "Grace Hopper"
    assert [label.name for label in issue.labels] == ["compiler"]
    assert issue.milestone == Milestone(
        due_date=date(2026, 8, 30),
        id=1,
        title="0.0.3",
    )
    assert comment.body == "Nested mutation complete."
    assert closed.status == "closed"
    assert stored.status == db.Issue.Status.CLOSED
    assert stored.comments.count() == 1
    assert [event.kind for event in issue_detail(issue.id).activity] == [
        "created",
        "commented",
        "status",
    ]


def test_issue_mutations_reject_invalid_domain_values():
    async def reject_invalid_values():
        resources = ApplicationAPI().issues
        with pytest.raises(
            OperationError,
            match="An issue title must contain at least three characters.",
        ):
            await resources.save(IssueDraft(title="x"))
        with pytest.raises(
            ValueError,
            match="A comment cannot be empty.",
        ):
            await resources.comments.add(CommentDraft(issue_id=101, body=" "))
        with pytest.raises(
            OperationError,
            match="Unsupported issue priority: urgent.",
        ):
            await resources.save(IssueDraft(title="Invalid priority", priority="urgent"))
        with pytest.raises(
            ValueError,
            match="Unsupported issue status: archived.",
        ):
            await resources.set_status(
                IssueStatusRequest(issue_id=101, status="archived")
            )

    asyncio.run(reject_invalid_values())
