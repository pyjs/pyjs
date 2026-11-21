from collections.abc import Awaitable, Callable
from typing import cast

from pyjs import js
from pyjs.web.dom import DOMException
from pyjs.web.events import Event, EventTarget
from pyjs.web.html import DOMStringList


@js.inline("new Promise({executor})")
def _promise(executor: Callable[[callable, callable], None]) -> Awaitable[object]: ...


@js
def _resolve_request(
    request: IDBRequest[object],
    validator: callable | None,
    resolve: callable,
    reject: callable,
) -> None:
    if validator is None:
        resolve(request.result)
    else:
        try:
            resolve(validator(request.result))
        except Exception as error:
            reject(error)


@js
def _listen_request(
    request: IDBRequest[object],
    validator: callable | None,
    resolve: callable,
    reject: callable,
) -> None:
    request.addEventListener(
        "success",
        lambda event: _resolve_request(request, validator, resolve, reject),
        once=True,
    )
    request.addEventListener("error", lambda event: reject(request.error), once=True)


@js
def _start_request(
    get_request: Callable[[], IDBRequest[object]],
    get_validator: Callable[[], callable | None],
    resolve: callable,
    reject: callable,
) -> None:
    request = get_request()
    validator = get_validator()
    _listen_request(request, validator, resolve, reject)


@js
def _request_promise(
    get_request: Callable[[], IDBRequest[object]],
    get_validator: Callable[[], callable | None],
) -> Awaitable[object]:
    return _promise(
        lambda resolve, reject: _start_request(
            get_request, get_validator, resolve, reject
        )
    )


def _rewrite_request_result(_arg_strs, request_promise, self=None, **kwargs):
    """Evaluate caller expressions synchronously inside the rejecting executor."""
    if self is not None:
        expression = self
        validator = _arg_strs[0] if _arg_strs else "null"
    else:
        expression = _arg_strs[0]
        validator = _arg_strs[1] if len(_arg_strs) > 1 else "null"
    return f"{request_promise}(() => ({expression}), () => ({validator}))"


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

    @js.inline(_rewrite_request_result, request_promise=_request_promise)
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


@js.native
class IDBCursorWithValue(IDBCursor):
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBCursorWithValue

    Browser support: Chrome 24, Safari 8"""

    def __init__(self):
        super().__init__()
        self.value: object = None


@js
def _notify_upgrade(
    request: IDBRequest[object], upgrade: callable, event: IDBVersionChangeEvent
) -> None:
    upgrade(request.result, event.oldVersion, event.newVersion, request.transaction)


@js
def _start_open(
    get_request: Callable[[], IDBRequest[object]],
    get_upgrade: Callable[[], callable | None],
    resolve: callable,
    reject: callable,
) -> None:
    request = get_request()
    upgrade = get_upgrade()
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
def _open_promise(
    get_request: Callable[[], IDBRequest[object]],
    get_upgrade: Callable[[], callable | None],
) -> Awaitable[object]:
    return _promise(
        lambda resolve, reject: _start_open(get_request, get_upgrade, resolve, reject)
    )


@js
async def open_database(
    name: str, version: int, upgrade: callable | None = None
) -> IDBDatabase: ...


@open_database.inline(open_promise=_open_promise)
def open_database(_arg_strs, open_promise, **kwargs):
    name, version = _arg_strs[:2]
    upgrade = _arg_strs[2] if len(_arg_strs) > 2 else "null"
    return f"{open_promise}(() => indexedDB.open({name}, {version}), () => ({upgrade}))"


@js.inline(_rewrite_request_result, request_promise=_request_promise)
async def request_result[T](request: IDBRequest[T]) -> T: ...


@js.inline(_rewrite_request_result, request_promise=_request_promise)
async def request_values(request: IDBRequest[list[object]]) -> list[object]: ...


@js.inline(
    "((transaction, operation) => new Promise((resolve, reject) => {{\n    // objectStore checks finished state without issuing a request. An empty\n    // versionchange transaction may have no stores yet (NotFoundError).\n    try {{ transaction.objectStore(transaction.objectStoreNames[0] ?? ''); }}\n    catch (error) {{ if (error.name !== 'NotFoundError') throw error; }}\n    let result, ready = false, settled = false;\n    const finish = (success, value) => {{\n        if (settled) return;\n        settled = true;\n        transaction.removeEventListener('complete', complete);\n        transaction.removeEventListener('abort', abort);\n        if (success) resolve(value); else reject(value);\n    }};\n    const complete = () => finish(ready, ready ? result : new Error('IndexedDB operation outlived its transaction'));\n    const abort = () => finish(false, transaction.error ?? new Error('IndexedDB transaction aborted'));\n    transaction.addEventListener('complete', complete, {{once: true}});\n    transaction.addEventListener('abort', abort, {{once: true}});\n    const fail = error => {{\n        try {{ transaction.abort(); }} catch {{}}\n        finish(false, error);\n    }};\n    try {{\n        Promise.resolve(operation()).then(value => {{result = value; ready = true;}}, fail);\n    }} catch (error) {{ fail(error); }}\n}}))({transaction}, {operation})"
)
async def transaction_result[T](
    transaction: IDBTransaction, operation: Callable[[], Awaitable[T]]
) -> T:
    """Run an operation and await transaction completion, aborting on failure.

    Call immediately after creating the transaction, before yielding. The
    operation may await requests in this transaction, but not timers, network
    I/O, or other work that lets IndexedDB auto-commit. Listeners are installed
    before the operation runs. Request success alone is not commit success.
    An already-finished transaction rejects without invoking the operation.
    """
    ...
