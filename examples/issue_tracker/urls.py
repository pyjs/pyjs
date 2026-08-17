from django.urls import include, path, re_path

from .api import api
from .server import index, static_asset

urlpatterns = [
    path("", index),
    path("api/", include(api.urls)),
    re_path(r"^static/(?P<path>.*)$", static_asset),
]
