import pytest

from pyjs import js
from pyjs.javascript import Date, Uint8Array
from pyjs.testing.web import next_frame
from pyjs.web.clipboard import navigator as clipboard_navigator
from pyjs.web.crypto import crypto
from pyjs.web.dom import DOMException, document
from pyjs.web.dragdrop import DataTransfer, DragEvent
from pyjs.web.encoding import TextDecoder, TextEncoder
from pyjs.web.events import WheelEvent
from pyjs.web.files import Blob, File
from pyjs.web.indexeddb import (
    IDBDatabase,
    IDBTransaction,
    TypedIDBStore,
    indexedDB,
    open_database,
    request_result,
)
from pyjs.web.network import Response, fetch
from pyjs.web.serviceworker import caches, navigator
from pyjs.web.storage import navigator as storage_navigator
from pyjs.web.svg import SVGLineElement, SVGSVGElement
from pyjs.web.timers import (
    cancelAnimationFrame,
    clearInterval,
    clearTimeout,
    queueMicrotask,
    requestAnimationFrame,
    setInterval,
    setTimeout,
)
from pyjs.web.url import URL

pytestmark = pytest.mark.pyjs_web


@js
async def test_text_encoding_and_sha256_digest_use_native_browser_apis():
    encoder = TextEncoder()
    encoded = encoder.encode("Example ✓")
    assert len(encoded) == 11
    assert TextDecoder().decode(encoded) == "Example ✓"

    destination = Uint8Array(16)
    result = encoder.encodeInto("PyJS", destination)
    assert result.read == 4
    assert result.written == 4
    assert destination[0] == 80

    digest = Uint8Array(await crypto.subtle.digest("SHA-256", encoded))
    assert len(digest) == 32
    # hashlib.sha256("Example ✓".encode("utf-8")).digest()
    expected = [81, 131, 137, 67, 147, 241, 182, 195, 75, 52, 212, 217, 161, 51, 6, 72,
                43, 189, 181, 193, 53, 76, 216, 145, 161, 77, 117, 166, 39, 223, 154, 219]
    for index, value in enumerate(expected):
        assert digest[index] == value


@js
def test_document_visibility_api_is_available():
    assert document.visibilityState == "visible"
    assert document.hidden is False


@js
def test_dom_exception_is_catchable_as_a_browser_exception():
    caught = False
    try:
        raise DOMException("Clipboard blocked", "NotAllowedError")
    except DOMException as error:
        caught = error.name == "NotAllowedError"

    assert caught


@js
def test_date_now_uses_native_epoch_milliseconds():
    first = Date.now()
    second = Date.now()

    assert first > 1_000_000_000_000
    assert second >= first


@js
def test_date_construction_and_string_primitives_use_native_browser_apis():
    epoch = Date(0)
    current = Date()

    assert epoch.toISOString() == "1970-01-01T00:00:00.000Z"
    assert current.getMonth() >= 0
    assert current.getMonth() <= 11
    assert current.getDate() >= 1
    assert current.getDate() <= 31
    assert current.getFullYear() >= 2026

    assert "example.json".startswith("example")
    assert "example.json".endswith(".json")
    assert "a::a::a".replace("a", "note") == "note::note::note"
    assert "a::a::a".replace("a", "note", 2) == "note::note::a"
    assert "a::a::a".replace("a", "note", 0) == "a::a::a"
    assert "ab".replace("", "-", 2) == "-a-b"
    assert "😊".replace("", "-") == "-😊-"
    assert "".replace("", "value") == "value"


@js
async def test_storage_and_clipboard_are_available_on_the_browser_navigator():
    estimate = await storage_navigator.storage.estimate()

    assert estimate.quota is not None
    assert estimate.usage is not None
    assert clipboard_navigator.clipboard is not None


@js
async def test_cache_storage_round_trip_and_service_worker_container():
    cache_name = "pyjs-platform-api-" + crypto.randomUUID()
    request_url = "/pyjs-cache-test-" + crypto.randomUUID()
    cache = await caches.open(cache_name)
    await cache.put(request_url, Response("cached by Python"))

    response = await caches.match(request_url)
    if response is None:
        raise ValueError("cached response was not found")
    assert await response.text() == "cached by Python"
    assert navigator.serviceWorker is not None

    assert await caches.delete(cache_name)


