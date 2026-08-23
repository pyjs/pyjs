import os
import shutil
from pathlib import Path


def main():
    try:
        import django
        import uvicorn
        from django.conf import settings
        from django.core.asgi import get_asgi_application
        from django.core.management import call_command
        from django.db import connections

        os.environ.setdefault(
            "DJANGO_SETTINGS_MODULE",
            "pyjs_examples.store.settings",
        )
        django.setup()

        from pyjs_examples.store.server import STATIC_ROOT, application
    except ModuleNotFoundError as error:
        if error.name.split(".", 1)[0] in {
            "django",
            "pydantic",
            "pyjs_extras",
            "uvicorn",
        }:
            raise SystemExit(
                "The Store example needs its optional server dependencies. "
                'Install them with: python -m pip install "pyjs-examples[store]"'
            ) from None
        raise

    database_path = Path(settings.DATABASES["default"]["NAME"])
    database_path.unlink(missing_ok=True)
    call_command("migrate", interactive=False, run_syncdb=True, verbosity=0)
    call_command("loaddata", "store", verbosity=0)
    test_static_root = os.environ.get("PYJS_STORE_TEST_STATIC_ROOT")
    build_marker = STATIC_ROOT / ".build-complete"
    if test_static_root is None or not build_marker.is_file():
        application.build(STATIC_ROOT / "store")
        if test_static_root is not None:
            build_marker.write_text("complete\n", encoding="utf-8")
        print(application.build_stats)
    else:
        print(f"Reusing the store test build in {STATIC_ROOT}")

    host = "127.0.0.1"
    port = int(os.environ.get("PYJS_PORT", "8000"))
    print(f"Serving the PyJS store at http://{host}:{port}/")
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
        if test_static_root is None:
            shutil.rmtree(STATIC_ROOT, ignore_errors=True)


if __name__ == "__main__":
    main()
