from pyjs import js
from pyjs.web.dom import DOMException
from pyjs.web.events import Event, EventTarget
from pyjs.web.html import DOMStringList


def _request_promise(expression: str, validator: str = "null") -> str:
    if validator == "null":
        resolve = "resolve(request.result)"
        setup = ""
    else:
        resolve = "{try{resolve(validate(request.result))}catch(error){reject(error)}}"
        setup = f"const validate = {validator};"
    return "".join(
        [
            "new Promise((resolve, reject) => {",
            f"const request = {expression};{setup}",
            f"request.addEventListener('success', () => {resolve}, {{once: true}});",
            "request.addEventListener('error', () => reject(request.error), ",
            "{once: true});})",
        ]
    )


def _rewrite_request_result(_arg_strs, self=None, **kwargs):
    if self is not None:
        validator = _arg_strs[0] if _arg_strs else "null"
        return _request_promise(self, validator)
    validator = _arg_strs[1] if len(_arg_strs) > 1 else "null"
    return _request_promise(_arg_strs[0], validator)


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

    @js.inline(_rewrite_request_result)
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
async def open_database(
    name: str, version: int, upgrade: callable | None = None
) -> IDBDatabase: ...


@open_database.inline
def open_database(_arg_strs, **kwargs):
    name, version = _arg_strs[:2]
    upgrade = _arg_strs[2] if len(_arg_strs) > 2 else "null"
    return f"new Promise((resolve, reject) => {{const request = indexedDB.open({name}, {version});const upgrade = {upgrade};if (upgrade !== null) request.addEventListener('upgradeneeded', event => upgrade(request.result, event.oldVersion, event.newVersion, request.transaction), {{once: true}});request.addEventListener('success', () => resolve(request.result), {{once: true}});request.addEventListener('error', () => reject(request.error), {{once: true}});}})"


@js.inline(_rewrite_request_result)
async def request_result[T](request: IDBRequest[T]) -> T: ...


@js.inline(_rewrite_request_result)
async def request_values(request: IDBRequest[list[object]]) -> list[object]: ...
