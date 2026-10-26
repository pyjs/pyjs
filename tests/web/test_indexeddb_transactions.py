"""A successful request is not a successfully committed transaction."""
import pytest

from pyjs import js
from pyjs.testing.web import wait_for_event
from pyjs.web.crypto import crypto
from pyjs.web.dom import DOMException
from pyjs.web.indexeddb import (
    IDBDatabase,
    IDBTransaction,
    indexedDB,
    open_database,
    request_result,
    transaction_result,
)

pytestmark = pytest.mark.pyjs_web


@js
def create_store(database: IDBDatabase, old: int, new: int | None,
                 transaction: IDBTransaction | None) -> None:
    database.createObjectStore("records")


@js
class Operation:
    def __init__(self, transaction: IDBTransaction, mode: str):
        self.transaction = transaction
        self.mode = mode
        self.calls = 0

    async def run(self) -> int:
        self.calls += 1
        if self.mode == "empty":
            return 7
        store = self.transaction.objectStore("records")
        await request_result(store.add("first", "one"))
        if self.mode == "outlived":
            # Wait for actual auto-commit, not a timing-dependent sleep. The
            # helper must reject even though this operation eventually returns.
            await wait_for_event(self.transaction, "complete")
            return 7
        if self.mode == "raise":
            raise ValueError("operation failed after first write")
        if self.mode == "duplicate":
            await request_result(store.add("duplicate", "one"))
        if self.mode == "abort":
            self.transaction.abort()
        else:
            await request_result(store.add("second", "two"))
        return 7


@js
async def check_transaction(mode: str, succeeds: bool) -> None:
    name = "transaction-contract-" + crypto.randomUUID()
    database = await open_database(name, 1, create_store)
    try:
        transaction = database.transaction("records", "readwrite", durability="strict")
        operation = Operation(transaction, mode)
        failed = False
        message = ""
        try:
            result = await transaction_result(transaction, operation.run)
            assert result == 7
        except Exception as error:
            failed = True
            message = str(error)
        assert failed != succeeds
        assert operation.calls == 1
        if mode == "raise":
            assert message == "operation failed after first write"
        if mode == "outlived":
            assert message == "IndexedDB operation outlived its transaction"
        # A committed transaction can no longer be aborted. This assertion
        # fails if the helper resolves as soon as the last request succeeds.
        if succeeds:
            finished = False
            try:
                transaction.abort()
            except Exception:
                finished = True
            assert finished
    finally:
        database.close()
    reopened = await open_database(name, 1)
    try:
        store = reopened.transaction("records").objectStore("records")
        count = await request_result(store.count())
        expected = 1 if mode == "outlived" else (2 if succeeds and mode != "empty" else 0)
        assert count == expected
    finally:
        reopened.close()
        await request_result(indexedDB.deleteDatabase(name))


@js
async def test_result_waits_for_commit_and_survives_reopen():
    await check_transaction("success", True)


@js
async def test_empty_transaction_still_waits_for_completion():
    await check_transaction("empty", True)


@js
async def test_operation_exception_rolls_back_prior_writes():
    await check_transaction("raise", False)


@js
async def test_request_failure_rolls_back_prior_writes():
    await check_transaction("duplicate", False)


@js
async def test_abort_after_successful_request_rejects_operation_result():
    await check_transaction("abort", False)


@js
async def test_outlived_operation_reports_failure_without_claiming_rollback():
    await check_transaction("outlived", False)


@js
async def test_finished_transaction_rejects_before_empty_operation_runs():
    name = "finished-transaction-" + crypto.randomUUID()
    database = await open_database(name, 1, create_store)
    try:
        transaction = database.transaction("records", "readwrite")
        await wait_for_event(transaction, "complete")
        operation = Operation(transaction, "empty")
        failed = False
        try:
            await transaction_result(transaction, operation.run)
        except DOMException as error:
            assert error.name == "InvalidStateError"
            failed = True
        assert failed
        assert operation.calls == 0
    finally:
        database.close()
        await request_result(indexedDB.deleteDatabase(name))
