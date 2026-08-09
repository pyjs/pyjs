from pyjs import js, js_object
from pyjs.web.dom import DOMException
from pyjs.web.events import Event, EventTarget
from pyjs.web.html import DOMStringList


@js(builtin=True)
class IDBCursor:
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBCursor

    Browser support: Chrome 24, Safari 8"""

    def __init__(self):
        self.direction: str = ""
        self.key: object = None
        self.primaryKey: object = None
        self.request: IDBRequest = None
        self.source: IDBObjectStore | IDBIndex = None

    def advance(self, count: int) -> None: ...

    @js(inline="{self}.continue({_args_joined})")
    def continue_(self, key: object | None = None) -> None: ...

    def continuePrimaryKey(self, key: object, primaryKey: object) -> None: ...

    def delete(self) -> IDBRequest: ...

    def update(self, value: object) -> IDBRequest: ...


@js(builtin=True)
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


@js
class IDBDatabaseInfo:
    """WebIDL source: @webref/idl/IndexedDB.idl"""

    def __init__(self, name: str | None = None, version: int | None = None):
        self.name = name
        self.version = version


@js(builtin=True)
class IDBFactory:
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBFactory

    Browser support: Chrome 24, Safari 8"""

    def cmp(self, first: object, second: object) -> int: ...

    async def databases(self) -> list[IDBDatabaseInfo]: ...

    def deleteDatabase(self, name: str) -> IDBOpenDBRequest: ...

    def open(self, name: str, version: int | None = None) -> IDBOpenDBRequest: ...


indexedDB = IDBFactory()
js_object(indexedDB, builtin=True)


@js
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


@js(builtin=True)
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

    def count(self, query: object | None = None) -> IDBRequest: ...

    def get(self, query: object) -> IDBRequest: ...

    def getAll(
        self, queryOrOptions: object | None = None, count: int | None = None
    ) -> IDBRequest: ...

    def getAllKeys(
        self, queryOrOptions: object | None = None, count: int | None = None
    ) -> IDBRequest: ...

    def getAllRecords(
        self,
        *,
        query: object | None = None,
        count: int | None = None,
        direction: str = "next",
    ) -> IDBRequest: ...

    def getKey(self, query: object) -> IDBRequest: ...

    def openCursor(
        self, query: object | None = None, direction: str = "next"
    ) -> IDBRequest: ...

    def openKeyCursor(
        self, query: object | None = None, direction: str = "next"
    ) -> IDBRequest: ...


@js
class IDBIndexParameters:
    """WebIDL source: @webref/idl/IndexedDB.idl"""

    def __init__(self, multiEntry: bool = False, unique: bool = False):
        self.multiEntry = multiEntry
        self.unique = unique


@js(builtin=True)
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


@js(builtin=True)
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

    def add(self, value: object, key: object | None = None) -> IDBRequest: ...

    def clear(self) -> IDBRequest: ...

    def count(self, query: object | None = None) -> IDBRequest: ...

    def createIndex(
        self,
        name: str,
        keyPath: str | list[str],
        *,
        unique: bool = False,
        multiEntry: bool = False,
    ) -> IDBIndex: ...

    def delete(self, query: object) -> IDBRequest: ...

    def deleteIndex(self, name: str) -> None: ...

    def get(self, query: object) -> IDBRequest: ...

    def getAll(
        self, queryOrOptions: object | None = None, count: int | None = None
    ) -> IDBRequest: ...

    def getAllKeys(
        self, queryOrOptions: object | None = None, count: int | None = None
    ) -> IDBRequest: ...

    def getAllRecords(
        self,
        *,
        query: object | None = None,
        count: int | None = None,
        direction: str = "next",
    ) -> IDBRequest: ...

    def getKey(self, query: object) -> IDBRequest: ...

    def index(self, name: str) -> IDBIndex: ...

    def openCursor(
        self, query: object | None = None, direction: str = "next"
    ) -> IDBRequest: ...

    def openKeyCursor(
        self, query: object | None = None, direction: str = "next"
    ) -> IDBRequest: ...

    def put(self, value: object, key: object | None = None) -> IDBRequest: ...