@js
def create_notes_store(
    database: IDBDatabase,
    old_version: int,
    new_version: int | None,
    transaction: IDBTransaction | None,
):
    if old_version < 1:
        database.createObjectStore("notes")


@js
def require_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("expected stored text")
    return value


@js
async def test_indexeddb_supports_example_storage_operations():
    name = "pyjs-platform-api-" + crypto.randomUUID()
    database = await open_database(name, 1, create_notes_store)
    raw_write = database.transaction("notes", "readwrite").objectStore("notes")
    write = TypedIDBStore[str](raw_write)
    await write.put("First note", "note-1").value()

    raw_read = database.transaction("notes").objectStore("notes")
    read = TypedIDBStore[str](raw_read)
    value = await read.get("note-1").value(require_text)
    values = await read.getAll().value()

    assert value == "First note"
    assert len(values) == 1
    assert values[0] == "First note"

    invalid_write = database.transaction("notes", "readwrite").objectStore("notes")
    await request_result(invalid_write.put(42, "invalid-note"))
    invalid_raw_read = database.transaction("notes").objectStore("notes")
    invalid_read = TypedIDBStore[str](invalid_raw_read)

    rejected_invalid_value = False
    try:
        await invalid_read.get("invalid-note").value(require_text)
    except Exception as error:
        rejected_invalid_value = str(error) == "expected stored text"
    assert rejected_invalid_value

    database.close()
    await indexedDB.deleteDatabase(name).value()


@js
async def test_blob_file_and_object_url_round_trip():
    blob = Blob(["Example backup"], type="application/json")
    file = File(["A note"], "note.md", type="text/markdown")

    assert blob.size == 14
    assert await blob.text() == "Example backup"
    assert file.name == "note.md"
    assert await file.text() == "A note"

    url = URL.createObjectURL(blob)
    response = await fetch(url)
    assert await response.text() == "Example backup"
    URL.revokeObjectURL(url)


@js
def test_svg_wheel_pointer_and_drag_apis_are_native():
    svg = document.createElementNS("http://www.w3.org/2000/svg", "svg")
    line = document.createElementNS("http://www.w3.org/2000/svg", "line")
    svg.append(line)

    assert isinstance(svg, SVGSVGElement)
    assert isinstance(line, SVGLineElement)
    assert svg.namespaceURI == "http://www.w3.org/2000/svg"

    wheel = WheelEvent(
        "wheel",
        deltaX=4,
        deltaY=-8,
        deltaMode=WheelEvent.DOM_DELTA_PIXEL,
    )
    assert (wheel.deltaX, wheel.deltaY, wheel.deltaMode) == (4, -8, 0)

    transfer = DataTransfer()
    transfer.setData("text/plain", "note-1")
    drag = DragEvent("dragstart", clientX=12, clientY=34, dataTransfer=transfer)
    assert drag.dataTransfer is not None
    assert (drag.clientX, drag.clientY) == (12, 34)
    assert transfer.getData("text/plain") == "note-1"


@js
async def test_timers_and_animation_scheduling_can_be_cancelled():
    calls: list[str] = []
    cancelled_timeout = setTimeout(lambda: calls.append("cancelled-timeout"), 1000)
    clearTimeout(cancelled_timeout)
    cancelled_interval = setInterval(lambda: calls.append("cancelled-interval"), 1)
    clearInterval(cancelled_interval)
    cancelled_frame = requestAnimationFrame(lambda timestamp: calls.append("cancelled-frame"))
    cancelAnimationFrame(cancelled_frame)

    queueMicrotask(lambda: calls.append("microtask"))
    setTimeout(lambda: calls.append("timeout"))
    requestAnimationFrame(lambda timestamp: calls.append("frame"))
    await next_frame()
    await next_frame()

    assert "microtask" in calls
    assert "timeout" in calls
    assert "frame" in calls
    assert "cancelled-timeout" not in calls
    assert "cancelled-interval" not in calls
    assert "cancelled-frame" not in calls
