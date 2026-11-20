import pytest

from pyjs import js
from pyjs.web.crypto import crypto
from pyjs.web.indexeddb import (
    IDBDatabase,
    IDBObjectStore,
    IDBRequest,
    IDBTransaction,
    indexedDB,
    open_database,
    request_result,
    request_values,
)

pytestmark = pytest.mark.pyjs_web


@js
def create_store(database: IDBDatabase, old: int, new: int | None,
                 transaction: IDBTransaction | None) -> None:
    database.createObjectStore("records")


@js
async def test_request_helpers_do_not_capture_caller_variable_names():
    name = "request-capture-" + crypto.randomUUID()
    database = await open_database(name, 1, create_store)
    try:
        store = database.transaction("records", "readwrite").objectStore("records")
        request = store.put("saved", "one")
        assert await request_result(request) == "one"
        resolve = store.get("one")
        assert await request_result(resolve) == "saved"
        reject = store.get("one")
        assert await request_result(reject) == "saved"
        getRequest = store.get("one")
        assert await request_result(getRequest) == "saved"
        request = store.get("one")
        assert await request.value() == "saved"
    finally:
        database.close()
        await request_result(indexedDB.deleteDatabase(name))


@js
async def test_request_values_captures_the_callers_request():
    name = "request-values-" + crypto.randomUUID()
    database = await open_database(name, 1, create_store)
    try:
        store = database.transaction("records", "readwrite").objectStore("records")
        await request_result(store.put("saved", "one"))
        request = store.getAll()
        values = await request_values(request)
        assert len(values) == 1 and values[0] == "saved"
    finally:
        database.close()
        await request_result(indexedDB.deleteDatabase(name))


@js
def missing_request() -> IDBRequest[object]:
    raise ValueError("Request creation failed")


@js
async def test_request_creation_errors_still_reject_the_returned_promise():
    pending = request_result(missing_request())
    rejected = False
    try:
        await pending
    except ValueError as error:
        assert str(error) == "Request creation failed"
        rejected = True
    assert rejected


@js
def upper(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a string")
    return value.upper()


@js
def next_request(store: IDBObjectStore, events: list[str]) -> IDBRequest[object]:
    events.append("request")
    return store.get("one")


@js
def next_validator(events: list[str]) -> callable:
    events.append("validator")
    return upper


@js
async def test_request_validator_capture_order_and_failure():
    name = "request-validator-" + crypto.randomUUID()
    database = await open_database(name, 1, create_store)
    try:
        store = database.transaction("records", "readwrite").objectStore("records")
        await request_result(store.put("saved", "one"))
        validate = upper
        assert await store.get("one").value(validate) == "SAVED"
        getValidator = upper
        assert await store.get("one").value(getValidator) == "SAVED"
        events: list[str] = []
        assert await next_request(store, events).value(next_validator(events)) == "SAVED"
        assert events == ["request", "validator"]
        rejected = False
        try:
            await store.get("missing").value(validate)
        except ValueError as error:
            assert str(error) == "Expected a string"
            rejected = True
        assert rejected
    finally:
        database.close()
        await request_result(indexedDB.deleteDatabase(name))
