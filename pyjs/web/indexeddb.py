from collections.abc import Awaitable, Callable
from typing import cast

from pyjs import js
from pyjs.javascript import Promise
from pyjs.web.dom import DOMException
from pyjs.web.events import Event, EventTarget
from pyjs.web.html import DOMStringList


@js
def _resolve_request[T](
    request: IDBRequest[T],
    validator: Callable[[T], T] | None,
    resolve: Callable[[T | Awaitable[T]], None],
    reject: Callable[[object], None],
) -> None:
    if validator is None:
        resolve(request.result)
    else:
        try:
            resolve(validator(request.result))
        except Exception as error:
            reject(error)


@js
def _listen_request[T](
    request: IDBRequest[T],
    validator: Callable[[T], T] | None,
    resolve: Callable[[T | Awaitable[T]], None],
    reject: Callable[[object], None],
) -> None:
    request.addEventListener(
        "success",
        lambda event: _resolve_request(request, validator, resolve, reject),
        once=True,
    )
    request.addEventListener("error", lambda event: reject(request.error), once=True)


@js
def request_result[T](
    request: IDBRequest[T], validator: Callable[[T], T] | None = None
) -> Promise[T]:
    """Listen immediately; argument evaluation follows ordinary Python rules."""
    return Promise[T](
        lambda resolve, reject: _listen_request(request, validator, resolve, reject)
    )


def _request_value(self, _arg_strs, _keyword_strs, request_result, **kwargs):
    validator = _arg_strs[0] if _arg_strs else _keyword_strs.get("validator", "null")
    return f"{request_result}({self}, {{validator: {validator}}})"


@js.native
class IDBCursor:
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBCursor

    Browser support: Chrome 24, Safari 8"""

    def __init__(self):
        self.direction: str = ""
        self.key: object = None
        self.primaryKey: object = None
        self.request: IDBRequest[object] = None
        self.source: IDBObjectStore | IDBIndex = None

    def advance(self, count: int) -> None: ...

    @js.inline("{self}.continue({_args_joined})")
    def continue_(self, key: object | None = None) -> None: ...

    def continuePrimaryKey(self, key: object, primaryKey: object) -> None: ...

    def delete(self) -> IDBRequest[None]: ...

    def update(self, value: object) -> IDBRequest[object]: ...


@js.native
class IDBDatabase(EventTarget):
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBDatabase

    Browser support: Chrome 24, Safari 8"""

    def __init__(self):
        super().__init__()
        self.name: str = ""
        self.objectStoreNames: DOMStringList = None
        self.onabort: callable = None
        self.onclose: callable = None
        self.onerror: callable = None
        self.onversionchange: callable = None
        self.version: int = 0

    def close(self) -> None: ...

    def createObjectStore(
        self,
        name: str,
        *,
        keyPath: str | list[str] | None = None,
        autoIncrement: bool = False,
    ) -> IDBObjectStore: ...

    def deleteObjectStore(self, name: str) -> None: ...

    def transaction(
        self,
        storeNames: str | list[str],
        mode: str = "readonly",
        *,
        durability: str = "default",
    ) -> IDBTransaction: ...


@js.dictionary
class IDBDatabaseInfo:
    """WebIDL source: @webref/idl/IndexedDB.idl"""

    def __init__(self, name: str | None = None, version: int | None = None):
        self.name = name
        self.version = version


