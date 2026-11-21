import pytest

from pyjs import js
from pyjs.javascript import Promise
from pyjs.web.crypto import crypto
from pyjs.web.dom import window
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
async def test_open_database_preserves_caller_bindings_and_upgrade():
    resolve = "open-capture-" + crypto.randomUUID()
    reject = 1
    upgrade = create_store
    database = await open_database(resolve, reject, upgrade)
    try:
        store = database.transaction("records", "readwrite").objectStore("records")
        assert await request_result(store.put("saved", "one")) == "one"
    finally:
        database.close()
    database = await open_database(resolve, reject)
    try:
        store = database.transaction("records").objectStore("records")
        assert await request_result(store.get("one")) == "saved"
    finally:
        database.close()
        await request_result(indexedDB.deleteDatabase(resolve))
    request = create_store
    resolve += "-request"
    database = await open_database(resolve, reject, request)
    try:
        assert database.objectStoreNames.contains("records")
    finally:
        database.close()
        await request_result(indexedDB.deleteDatabase(resolve))
    getRequest = "open-factory-" + crypto.randomUUID()
    getUpgrade = create_store
    database = await open_database(getRequest, 1, getUpgrade)
    try:
        assert database.objectStoreNames.contains("records")
    finally:
        database.close()
        await request_result(indexedDB.deleteDatabase(getRequest))


@js
def database_name(events: list[str]) -> str:
    events.append("name")
    return "open-order-" + crypto.randomUUID()


@js
def database_version(events: list[str]) -> int:
    events.append("version")
    return 1


@js
def database_upgrade(events: list[str]) -> callable:
    events.append("upgrade")
    return create_store


@js
async def test_open_arguments_evaluate_once_before_returning_the_promise():
    events: list[str] = []
    pending = open_database(database_name(events), database_version(events), database_upgrade(events))
    assert events == ["name", "version", "upgrade"]
    database = await pending
    name = database.name
    try:
        assert database.objectStoreNames.contains("records")
    finally:
        database.close()
        await request_result(indexedDB.deleteDatabase(name))


@js
def invalid_database_name() -> str:
    raise ValueError("Name lookup failed")


@js
async def test_open_argument_errors_raise_without_evaluating_later_arguments():
    events: list[str] = []
    rejected = False
    try:
        open_database(invalid_database_name(), database_version(events), database_upgrade(events))
    except ValueError as error:
        assert str(error) == "Name lookup failed"
        rejected = True
    assert rejected
    assert len(events) == 0


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
        validate: callable | None = None
        assert await store.get("one").value(validate) == "saved"
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
async def test_request_argument_errors_raise_before_returning_a_promise():
    rejected = False
    try:
        request_result(missing_request())
    except ValueError as error:
        assert str(error) == "Request creation failed"
        rejected = True
    assert rejected


@js
async def test_awaited_arguments_use_normal_function_call_semantics():
    name = "awaited-request-" + crypto.randomUUID()
    database = await open_database(await Promise.resolve(name), 1, create_store)
    try:
        store = database.transaction("records", "readwrite").objectStore("records")
        assert await request_result(await Promise.resolve(store.put("saved", "one"))) == "one"
        assert await request_result(store.get("one")) == "saved"
    finally:
        database.close()
        await request_result(indexedDB.deleteDatabase(name))


@js
def mark_after_validation(events: list[str], value: object) -> object:
    window.queueMicrotask(lambda: window.queueMicrotask(lambda: events.append("later")))
    return value


@js
async def test_request_resolution_does_not_add_an_await_boundary():
    name = "request-timing-" + crypto.randomUUID()
    database = await open_database(name, 1, create_store)
    try:
        store = database.transaction("records", "readwrite").objectStore("records")
        request = store.put("saved", "one")
        events: list[str] = []
        pending = request.value(lambda value: mark_after_validation(events, value))
        assert await pending == "one"
        assert len(events) == 0
        assert await request_result(store.get("one")) == "saved"
        assert events == ["later"]
    finally:
        database.close()
        await request_result(indexedDB.deleteDatabase(name))


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