@js
class IDBObjectStoreParameters:
    """WebIDL source: @webref/idl/IndexedDB.idl"""

    def __init__(
        self, autoIncrement: bool = False, keyPath: str | list[str] | None = None
    ):
        self.autoIncrement = autoIncrement
        self.keyPath = keyPath


@js(builtin=True)
class IDBRecord:
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBRecord

    Browser support: Chrome 141, Safari preview"""

    def __init__(self):
        self.key: object = None
        self.primaryKey: object = None
        self.value: object = None


@js(builtin=True)
class IDBRequest(EventTarget):
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBRequest

    Browser support: Chrome 24, Safari 8"""

    def __init__(self):
        super().__init__()
        self.error: DOMException | None = None
        self.onerror: callable = None
        self.onsuccess: callable = None
        self.readyState: str = ""
        self.result: object = None
        self.source: IDBObjectStore | IDBIndex | IDBCursor | None = None
        self.transaction: IDBTransaction | None = None


@js(builtin=True)
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


@js
class IDBTransactionOptions:
    """WebIDL source: @webref/idl/IndexedDB.idl"""

    def __init__(self, durability: str = "default"):
        self.durability = durability


@js(builtin=True)
class IDBVersionChangeEvent(Event):
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBVersionChangeEvent

    Browser support: Chrome 24, Safari 8"""

    def __init__(self, type: str, *, oldVersion: int = 0, newVersion: int | None = None):
        super().__init__()
        self.newVersion: int | None = newVersion
        self.oldVersion: int = oldVersion


@js
class IDBVersionChangeEventInit:
    """WebIDL source: @webref/idl/IndexedDB.idl"""

    def __init__(self, newVersion: int | None = None, oldVersion: int = 0):
        self.newVersion = newVersion
        self.oldVersion = oldVersion


@js(builtin=True)
class IDBCursorWithValue(IDBCursor):
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBCursorWithValue

    Browser support: Chrome 24, Safari 8"""

    def __init__(self):
        super().__init__()
        self.value: object = None


@js(builtin=True)
class IDBOpenDBRequest(IDBRequest):
    """WebIDL source: @webref/idl/IndexedDB.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IDBOpenDBRequest

    Browser support: Chrome 24, Safari 8"""

    def __init__(self):
        super().__init__()
        self.onblocked: callable = None
        self.onupgradeneeded: callable = None


def _request_promise(expression: str) -> str:
    return f"new Promise((resolve, reject) => {{const request = {expression};request.addEventListener('success', () => resolve(request.result), {{once: true}});request.addEventListener('error', () => reject(request.error), {{once: true}});}})"


def _rewrite_open_database(_arg_strs, **kwargs):
    name, version = _arg_strs[:2]
    upgrade = _arg_strs[2] if len(_arg_strs) > 2 else "null"
    return f"new Promise((resolve, reject) => {{const request = indexedDB.open({name}, {version});const upgrade = {upgrade};if (upgrade !== null) request.addEventListener('upgradeneeded', event => upgrade(request.result, event.oldVersion, event.newVersion, request.transaction), {{once: true}});request.addEventListener('success', () => resolve(request.result), {{once: true}});request.addEventListener('error', () => reject(request.error), {{once: true}});}})"


def _rewrite_request_result(_arg_strs, **kwargs):
    return _request_promise(_arg_strs[0])


@js(builtin=True, inline=_rewrite_open_database)
async def open_database(
    name: str, version: int, upgrade: callable | None = None
) -> IDBDatabase: ...


@js(builtin=True, inline=_rewrite_request_result)
async def request_result(request: IDBRequest) -> object: ...


@js(builtin=True, inline=_rewrite_request_result)
async def request_values(request: IDBRequest) -> list[object]: ...