@js.native
class IDBFactory:
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBFactory

    Browser support: Chrome 24, Safari 8"""

    def cmp(self, first: object, second: object) -> int: ...

    async def databases(self) -> list[IDBDatabaseInfo]: ...

    def deleteDatabase(self, name: str) -> IDBOpenDBRequest[None]: ...

    def open(
        self, name: str, version: int | None = None
    ) -> IDBOpenDBRequest[IDBDatabase]: ...


indexedDB = IDBFactory()
js.native(indexedDB)


@js.dictionary
class IDBGetAllOptions:
    """WebIDL source: @webref/idl/IndexedDB.idl"""

    def __init__(
        self,
        count: int | None = None,
        direction: str = "next",
        query: object | None = None,
    ):
        self.count = count
        self.direction = direction
        self.query = query


@js.native
class IDBIndex:
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBIndex

    Browser support: Chrome 24, Safari 8"""

    def __init__(self):
        self.keyPath: object = None
        self.multiEntry: bool = False
        self.name: str = ""
        self.objectStore: IDBObjectStore = None
        self.unique: bool = False

    def count(self, query: object | None = None) -> IDBRequest[int]: ...

    def get(self, query: object) -> IDBRequest[object]: ...

    def getAll(
        self, queryOrOptions: object | None = None, count: int | None = None
    ) -> IDBRequest[list[object]]: ...

    def getAllKeys(
        self, queryOrOptions: object | None = None, count: int | None = None
    ) -> IDBRequest[list[object]]: ...

    def getAllRecords(
        self,
        *,
        query: object | None = None,
        count: int | None = None,
        direction: str = "next",
    ) -> IDBRequest[list[IDBRecord]]: ...

    def getKey(self, query: object) -> IDBRequest[object]: ...

    def openCursor(
        self, query: object | None = None, direction: str = "next"
    ) -> IDBRequest[IDBCursorWithValue | None]: ...

    def openKeyCursor(
        self, query: object | None = None, direction: str = "next"
    ) -> IDBRequest[IDBCursor | None]: ...


@js.dictionary
class IDBIndexParameters:
    """WebIDL source: @webref/idl/IndexedDB.idl"""

    def __init__(self, multiEntry: bool = False, unique: bool = False):
        self.multiEntry = multiEntry
        self.unique = unique


@js.native
class IDBKeyRange:
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBKeyRange

    Browser support: Chrome 24, Safari 8"""

    def __init__(self):
        self.lower: object = None
        self.lowerOpen: bool = False
        self.upper: object = None
        self.upperOpen: bool = False

    @staticmethod
    def bound(
        lower: object, upper: object, lowerOpen: bool = False, upperOpen: bool = False
    ) -> IDBKeyRange: ...

    def includes(self, key: object) -> bool: ...

    @staticmethod
    def lowerBound(lower: object, open: bool = False) -> IDBKeyRange: ...

    @staticmethod
    def only(value: object) -> IDBKeyRange: ...

    @staticmethod
    def upperBound(upper: object, open: bool = False) -> IDBKeyRange: ...


@js.native
class IDBObjectStore:
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBObjectStore

    Browser support: Chrome 24, Safari 8"""

    def __init__(self):
        self.autoIncrement: bool = False
        self.indexNames: DOMStringList = None
        self.keyPath: object = None
        self.name: str = ""
        self.transaction: IDBTransaction = None

    def add(self, value: object, key: object | None = None) -> IDBRequest[object]: ...

    def clear(self) -> IDBRequest[None]: ...

    def count(self, query: object | None = None) -> IDBRequest[int]: ...

    def createIndex(
        self,
        name: str,
        keyPath: str | list[str],
        *,
        unique: bool = False,
        multiEntry: bool = False,
    ) -> IDBIndex: ...

    def delete(self, query: object) -> IDBRequest[None]: ...

    def deleteIndex(self, name: str) -> None: ...

    def get(self, query: object) -> IDBRequest[object]: ...

    def getAll(
        self, queryOrOptions: object | None = None, count: int | None = None
    ) -> IDBRequest[list[object]]: ...

    def getAllKeys(
        self, queryOrOptions: object | None = None, count: int | None = None
    ) -> IDBRequest[list[object]]: ...

    def getAllRecords(
        self,
        *,
        query: object | None = None,
        count: int | None = None,
        direction: str = "next",
    ) -> IDBRequest[list[IDBRecord]]: ...

    def getKey(self, query: object) -> IDBRequest[object]: ...

    def index(self, name: str) -> IDBIndex: ...

    def openCursor(
        self, query: object | None = None, direction: str = "next"
    ) -> IDBRequest[IDBCursorWithValue | None]: ...

    def openKeyCursor(
        self, query: object | None = None, direction: str = "next"
    ) -> IDBRequest[IDBCursor | None]: ...

    def put(self, value: object, key: object | None = None) -> IDBRequest[object]: ...


