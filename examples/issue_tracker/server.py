import os
import tempfile
from pathlib import Path

from django.http import HttpRequest, HttpResponse
from django.views.static import serve as serve_static
from pyjs.server.django import PyJSApplication

from .api import issue_detail, issue_page
from .core import IssueListRequest
from .ui import IssueTracker, main

STATIC_ROOT = Path(tempfile.gettempdir()) / f"pyjs-issue-tracker-{os.getpid()}"


def render_application():
    page = issue_page(IssueListRequest())
    return IssueTracker(page, issue_detail(page.items[0].id))


application = PyJSApplication(
    main,
    name="issue_tracker",
    body_attributes={"class": "bg-slate-50 text-slate-950"},
)


def index(request: HttpRequest) -> HttpResponse:
    return application.response(
        request,
        render_application(),
        title="Issue tracker · PyJS",
    )


def static_asset(request: HttpRequest, path: str) -> HttpResponse:
    return serve_static(request, path, document_root=STATIC_ROOT)
