"""Isolated Django endpoint for compiled JVM transport tests."""

from wsgiref.simple_server import WSGIRequestHandler, make_server

import django
from django.conf import settings
from django.core.wsgi import get_wsgi_application

from tests.java.api_transport_contract import EchoAPI


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def main():
    settings.configure(
        SECRET_KEY="isolated-transport-test",
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=["127.0.0.1"],
        MIDDLEWARE=["django.middleware.csrf.CsrfViewMiddleware"],
        CSRF_FAILURE_VIEW="pyjs.server.django.csrf_failure",
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    )
    django.setup()
    global urlpatterns
    urlpatterns = EchoAPI().urls
    with make_server("127.0.0.1", 0, get_wsgi_application(), handler_class=QuietHandler) as server:
        print(f"http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
