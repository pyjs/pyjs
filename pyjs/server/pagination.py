from pydantic import BaseModel, Field

from pyjs import js


@js
class OffsetPageRequest(BaseModel):
    """Request one page using a one-based page number and bounded size."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)


@js
class CursorPageRequest(BaseModel):
    """Request records before or after an opaque stable cursor."""

    size: int = Field(default=25, ge=1, le=100)
    after: str | None = None
    before: str | None = None


@js
class Page[Value](BaseModel):
    """A page of typed values with optional navigation cursors and total."""

    items: list[Value]
    next: str | None = None
    previous: str | None = None
    total: int | None = None
