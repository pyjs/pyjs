import os
import tempfile
from pathlib import Path

SECRET_KEY = "pyjs-store"
DEBUG = True
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "testserver")
ROOT_URLCONF = "pyjs_examples.store.urls"
INSTALLED_APPS = ("pyjs_examples.store",)
MIDDLEWARE = ("django.middleware.csrf.CsrfViewMiddleware",)
CSRF_FAILURE_VIEW = "pyjs.server.django.csrf_failure"
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
TIME_ZONE = "UTC"
USE_TZ = True

default_database = Path(tempfile.gettempdir()) / f"pyjs-store-{os.getpid()}.sqlite3"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("PYJS_STORE_DB", default_database),
    }
}
