from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone
from pyjs import js
from pyjs.server import (
    API,
    Relationship,
    Resource,
    action,
    include_paths,
    mutation,
    operation_error,
    query,
)
from pyjs.server.django import queryset_result

from . import models as db
from .core import (
    ActivityEvent,
    Comment,
    CommentDraft,
    Issue,
    IssueDetail,
    IssueDraft,
    IssueListRequest,
    IssueMutationResult,
    IssuePage,
    IssueRequest,
    IssueStatusRequest,
    Label,
    Milestone,
    Project,
    UserSummary,
)


def display_date(value) -> str:
    return f"{value:%b} {value.day}, {value.year}"


def user_value(person: db.Person) -> UserSummary:
    return UserSummary(id=person.id, name=person.name, initials=person.initials)


def project_value(project: db.Project) -> Project:
    return Project(
        id=project.id,
        key=project.key,
        name=project.name,
        description=project.description,
    )


def label_value(label: db.Label) -> Label:
    return Label(id=label.id, name=label.name, color=label.color)


def milestone_value(milestone: db.Milestone | None) -> Milestone | None:
    if milestone is None:
        return None
    return Milestone(
        id=milestone.id,
        title=milestone.title,
        due_date=milestone.due_date,
    )


def issue_queryset():
    return (
        db.Issue.objects.select_related(
            "project",
            "author",
            "assignee",
            "milestone",
        )
        .prefetch_related("labels")
        .annotate(comment_total=Count("comments"))
    )


def issue_value(issue: db.Issue) -> Issue:
    assignee = None
    if issue.assignee is not None:
        assignee = user_value(issue.assignee)
    comment_count = getattr(issue, "comment_total", None)
    if comment_count is None:
        comment_count = issue.comments.count()
    return Issue(
        id=issue.id,
        number=issue.number,
        project=project_value(issue.project),
        title=issue.title,
        description=issue.description,
        status=issue.status,
        priority=issue.priority,
        author=user_value(issue.author),
        assignee=assignee,
        labels=[label_value(label) for label in issue.labels.all()],
        milestone=milestone_value(issue.milestone),
        comment_count=comment_count,
        created_at=display_date(issue.created_at),
        updated_at=display_date(issue.updated_at),
    )


def comment_value(comment: db.Comment) -> Comment:
    return Comment(
        id=comment.id,
        issue_id=comment.issue_id,
        author=user_value(comment.author),
        body=comment.body,
        created_at=display_date(comment.created_at),
    )


def activity_value(event: db.Activity) -> ActivityEvent:
    return ActivityEvent(
        id=event.id,
        issue_id=event.issue_id,
        actor=user_value(event.actor),
        kind=event.kind,
        message=event.message,
        occurred_at=display_date(event.occurred_at),
    )


def find_issue(issue_id: int) -> db.Issue:
    try:
        return issue_queryset().get(pk=issue_id)
    except db.Issue.DoesNotExist as error:
        raise ValueError(f"Unknown issue: {issue_id}.") from error


def issue_page(request: IssueListRequest) -> IssuePage:
    counts = db.Issue.objects.aggregate(
        open_count=Count("id", filter=Q(status=db.Issue.Status.OPEN)),
        closed_count=Count("id", filter=Q(status=db.Issue.Status.CLOSED)),
    )
    matches = issue_queryset()
    if request.status != "all":
        matches = matches.filter(status=request.status)
    search = request.query.strip()
    if search:
        matches = matches.filter(title__icontains=search)
    total = matches.count()
    start = (request.page - 1) * request.page_size
    end = start + request.page_size
    return IssuePage(
        items=[issue_value(issue) for issue in matches[start:end]],
        page=request.page,
        page_size=request.page_size,
        total=total,
        open_count=counts["open_count"],
        closed_count=counts["closed_count"],
    )


def issue_detail(issue_id: int) -> IssueDetail:
    issue = find_issue(issue_id)
    comments = db.Comment.objects.filter(issue=issue).select_related("author")
    activity = db.Activity.objects.filter(issue=issue).select_related("actor")
    return IssueDetail(
        issue=issue_value(issue),
        comments=[comment_value(comment) for comment in comments],
        activity=[activity_value(event) for event in activity],
    )


