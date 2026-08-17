import os
import shutil
from pathlib import Path

import django
import uvicorn
from django.conf import settings
from django.core.asgi import get_asgi_application
from django.core.management import call_command
from django.db import connections


def main():
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE",
        "pyjs_examples.issue_tracker.settings",
    )
    django.setup()

    from pyjs_examples.issue_tracker.server import STATIC_ROOT, application

    database_path = Path(settings.DATABASES["default"]["NAME"])
    database_path.unlink(missing_ok=True)
    call_command("migrate", interactive=False, verbosity=0)
    call_command("loaddata", "issue_tracker", verbosity=0)
    application.build(STATIC_ROOT / "issue_tracker")

    host = "127.0.0.1"
    port = int(os.environ.get("PYJS_PORT", "8000"))
    url = f"http://{host}:{port}/"
    print(f"Serving the PyJS issue tracker at {url}")

    try:
        uvicorn.run(
            get_asgi_application(),
            host=host,
            port=port,
            log_level="warning",
        )
    finally:
        connections.close_all()
        database_path.unlink(missing_ok=True)
        shutil.rmtree(STATIC_ROOT, ignore_errors=True)


main()
