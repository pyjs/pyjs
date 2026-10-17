from django.db import models


class AuthorRecord(models.Model):
    name = models.CharField(max_length=100)

    @property
    def display_name(self):
        return self.name.upper()


class PublisherRecord(models.Model):
    name = models.CharField(max_length=100)


class TagRecord(models.Model):
    name = models.CharField(max_length=100)


class ChoiceRecord(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"

    state = models.CharField(max_length=20, choices=State, default=State.DRAFT)


class BookRecord(models.Model):
    author = models.ForeignKey(
        AuthorRecord,
        on_delete=models.CASCADE,
        related_name="books",
    )
    publisher = models.ForeignKey(
        PublisherRecord,
        null=True,
        on_delete=models.SET_NULL,
        related_name="books",
    )
    tags = models.ManyToManyField(TagRecord, related_name="books")
    title = models.CharField(max_length=100)

    class Meta:
        ordering = ("id",)
