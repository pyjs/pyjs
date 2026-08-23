import os
import tempfile
from pathlib import Path

from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.views.static import serve as serve_static
from pyjs.server.django import PyJSApplication
from pyjs.web.dom import Element
from pyjs.web.domx import button, form, h1, input, p, tag
from pyjs.web.ssr import render_document

from . import models as db
from .api import (
    account_summary,
    inventory_page,
    order_history_page,
    payment_gateway,
    product_page,
    review_moderation_page,
    traffic_summary,
    visitor_event_page,
)
from .store import (
    ACCOUNT_PAGE,
    CATALOG_PAGE,
    INVENTORY_PAGE,
    REVIEW_MODERATION_PAGE,
    STORE_APPLICATION,
    STORY_PAGE,
    VISITOR_ACTIVITY_PAGE,
)

STATIC_ROOT = Path(
    os.environ.get(
        "PYJS_STORE_TEST_STATIC_ROOT",
        Path(tempfile.gettempdir()) / f"pyjs-store-static-{os.getpid()}",
    )
)

application = PyJSApplication(
    STORE_APPLICATION,
    name="store",
    layout_id="store",
    body_attributes={"class": "bg-stone-50 text-stone-950"},
)


def index(request: HttpRequest) -> HttpResponse:
    return application.response(
        request,
        CATALOG_PAGE(product_page()),
        title="Northstar Supply · PyJS",
    )


def story(request: HttpRequest) -> HttpResponse:
    return application.response(
        request,
        STORY_PAGE(),
        title="Our story · Northstar Supply",
    )


def account(request: HttpRequest) -> HttpResponse:
    return application.response(
        request,
        ACCOUNT_PAGE(account_summary(), order_history_page()),
        title="Account · Northstar Supply",
    )


def inventory(request: HttpRequest) -> HttpResponse:
    return application.response(
        request,
        INVENTORY_PAGE(inventory_page()),
        title="Inventory · Northstar Supply",
    )


def reviews(request: HttpRequest) -> HttpResponse:
    return application.response(
        request,
        REVIEW_MODERATION_PAGE(review_moderation_page()),
        title="Review moderation · Northstar Supply",
    )


def visitors(request: HttpRequest) -> HttpResponse:
    return application.response(
        request,
        VISITOR_ACTIVITY_PAGE(traffic_summary(), visitor_event_page()),
        title="Visitor activity · Northstar Supply",
    )


def payment_page(session: dict[str, object], csrf_token: str) -> Element:
    amount = int(session["amount_cents"])
    return tag(
        "html",
        tag(
            "head",
            tag("meta", {"charset": "utf-8"}),
            tag("meta", {"name": "viewport", "content": "width=device-width"}),
            tag("title", "Northstar test payment"),
        ),
        tag(
            "body",
            {
                "style": (
                    "margin:0;background:#0c0a09;color:#fafaf9;font-family:system-ui;"
                    "min-height:100vh;display:grid;place-items:center;padding:1.5rem"
                )
            },
            tag(
                "main",
                {
                    "style": (
                        "width:min(28rem,100%);border:1px solid #44403c;border-radius:1rem;"
                        "background:#1c1917;padding:2rem;box-sizing:border-box"
                    )
                },
                p({"style": "color:#fbbf24;margin:0"}, "Stripe simulator"),
                h1({"style": "font:2rem Georgia;margin:.75rem 0"}, session["name"]),
                p(
                    {"style": "color:#a8a29e"},
                    "Use this local page to exercise a hosted payment without a "
                    "network call or real card.",
                ),
                p(
                    {"style": "font-size:2rem;font-weight:700"},
                    "$" + f"{amount / 100:.2f}",
                ),
                form(
                    {"method": "post"},
                    input(
                        {
                            "type": "hidden",
                            "name": "csrfmiddlewaretoken",
                            "value": csrf_token,
                        }
                    ),
                    button(
                        {
                            "type": "submit",
                            "style": (
                                "width:100%;border:0;border-radius:.5rem;background:#fbbf24;"
                                "color:#1c1917;padding:.8rem;font-weight:700;cursor:pointer"
                            ),
                            "data-testid": "complete-payment",
                        },
                        "Complete test payment",
                    ),
                ),
            ),
        ),
    )


def payment_checkout(request: HttpRequest, session_id: str) -> HttpResponse:
    gateway = payment_gateway(request.build_absolute_uri("/"))
    session = gateway.checkout(session_id)
    if session is None or session.get("mode") != "payment":
        return HttpResponse("Unknown payment session.", status=404)
    if request.method == "POST":
        gateway.complete_payment(session_id)
        order_id = int(session["metadata"]["order_id"])
        db.Order.objects.filter(pk=order_id).update(status=db.Order.Status.PAID)
        return redirect("/account/")
    return HttpResponse(
        render_document(payment_page(session, get_token(request))),
        content_type="text/html",
    )


def static_asset(request: HttpRequest, path: str) -> HttpResponse:
    response = serve_static(request, path, document_root=STATIC_ROOT)
    if not response.streaming:
        return response
    try:
        content = response.getvalue()
    finally:
        response.close()
    headers = dict(response.headers)
    if Path(path).suffix == ".js":
        headers["Content-Type"] = "text/javascript"
    return HttpResponse(
        content,
        status=response.status_code,
        headers=headers,
    )