@js.dictionary
class IDBObjectStoreParameters:
    """WebIDL source: @webref/idl/IndexedDB.idl"""

    def __init__(
        self, autoIncrement: bool = False, keyPath: str | list[str] | None = None
    ):
        self.autoIncrement = autoIncrement
        self.keyPath = keyPath


@js.native
class IDBRecord:
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBRecord

    Browser support: Chrome 141, Safari preview"""

    def __init__(self):
        self.key: object = None
        self.primaryKey: object = None
        self.value: object = None


@js.native
class IDBRequest[T](EventTarget):
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBRequest

    Browser support: Chrome 24, Safari 8"""

    def __init__(self):
        super().__init__()
        self.error: DOMException | None = None
        self.onerror: callable = None
        self.onsuccess: callable = None
        self.readyState: str = ""
        self.result: T = None
        self.source: IDBObjectStore | IDBIndex | IDBCursor | None = None
        self.transaction: IDBTransaction | None = None

    @js.inline(_request_value, request_result=request_result)
    async def value(self, validator: callable | None = None) -> T:
        if validator is None:
            return self.result
        return validator(self.result)


@js.native
class TypedIDBStore[T]:
    @js.inline("{store}")
    def __init__(self, store: IDBObjectStore):
        self.store = store

    @js.inline("{self}.add({_args_joined})")
    def add(self, value: T, key: object | None = None) -> IDBRequest[object]:
        return self.store.add(value, key)

    @js.inline("{self}.clear()")
    def clear(self) -> IDBRequest[None]:
        return self.store.clear()

    @js.inline("{self}.count({_args_joined})")
    def count(self, query: object | None = None) -> IDBRequest[int]:
        return self.store.count(query)

    @js.inline("{self}.delete({query})")
    def delete(self, query: object) -> IDBRequest[None]:
        return self.store.delete(query)

    @js.inline("{self}.get({query})")
    def get(self, query: object) -> IDBRequest[T | None]:
        return self.store.get(query)

    @js.inline("{self}.getAll({_args_joined})")
    def getAll(
        self, queryOrOptions: object | None = None, count: int | None = None
    ) -> IDBRequest[list[T]]:
        return self.store.getAll(queryOrOptions, count)

    @js.inline("{self}.put({_args_joined})")
    def put(self, value: T, key: object | None = None) -> IDBRequest[object]:
        return self.store.put(value, key)


@js.native
class IDBTransaction(EventTarget):
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBTransaction

    Browser support: Chrome 24, Safari 8"""

    def __init__(self):
        super().__init__()
        self.db: IDBDatabase = None
        self.durability: str = ""
        self.error: DOMException | None = None
        self.mode: str = ""
        self.objectStoreNames: DOMStringList = None
        self.onabort: callable = None
        self.oncomplete: callable = None
        self.onerror: callable = None

    def abort(self) -> None: ...

    def commit(self) -> None: ...

    def objectStore(self, name: str) -> IDBObjectStore: ...


@js.dictionary
class IDBTransactionOptions:
    """WebIDL source: @webref/idl/IndexedDB.idl"""

    def __init__(self, durability: str = "default"):
        self.durability = durability


@js.native
class IDBVersionChangeEvent(Event):
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBVersionChangeEvent

    Browser support: Chrome 24, Safari 8"""

    def __init__(self, type: str, *, oldVersion: int = 0, newVersion: int | None = None):
        super().__init__()
        self.newVersion: int | None = newVersion
        self.oldVersion: int = oldVersion


@js.dictionary
class IDBVersionChangeEventInit:
    """WebIDL source: @webref/idl/IndexedDB.idl"""

    def __init__(self, newVersion: int | None = None, oldVersion: int = 0):
        self.newVersion = newVersion
        self.oldVersion = oldVersion


