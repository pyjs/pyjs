from django.urls import include, path, re_path

from .api import api
from .server import (
    account,
    index,
    inventory,
    payment_checkout,
    reviews,
    static_asset,
    story,
    visitors,
)

urlpatterns = [
    path("", index),
    path("story/", story),
    path("account/", account),
    path("account/inventory/", inventory),
    path("account/reviews/", reviews),
    path("account/visitors/", visitors),
    path(
        "stripe/mock/checkout/<str:session_id>/",
        payment_checkout,
    ),
    path("api/", include(api.urls)),
    re_path(r"^static/(?P<path>.*)$", static_asset),
]
