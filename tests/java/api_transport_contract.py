"""One typed contract shared by the Django fixture and compiled client."""

from pydantic import BaseModel, Field

from pyjs.server import API, query


class Draft(BaseModel):
    title: str = Field(min_length=1)
    count: int = 0


class EchoAPI(API):
    @query
    async def echo(self, draft: Draft) -> Draft:
        from django.core.exceptions import PermissionDenied

        if self.request.headers.get("Authorization") != "Bearer test-token":
            raise PermissionDenied("missing test credential")
        return draft
