from pydantic import BaseModel
from pyjs import js
from pyjs.server.django import ModelSchema

from . import models as db


@js
class UserSummary(ModelSchema):
    class Meta:
        model = db.Person
        fields = ("name", "initials")


@js
class Label(ModelSchema):
    class Meta:
        model = db.Label
        fields = ("name", "color")


@js
class Milestone(ModelSchema):
    class Meta:
        model = db.Milestone
        fields = ("title", "due_date")


@js
class Project(ModelSchema):
    id: int

    class Meta:
        model = db.Project
        fields = ("key", "name", "description")


@js
class Issue(BaseModel):
    id: int
    number: int
    project: Project
    title: str
    description: str
    status: str
    priority: str
    author: UserSummary
    assignee: UserSummary | None = None
    labels: list[Label] = []
    milestone: Milestone | None = None
    comment_count: int = 0
    created_at: str
    updated_at: str


@js
class Comment(BaseModel):
    id: int
    issue_id: int
    author: UserSummary
    body: str
    created_at: str


@js
class ActivityEvent(BaseModel):
    id: int
    issue_id: int
    actor: UserSummary
    kind: str
    message: str
    occurred_at: str


@js
class IssueDraft(BaseModel):
    title: str
    description: str = ""
    priority: str = "normal"
    project_id: int = 1
    assignee_id: int | None = 2
    label_ids: list[int] = [1]
    milestone_id: int | None = 1


@js
class IssueListRequest(BaseModel):
    page: int = 1
    page_size: int = 25
    status: str = "all"
    query: str = ""


@js
class IssueRequest(BaseModel):
    issue_id: int


@js
class IssueStatusRequest(BaseModel):
    issue_id: int
    status: str


@js
class CommentDraft(BaseModel):
    issue_id: int
    body: str


@js
class IssuePage(BaseModel):
    items: list[Issue]
    page: int
    page_size: int
    total: int
    open_count: int
    closed_count: int


@js
class IssueDetail(BaseModel):
    issue: Issue
    comments: list[Comment]
    activity: list[ActivityEvent]


@js
class IssueMutationResult(BaseModel):
    issue: Issue
