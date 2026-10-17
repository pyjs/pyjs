import django
from django.conf import settings


def pytest_configure():
    if not settings.configured:
        settings.configure(
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": ":memory:",
                }
            },
            INSTALLED_APPS=("tests.django.apps.JSONAPITestConfig",),
            SECRET_KEY="pyjs-django-tests",
            STATIC_URL="/assets/",
        )
    django.setup()
