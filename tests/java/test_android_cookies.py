from typing import cast

import pytest

from pyjs import jvm
from pyjs.java import i32
from pyjs.java.collections import JavaList, JavaMap
from pyjs.java.errors import IllegalArgumentException
from pyjs.java.net import URI, CookieManager, HttpCookie

pytestmark = pytest.mark.pyjs_android_jvm


@jvm.native("java/util/Collections", name="emptyMap")
def empty_headers() -> JavaMap: ...


def cookie_header(manager: CookieManager, url: str) -> str:
    raw = manager.get(URI(url), empty_headers()).get("Cookie")
    if raw is None:
        return ""
    values = cast(JavaList, raw)
    parts: list[str] = []
    for index in range(int(values.size())):
        parts.append(cast(str, values.get(i32(index))))
    return "; ".join(parts)


def test_cookie_attributes_and_store_replacement() -> None:
    cookie = HttpCookie("session", "first")
    assert cookie.getName() == "session" and cookie.getValue() == "first"
    assert cookie.getDomain() is None and cookie.getPath() is None
    assert cookie.getPortlist() is None and cookie.getMaxAge() == -1
    assert not cookie.hasExpired() and not cookie.getSecure()
    assert not cookie.isHttpOnly() and not cookie.getDiscard()
    assert cookie.getVersion() == 1
    cookie.setValue("second")
    cookie.setDomain("EXAMPLE.TEST")
    cookie.setPath("/api")
    cookie.setPortlist("443")
    cookie.setSecure(True)
    cookie.setHttpOnly(True)
    cookie.setDiscard(True)
    cookie.setVersion(i32(0))
    cookie.setMaxAge(4_294_967_296)
    assert cookie.getValue() == "second" and cookie.getDomain() == "example.test"
    assert cookie.getPath() == "/api" and cookie.getPortlist() == "443"
    assert cookie.getSecure() and cookie.isHttpOnly() and cookie.getDiscard()
    assert cookie.getVersion() == 0 and cookie.getMaxAge() == 4_294_967_296
    assert not cookie.hasExpired()
    manager = CookieManager()
    store = manager.getCookieStore()
    store.add(URI("https://example.test/api"), cookie)
    assert store.getCookies().size() == 1
    replacement = HttpCookie("session", "replacement")
    replacement.setDomain("example.test")
    replacement.setPath("/api")
    store.add(URI("https://example.test/api"), replacement)
    assert store.getCookies().size() == 1
    actual = cast(HttpCookie, store.getCookies().get(i32(0)))
    assert actual.getValue() == "replacement"
    actual.setDomain(None)
    actual.setPath(None)
    actual.setPortlist(None)
    assert actual.getDomain() is None and actual.getPath() is None
    assert actual.getPortlist() is None
    assert store.removeAll()
    assert store.getCookies().size() == 0


def test_restored_cookies_follow_native_request_constraints() -> None:
    manager = CookieManager()
    cookie = HttpCookie("session", "restored")
    cookie.setDomain("example.test")
    cookie.setPath("/api/")
    cookie.setPortlist("443")
    cookie.setSecure(True)
    cookie.setHttpOnly(True)
    cookie.setVersion(i32(0))
    cookie.setMaxAge(60)
    manager.getCookieStore().add(URI("https://example.test/api/"), cookie)
    assert "session=restored" in cookie_header(manager, "https://example.test/api/notes")
    for url in ["https://example.test/other", "http://example.test/api/notes",
                "https://example.test:444/api/notes", "https://other.test/api/notes"]:
        assert "session=restored" not in cookie_header(manager, url), url
    assert cookie_header(CookieManager(), "https://example.test/api/notes") == ""
    cookie.setMaxAge(0)
    assert cookie.hasExpired()
    assert "session=restored" not in cookie_header(manager, "https://example.test/api/notes")
    assert manager.getCookieStore().getCookies().size() == 0


def test_invalid_native_cookie_names_and_versions_are_catchable() -> None:
    for name in ["", "invalid name", "$reserved"]:
        rejected = False
        try:
            HttpCookie(name, "value")
        except IllegalArgumentException:
            rejected = True
        assert rejected, name
    cookie = HttpCookie("valid", "value")
    rejected = False
    try:
        cookie.setVersion(i32(2))
    except IllegalArgumentException:
        rejected = True
    assert rejected


def test_restoring_cookie_version_preserves_request_header_format() -> None:
    original = HttpCookie("session", "saved")
    original.setVersion(i32(0))
    original.setPath("/")
    restored = HttpCookie(original.getName(), original.getValue())
    restored.setPath(original.getPath())
    manager = CookieManager()
    manager.getCookieStore().add(URI("https://example.test/"), restored)
    assert 'session="saved"' in cookie_header(manager, "https://example.test/notes")
    restored.setVersion(original.getVersion())
    assert cookie_header(manager, "https://example.test/notes") == "session=saved"
