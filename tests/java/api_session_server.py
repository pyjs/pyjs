"""Isolated session/CSRF fixture using Django's auth views and database."""

import sys
from wsgiref.simple_server import make_server

import django
from django.conf import settings
from django.core.wsgi import get_wsgi_application

from tests.java.api_session_contract import AuthenticatedAPI
from tests.java.api_transport_server import QuietHandler


def main():
    settings.configure(
        SECRET_KEY="isolated-session-test",
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=["127.0.0.1"],
        INSTALLED_APPS=["django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions"],
        MIDDLEWARE=["django.contrib.sessions.middleware.SessionMiddleware",
                    "django.middleware.csrf.CsrfViewMiddleware",
                    "django.contrib.auth.middleware.AuthenticationMiddleware"],
        CSRF_FAILURE_VIEW="pyjs.server.django.csrf_failure",
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": sys.argv[1]}},
        LOGIN_REDIRECT_URL="/",
        LOGOUT_REDIRECT_URL="/",
        TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates", "OPTIONS": {
            "loaders": [("django.template.loaders.locmem.Loader", {"login.html": "{{ form.errors }}"})],
        }}],
    )
    django.setup()
    from django.contrib.auth import get_user_model
    from django.contrib.auth.views import LoginView, LogoutView
    from django.core.management import call_command
    from django.http import HttpResponse
    from django.urls import include, path
    from django.views.decorators.csrf import ensure_csrf_cookie

    call_command("migrate", verbosity=0, interactive=False)
    get_user_model().objects.create_user("test-user", password="test-pass-雪")
    global urlpatterns
    urlpatterns = [
        path("bootstrap/", ensure_csrf_cookie(lambda request: HttpResponse("ready"))),
        path("login/", LoginView.as_view(template_name="login.html")),
        path("logout/", LogoutView.as_view()),
        path("api/", include(AuthenticatedAPI().urls)),
    ]
    with make_server("127.0.0.1", 0, get_wsgi_application(), handler_class=QuietHandler) as server:
        print(f"http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
