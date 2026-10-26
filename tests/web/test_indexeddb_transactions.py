"""A successful request is not a successfully committed transaction."""
import pytest

from pyjs import js
from pyjs.web.crypto import crypto
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
        assert count == (2 if succeeds and mode != "empty" else 0)
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
