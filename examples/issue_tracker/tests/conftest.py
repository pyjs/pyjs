import os
from pathlib import Path

import django
import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import connections

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "pyjs_examples.issue_tracker.settings",
)
django.setup()

call_command("migrate", interactive=False, verbosity=0)


@pytest.fixture(autouse=True)
def issue_tracker_database():
    call_command("flush", interactive=False, verbosity=0)
    call_command("loaddata", "issue_tracker", verbosity=0)


def pytest_sessionfinish(session, exitstatus):
    connections.close_all()
    Path(settings.DATABASES["default"]["NAME"]).unlink(missing_ok=True)
