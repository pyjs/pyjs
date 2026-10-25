"""A typed API protected by Django's ordinary authenticated session."""

from pyjs.server import API, mutation, query
from tests.java.api_transport_contract import Draft


class AuthenticatedAPI(API):
    @query
    async def username(self) -> str:
        from asgiref.sync import sync_to_async

        return await sync_to_async(lambda: self.request.user.get_username())()

    @mutation
    async def echo(self, draft: Draft) -> Draft:
        from asgiref.sync import sync_to_async
        from django.core.exceptions import PermissionDenied

        username = await sync_to_async(lambda: self.request.user.get_username())()
        if not username:
            raise PermissionDenied("Sign in first")
        return draft