@transaction.atomic
def create_issue(draft: IssueDraft) -> Issue:
    if len(draft.title.strip()) < 3:
        raise operation_error(
            "An issue title must contain at least three characters.",
            "draft",
            "title",
            code="too_short",
        )
    if draft.priority not in db.Issue.Priority.values:
        raise operation_error(
            f"Unsupported issue priority: {draft.priority}.",
            "draft",
            "priority",
            code="invalid_choice",
        )
    try:
        project = db.Project.objects.get(pk=draft.project_id)
        author = db.Person.objects.get(pk=1)
        assignee = (
            None
            if draft.assignee_id is None
            else db.Person.objects.get(pk=draft.assignee_id)
        )
        milestone = (
            None
            if draft.milestone_id is None
            else db.Milestone.objects.get(
                pk=draft.milestone_id,
                project=project,
            )
        )
    except (
        db.Project.DoesNotExist,
        db.Person.DoesNotExist,
        db.Milestone.DoesNotExist,
    ) as error:
        raise ValueError("The issue references an unknown related object.") from error
    number = (
        db.Issue.objects.filter(project=project).aggregate(Max("number"))[
            "number__max"
        ]
        or 0
    ) + 1
    now = timezone.now()
    issue = db.Issue.objects.create(
        project=project,
        number=number,
        title=draft.title.strip(),
        description=draft.description,
        priority=draft.priority,
        author=author,
        assignee=assignee,
        milestone=milestone,
        created_at=now,
        updated_at=now,
    )
    labels = list(db.Label.objects.filter(pk__in=draft.label_ids))
    if len(labels) != len(set(draft.label_ids)):
        raise ValueError("The issue references an unknown label.")
    issue.labels.set(labels)
    db.Activity.objects.create(
        issue=issue,
        actor=author,
        kind="created",
        message="opened this issue",
        occurred_at=now,
    )
    return issue_value(find_issue(issue.id))


@transaction.atomic
def create_comment(draft: CommentDraft) -> Comment:
    if not draft.body.strip():
        raise ValueError("A comment cannot be empty.")
    issue = find_issue(draft.issue_id)
    now = timezone.now()
    comment = db.Comment.objects.create(
        issue=issue,
        author=issue.author,
        body=draft.body.strip(),
        created_at=now,
    )
    db.Activity.objects.create(
        issue=issue,
        actor=issue.author,
        kind="commented",
        message="added a comment",
        occurred_at=now,
    )
    db.Issue.objects.filter(pk=issue.id).update(updated_at=now)
    return comment_value(comment)


@transaction.atomic
def change_issue_status(request: IssueStatusRequest) -> Issue:
    if request.status not in (db.Issue.Status.OPEN, db.Issue.Status.CLOSED):
        raise ValueError(f"Unsupported issue status: {request.status}.")
    issue = find_issue(request.issue_id)
    now = timezone.now()
    issue.status = request.status
    issue.updated_at = now
    issue.save(update_fields=("status", "updated_at"))
    db.Activity.objects.create(
        issue=issue,
        actor=issue.author,
        kind="status",
        message="changed the status to " + request.status,
        occurred_at=now,
    )
    return issue_value(find_issue(issue.id))


@js
class CommentResource(Resource[Comment]):
    @mutation
    async def add(self, draft: CommentDraft) -> Comment:
        return await sync_to_async(create_comment)(draft)


@js
class IssueResource(Resource[Issue]):
    project: Relationship[Project]
    assignee: Relationship[UserSummary | None]
    labels: Relationship[list[Label]]
    milestone: Relationship[Milestone | None]
    comments: Relationship[list[Comment], CommentResource]

    @query
    async def list(self, request: IssueListRequest) -> IssuePage:
        return await sync_to_async(issue_page)(request)

    @query
    async def get(self, request: IssueRequest) -> IssueDetail:
        return await sync_to_async(issue_detail)(request.issue_id)

    @mutation
    async def save(self, draft: IssueDraft) -> IssueMutationResult:
        issue = await sync_to_async(create_issue)(draft)
        return IssueMutationResult(issue=issue)

    @action
    async def set_status(self, request: IssueStatusRequest) -> IssueMutationResult:
        issue = await sync_to_async(change_issue_status)(request)
        return IssueMutationResult(issue=issue)


@js
class UserResource(Resource[UserSummary]):
    pass


@js
class LabelResource(Resource[Label]):
    pass


@js
class MilestoneResource(Resource[Milestone]):
    pass


@js
class ProjectResource(Resource[Project]):
    issues: Relationship[list[Issue]]
    milestones: Relationship[list[Milestone], MilestoneResource]

    @query
    async def list(self) -> list[Project]:
        return queryset_result(
            db.Project.objects.order_by("name"),
            include_paths=include_paths(self, self.milestones),
        )


@js
class ApplicationAPI(API):
    projects: ProjectResource
    issues: IssueResource
    users: UserResource
    labels: LabelResource


api = ApplicationAPI()
