from django.db import models


class Person(models.Model):
    name = models.CharField(max_length=120)
    initials = models.CharField(max_length=4)

    def __str__(self) -> str:
        return self.name


class Project(models.Model):
    key = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class Label(models.Model):
    name = models.CharField(max_length=60, unique=True)
    color = models.CharField(max_length=30)

    def __str__(self) -> str:
        return self.name


class Milestone(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="milestones",
    )
    title = models.CharField(max_length=120)
    due_date = models.DateField()

    def __str__(self) -> str:
        return self.title


class Issue(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="issues",
    )
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=12,
        choices=Status,
        default=Status.OPEN,
    )
    priority = models.CharField(
        max_length=12,
        choices=Priority,
        default=Priority.NORMAL,
    )
    author = models.ForeignKey(
        Person,
        on_delete=models.PROTECT,
        related_name="authored_issues",
    )
    assignee = models.ForeignKey(
        Person,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="assigned_issues",
    )
    labels = models.ManyToManyField(Label, blank=True, related_name="issues")
    milestone = models.ForeignKey(
        Milestone,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="issues",
    )
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("project", "number"),
                name="issue_tracker_unique_project_issue",
            )
        ]
        ordering = ("-updated_at", "-number")

    def __str__(self) -> str:
        return f"{self.project.key}-{self.number}: {self.title}"


class Comment(models.Model):
    issue = models.ForeignKey(
        Issue,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        Person,
        on_delete=models.PROTECT,
        related_name="comments",
    )
    body = models.TextField()
    created_at = models.DateTimeField()

    class Meta:
        ordering = ("created_at", "id")


class Activity(models.Model):
    issue = models.ForeignKey(
        Issue,
        on_delete=models.CASCADE,
        related_name="activity",
    )
    actor = models.ForeignKey(
        Person,
        on_delete=models.PROTECT,
        related_name="issue_activity",
    )
    kind = models.CharField(max_length=30)
    message = models.CharField(max_length=240)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ("occurred_at", "id")
