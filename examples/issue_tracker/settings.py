import os
import tempfile
from pathlib import Path

SECRET_KEY = "pyjs-issue-tracker"
DEBUG = True
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "testserver")
ROOT_URLCONF = "pyjs_examples.issue_tracker.urls"
INSTALLED_APPS = ("pyjs_examples.issue_tracker",)
MIDDLEWARE = ()
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
TIME_ZONE = "UTC"
USE_TZ = True

default_database = Path(tempfile.gettempdir()) / f"pyjs-issue-tracker-{os.getpid()}.sqlite3"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("PYJS_ISSUE_TRACKER_DB", default_database),
    }
}