@js.native
class IDBOpenDBRequest[T](IDBRequest[T]):
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBOpenDBRequest

    Browser support: Chrome 24, Safari 8"""

    def __init__(self):
        super().__init__()
        self.onblocked: callable = None
        self.onupgradeneeded: callable = None


@js
class _TransactionResult[T]:
    def __init__(self, transaction: IDBTransaction):
        self.transaction = transaction
        self.pending = Promise[T].withResolvers()
        self.result: T | None = None
        self.ready = False
        self.settled = False
        self.complete_listener = lambda event: self.complete()
        self.abort_listener = lambda event: self.abort()

    def start(self, operation: Callable[[], Awaitable[T]]) -> None:
        """Probe finished state without issuing a request.

        An empty versionchange transaction may have no stores yet; its
        NotFoundError does not mean the transaction has finished.
        """
        try:
            names = self.transaction.objectStoreNames
            name = names.item(0) or ""
            try:
                self.transaction.objectStore(name)
            except DOMException as error:
                if error.name != "NotFoundError":
                    raise
            self.transaction.addEventListener(
                "complete", self.complete_listener, once=True
            )
            self.transaction.addEventListener("abort", self.abort_listener, once=True)
            Promise[T].resolve(operation()).then(self.succeed, self.fail)
        except Exception as error:
            self.fail(error)

    def dispose(self) -> bool:
        if self.settled:
            return False
        self.settled = True
        self.transaction.removeEventListener("complete", self.complete_listener)
        self.transaction.removeEventListener("abort", self.abort_listener)
        return True

    def succeed(self, result: T) -> None:
        self.result = result
        self.ready = True

    def complete(self) -> None:
        if self.dispose():
            if self.ready:
                self.pending.resolve(cast(T, self.result))
            else:
                self.pending.reject(
                    RuntimeError("IndexedDB operation outlived its transaction")
                )

    def abort(self) -> None:
        if self.dispose():
            error = self.transaction.error
            if error is None:
                self.pending.reject(RuntimeError("IndexedDB transaction aborted"))
            else:
                self.pending.reject(error)

    def fail(self, error: object) -> None:
        try:
            self.transaction.abort()
        except Exception:
            pass
        if self.dispose():
            self.pending.reject(error)


@js
def _notify_upgrade(
    request: IDBRequest[IDBDatabase], upgrade: callable, event: IDBVersionChangeEvent
) -> None:
    upgrade(request.result, event.oldVersion, event.newVersion, request.transaction)


@js
def _start_open(
    name: str,
    version: int,
    upgrade: callable | None,
    resolve: Callable[[IDBDatabase | Awaitable[IDBDatabase]], None],
    reject: Callable[[object], None],
) -> None:
    request = indexedDB.open(name, version)
    if upgrade is not None:
        request.addEventListener(
            "upgradeneeded",
            lambda event: _notify_upgrade(
                request, upgrade, cast(IDBVersionChangeEvent, event)
            ),
            once=True,
        )
    _listen_request(request, None, resolve, reject)


@js
def open_database(
    name: str, version: int, upgrade: callable | None = None
) -> Promise[IDBDatabase]:
    return Promise[IDBDatabase](
        lambda resolve, reject: _start_open(name, version, upgrade, resolve, reject)
    )


@js
def request_values(request: IDBRequest[list[object]]) -> Promise[list[object]]:
    return request_result(request)


@js.native
class IDBCursorWithValue(IDBCursor):
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBCursorWithValue

    Browser support: Chrome 24, Safari 8"""

    def __init__(self):
        super().__init__()
        self.value: object = None


@js
def transaction_result[T](
    transaction: IDBTransaction, operation: Callable[[], Awaitable[T]]
) -> Promise[T]:
    """Run an operation and await transaction completion, aborting on failure.

    Call immediately after creating the transaction, before yielding. The
    operation may await requests in this transaction, but not timers, network
    I/O, or other work that lets IndexedDB auto-commit. Listeners are installed
    before the operation runs. Request success alone is not commit success.
    An already-finished transaction rejects without invoking the operation.

    Requires native Promise.withResolvers (Chrome 119 or Safari 17.4+).
    """
    result = _TransactionResult[T](transaction)
    result.start(operation)
    return result.pending.promise
