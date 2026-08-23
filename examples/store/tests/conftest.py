import asyncio
import os
from pathlib import Path

import django
import pytest
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management import call_command
from django.db import connections

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pyjs_examples.store.settings")
django.setup()
call_command("migrate", interactive=False, run_syncdb=True, verbosity=0)


@pytest.fixture(autouse=True)
def store_database():
    from pyjs_examples.store.api import PAYMENT_STATE

    PAYMENT_STATE.clear()
    call_command("flush", interactive=False, verbosity=0)
    call_command("loaddata", "store", verbosity=0)
    yield
    asyncio.run(sync_to_async(connections.close_all)())
    connections.close_all()


def pytest_sessionfinish(session, exitstatus):
    connections.close_all()
    database_name = settings.DATABASES["default"]["NAME"]
    if database_name != ":memory:":
        Path(database_name).unlink(missing_ok=True)
