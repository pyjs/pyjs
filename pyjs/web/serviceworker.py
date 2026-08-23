from collections.abc import Awaitable, Iterable

from pyjs import js
from pyjs.javascript import (
    ArrayBuffer,
    BigInt64Array,
    BigUint64Array,
    DataView,
    Float16Array,
    Float32Array,
    Float64Array,
    Int8Array,
    Int16Array,
    Int32Array,
    Uint8Array,
    Uint8ClampedArray,
    Uint16Array,
    Uint32Array,
)
from pyjs.web.events import Event, EventTarget, MessagePort
from pyjs.web.files import Blob
from pyjs.web.html import WorkerGlobalScope
from pyjs.web.network import Request, Response


@js.native
class Cache:
    """WebIDL source: @webref/idl/service-workers.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Cache

    Browser support: Chrome 40, Safari 11.1"""

    async def add(self, request: Request | str) -> None: ...

    async def addAll(self, requests: Iterable[Request | str]) -> None: ...

    async def delete(
        self,
        request: Request | str,
        *,
        ignoreSearch: bool = False,
        ignoreMethod: bool = False,
        ignoreVary: bool = False,
    ) -> bool: ...

    async def keys(
        self,
        request: Request | str | None = None,
        *,
        ignoreSearch: bool = False,
        ignoreMethod: bool = False,
        ignoreVary: bool = False,
    ) -> list[Request]: ...

    async def match(
        self,
        request: Request | str,
        *,
        ignoreSearch: bool = False,
        ignoreMethod: bool = False,
        ignoreVary: bool = False,
    ) -> Response | None: ...

    async def matchAll(
        self,
        request: Request | str | None = None,
        *,
        ignoreSearch: bool = False,
        ignoreMethod: bool = False,
        ignoreVary: bool = False,
    ) -> list[Response]: ...

    async def put(self, request: Request | str, response: Response) -> None: ...


@js.dictionary
class CacheQueryOptions:
    """WebIDL source: @webref/idl/service-workers.idl"""

    def __init__(
        self,
        ignoreMethod: bool = False,
        ignoreSearch: bool = False,
        ignoreVary: bool = False,
    ):
        self.ignoreMethod = ignoreMethod
        self.ignoreSearch = ignoreSearch
        self.ignoreVary = ignoreVary


@js.native
class CacheStorage:
    """WebIDL source: @webref/idl/service-workers.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CacheStorage

    Browser support: Chrome 43, Safari 11.1"""

    async def delete(self, cacheName: str) -> bool: ...

    async def has(self, cacheName: str) -> bool: ...

    async def keys(self) -> list[str]: ...

    async def match(
        self,
        request: Request | str,
        *,
        ignoreSearch: bool = False,
        ignoreMethod: bool = False,
        ignoreVary: bool = False,
        cacheName: str | None = None,
    ) -> Response | None: ...

    async def open(self, cacheName: str) -> Cache: ...


caches = CacheStorage()
js.native(caches)


@js.native
class Client:
    """WebIDL source: @webref/idl/service-workers.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Client

    Browser support: Chrome 40, Safari 11.1"""

    def __init__(self):
        self.frameType: str = ""
        self.id: str = ""
        self.type: str = ""
        self.url: str = ""

    def postMessage(self, message: object, transfer: list[object]) -> None: ...


@js.dictionary
class ClientQueryOptions:
    """WebIDL source: @webref/idl/service-workers.idl"""

    def __init__(self, includeUncontrolled: bool = False, type: str = "window"):
        self.includeUncontrolled = includeUncontrolled
        self.type = type


@js.native
class Clients:
    """WebIDL source: @webref/idl/service-workers.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Clients

    Browser support: Chrome 40, Safari 11.1"""

    async def claim(self) -> None: ...

    async def get(self, id: str) -> Client | None: ...

    async def matchAll(
        self, *, includeUncontrolled: bool = False, type: str = "window"
    ) -> list[Client]: ...

    async def openWindow(self, url: str) -> WindowClient | None: ...


@js.native
class ExtendableEvent(Event):
    """WebIDL source: @webref/idl/service-workers.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ExtendableEvent

    Browser support: Chrome 40, Safari 11.1"""

    def __init__(self, type: str):
        super().__init__()

    def waitUntil(self, f: object) -> None: ...


@js.dictionary
class GetNotificationOptions:
    """WebIDL source: @webref/idl/notifications.idl"""

    def __init__(self, tag: str = ""):
        self.tag = tag


@js.native
class NavigationPreloadManager:
    """WebIDL source: @webref/idl/service-workers.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NavigationPreloadManager

    Browser support: Chrome 59, Safari 15.4"""

    async def disable(self) -> None: ...

    async def enable(self) -> None: ...

    async def getState(self) -> NavigationPreloadState: ...

    async def setHeaderValue(self, value: str) -> None: ...


@js.dictionary
class NavigationPreloadState:
    """WebIDL source: @webref/idl/service-workers.idl"""

    def __init__(self, enabled: bool = False, headerValue: str | None = None):
        self.enabled = enabled
        self.headerValue = headerValue


@js.native
class Navigator:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Navigator

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.serviceWorker: ServiceWorkerContainer = None


navigator = Navigator()
js.native(navigator)


@js.native
class Notification(EventTarget):
    """WebIDL source: @webref/idl/notifications.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Notification

    Browser support: Chrome 20, Safari 7"""

    def __init__(
        self,
        title: str,
        *,
        dir: str = "auto",
        lang: str = "",
        body: str = "",
        navigate: str | None = None,
        tag: str = "",
        image: str | None = None,
        icon: str | None = None,
        badge: str | None = None,
        vibrate: int | list[int] | None = None,
        timestamp: int | None = None,
        renotify: bool = False,
        silent: bool | None = None,
        requireInteraction: bool = False,
        data: object | None = None,
        actions: list[NotificationAction] | None = None,
    ):
        super().__init__()
        self.actions: list[NotificationAction] = actions
        self.badge: str = badge
        self.body: str = body
        self.data: object = data
        self.dir: str = dir
        self.icon: str = icon
        self.image: str = image
        self.lang: str = lang
        self.maxActions: int = 0
        self.navigate: str = navigate
        self.onclick: callable = None
        self.onclose: callable = None
        self.onerror: callable = None
        self.onshow: callable = None
        self.permission: str = ""
        self.renotify: bool = renotify
        self.requireInteraction: bool = requireInteraction
        self.silent: bool | None = silent
        self.tag: str = tag
        self.timestamp: int = timestamp
        self.title: str = title
        self.vibrate: list[int] = vibrate

    def close(self) -> None: ...

    @staticmethod
    async def requestPermission(deprecatedCallback: callable | None = None) -> str: ...


@js.dictionary
class NotificationAction:
    """WebIDL source: @webref/idl/notifications.idl"""

    def __init__(
        self,
        action: str,
        title: str,
        icon: str | None = None,
        navigate: str | None = None,
    ):
        self.action = action
        self.title = title
        if icon is not None:
            self.icon = icon
        if navigate is not None:
            self.navigate = navigate


@js.dictionary
class NotificationOptions:
    """WebIDL source: @webref/idl/notifications.idl"""

    def __init__(
        self,
        actions: list[NotificationAction] | None = None,
        badge: str | None = None,
        body: str = "",
        data: object | None = None,
        dir: str = "auto",
        icon: str | None = None,
        image: str | None = None,
        lang: str = "",
        navigate: str | None = None,
        renotify: bool = False,
        requireInteraction: bool = False,
        silent: bool | None = None,
        tag: str = "",
        timestamp: int | None = None,
        vibrate: int | list[int] | None = None,
    ):
        if actions is None:
            actions = []
        self.actions = actions
        if badge is not None:
            self.badge = badge
        self.body = body
        self.data = data
        self.dir = dir
        if icon is not None:
            self.icon = icon
        if image is not None:
            self.image = image
        self.lang = lang
        if navigate is not None:
            self.navigate = navigate
        self.renotify = renotify
        self.requireInteraction = requireInteraction
        self.silent = silent
        self.tag = tag
        if timestamp is not None:
            self.timestamp = timestamp
        if vibrate is not None:
            self.vibrate = vibrate


@js.dictionary
class PermissionDescriptor:
    """WebIDL source: @webref/idl/permissions.idl"""

    def __init__(self, name: str):
        self.name = name


@js.native
class PushManager:
    """WebIDL source: @webref/idl/push-api.idl

    MDN: https://developer.mozilla.org/docs/Web/API/PushManager

    Browser support: Chrome 42, Safari 16"""

    def __init__(self):
        self.supportedContentEncodings: list[str] = []

    async def getSubscription(self) -> PushSubscription | None: ...

    async def permissionState(
        self,
        *,
        userVisibleOnly: bool = False,
        applicationServerKey: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | str
        | None = None,
    ) -> str: ...

    async def subscribe(
        self,
        *,
        userVisibleOnly: bool = False,
        applicationServerKey: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | str
        | None = None,
    ) -> PushSubscription: ...


@js.native
class PushMessageData:
    """WebIDL source: @webref/idl/push-api.idl

    MDN: https://developer.mozilla.org/docs/Web/API/PushMessageData

    Browser support: Chrome 50, Safari 16"""

    def arrayBuffer(self) -> ArrayBuffer: ...

    def blob(self) -> Blob: ...

    def bytes(self) -> Uint8Array: ...

    def json(self) -> object: ...

    def text(self) -> str: ...


@js.native
class PushSubscription:
    """WebIDL source: @webref/idl/push-api.idl

    MDN: https://developer.mozilla.org/docs/Web/API/PushSubscription

    Browser support: Chrome 42, Safari 16"""

    def __init__(self):
        self.endpoint: str = ""
        self.expirationTime: int | None = None
        self.options: PushSubscriptionOptions = None

    def getKey(self, name: str) -> ArrayBuffer | None: ...

    def toJSON(self) -> PushSubscriptionJSON: ...

    async def unsubscribe(self) -> bool: ...


@js.dictionary
class PushSubscriptionJSON:
    """WebIDL source: @webref/idl/push-api.idl"""

    def __init__(
        self,
        endpoint: str | None = None,
        expirationTime: int | None = None,
        keys: dict[str, str] | None = None,
    ):
        if endpoint is not None:
            self.endpoint = endpoint
        self.expirationTime = expirationTime
        if keys is not None:
            self.keys = keys


@js.native
class PushSubscriptionOptions:
    """WebIDL source: @webref/idl/push-api.idl

    MDN: https://developer.mozilla.org/docs/Web/API/PushSubscriptionOptions

    Browser support: Chrome 54, Safari 16"""

    def __init__(self):
        self.applicationServerKey: ArrayBuffer | None = None
        self.userVisibleOnly: bool = False


@js.dictionary
class PushSubscriptionOptionsInit:
    """WebIDL source: @webref/idl/push-api.idl"""

    def __init__(
        self,
        applicationServerKey: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | str
        | None = None,
        userVisibleOnly: bool = False,
    ):
        self.applicationServerKey = applicationServerKey
        self.userVisibleOnly = userVisibleOnly


@js.dictionary
class RegistrationOptions:
    """WebIDL source: @webref/idl/service-workers.idl"""

    def __init__(
        self,
        scope: str | None = None,
        type: str = "classic",
        updateViaCache: str = "imports",
    ):
        self.scope = scope
        self.type = type
        self.updateViaCache = updateViaCache


@js.dictionary
class RouterCondition:
    """WebIDL source: @webref/idl/service-workers.idl"""

    def __init__(
        self,
        not_: RouterCondition | None = None,
        or_: list[RouterCondition] | None = None,
        requestDestination: str | None = None,
        requestMethod: str | None = None,
        requestMode: str | None = None,
        runningStatus: str | None = None,
        urlPattern: str | URLPatternInit | URLPattern | None = None,
    ):
        self.not_ = not_
        self.or_ = or_
        self.requestDestination = requestDestination
        self.requestMethod = requestMethod
        self.requestMode = requestMode
        self.runningStatus = runningStatus
        self.urlPattern = urlPattern


@js.dictionary
class RouterRule:
    """WebIDL source: @webref/idl/service-workers.idl"""

    def __init__(self, condition: RouterCondition, source: RouterSourceDict | str):
        self.condition = condition
        self.source = source


@js.dictionary
class RouterSourceDict:
    """WebIDL source: @webref/idl/service-workers.idl"""

    def __init__(self, cacheName: str | None = None):
        self.cacheName = cacheName


@js.native
class ServiceWorker(EventTarget):
    """WebIDL source: @webref/idl/service-workers.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ServiceWorker

    Browser support: Chrome 40, Safari 11.1"""

    def __init__(self):
        super().__init__()
        self.onstatechange: callable = None
        self.scriptURL: str = ""
        self.state: str = ""

    def postMessage(self, message: object, transfer: list[object]) -> None: ...


@js.native
class ServiceWorkerContainer(EventTarget):
    """WebIDL source: @webref/idl/service-workers.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ServiceWorkerContainer

    Browser support: Chrome 40, Safari 11.1"""

    def __init__(self):
        super().__init__()
        self.controller: ServiceWorker | None = None
        self.oncontrollerchange: callable = None
        self.onmessage: callable = None
        self.onmessageerror: callable = None
        self.ready: ServiceWorkerRegistration = None

    async def getRegistration(
        self, clientURL: str = ""
    ) -> ServiceWorkerRegistration | None: ...

    async def getRegistrations(self) -> list[ServiceWorkerRegistration]: ...

    async def register(
        self,
        scriptURL: TrustedScriptURL | str,
        *,
        scope: str | None = None,
        type: str = "classic",
        updateViaCache: str = "imports",
    ) -> ServiceWorkerRegistration: ...

    def startMessages(self) -> None: ...


@js.native
class ServiceWorkerRegistration(EventTarget):
    """WebIDL source: @webref/idl/service-workers.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ServiceWorkerRegistration

    Browser support: Chrome 40, Safari 11.1"""

    def __init__(self):
        super().__init__()
        self.active: ServiceWorker | None = None
        self.installing: ServiceWorker | None = None
        self.navigationPreload: NavigationPreloadManager = None
        self.onupdatefound: callable = None
        self.pushManager: PushManager = None
        self.scope: str = ""
        self.updateViaCache: str = ""
        self.waiting: ServiceWorker | None = None

    async def getNotifications(self, *, tag: str = "") -> list[Notification]: ...

    async def showNotification(
        self,
        title: str,
        *,
        dir: str = "auto",
        lang: str = "",
        body: str = "",
        navigate: str | None = None,
        tag: str = "",
        image: str | None = None,
        icon: str | None = None,
        badge: str | None = None,
        vibrate: int | list[int] | None = None,
        timestamp: int | None = None,
        renotify: bool = False,
        silent: bool | None = None,
        requireInteraction: bool = False,
        data: object | None = None,
        actions: list[NotificationAction] | None = None,
    ) -> None: ...

    async def unregister(self) -> bool: ...

    async def update(self) -> ServiceWorkerRegistration: ...


@js.native
class TrustedScriptURL:
    """WebIDL source: @webref/idl/trusted-types.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TrustedScriptURL

    Browser support: Chrome 83, Safari 26"""

    pass


@js.native
class URLPattern:
    """WebIDL source: @webref/idl/urlpattern.idl

    MDN: https://developer.mozilla.org/docs/Web/API/URLPattern

    Browser support: Chrome 95, Safari 26"""

    pass


@js.dictionary
class URLPatternInit:
    """WebIDL source: @webref/idl/urlpattern.idl"""

    def __init__(
        self,
        *,
        baseURL: str | None = None,
        hash: str | None = None,
        hostname: str | None = None,
        password: str | None = None,
        pathname: str | None = None,
        port: str | None = None,
        protocol: str | None = None,
        search: str | None = None,
        username: str | None = None,
    ):
        ...
        if baseURL is not None:
            self.baseURL = baseURL
        if hash is not None:
            self.hash = hash
        if hostname is not None:
            self.hostname = hostname
        if password is not None:
            self.password = password
        if pathname is not None:
            self.pathname = pathname
        if port is not None:
            self.port = port
        if protocol is not None:
            self.protocol = protocol
        if search is not None:
            self.search = search
        if username is not None:
            self.username = username


@js.dictionary
class ExtendableEventInit:
    """WebIDL source: @webref/idl/service-workers.idl"""

    def __init__(self): ...


@js.native
class ServiceWorkerGlobalScope(WorkerGlobalScope):
    """WebIDL source: @webref/idl/service-workers.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ServiceWorkerGlobalScope

    Browser support: Chrome 40, Safari 11.1"""

    def __init__(self):
        super().__init__()
        self.clients: Clients = None
        self.onactivate: callable = None
        self.onfetch: callable = None
        self.oninstall: callable = None
        self.onmessage: callable = None
        self.onmessageerror: callable = None
        self.onnotificationclick: callable = None
        self.onnotificationclose: callable = None
        self.onpush: callable = None
        self.onpushsubscriptionchange: callable = None
        self.registration: ServiceWorkerRegistration = None
        self.serviceWorker: ServiceWorker = None

    async def skipWaiting(self) -> None: ...


@js.dictionary
class ExtendableMessageEventInit:
    """WebIDL source: @webref/idl/service-workers.idl"""

    def __init__(
        self,
        data: object | None = None,
        lastEventId: str = "",
        origin: str = "",
        ports: list[MessagePort] | None = None,
        source: Client | ServiceWorker | MessagePort | None = None,
    ):
        self.data = data
        self.lastEventId = lastEventId
        self.origin = origin
        if ports is None:
            ports = []
        self.ports = ports
        self.source = source


@js.dictionary
class MultiCacheQueryOptions:
    """WebIDL source: @webref/idl/service-workers.idl"""

    def __init__(
        self,
        cacheName: str | None = None,
        ignoreMethod: bool = False,
        ignoreSearch: bool = False,
        ignoreVary: bool = False,
    ):
        self.cacheName = cacheName
        self.ignoreMethod = ignoreMethod
        self.ignoreSearch = ignoreSearch
        self.ignoreVary = ignoreVary


@js.dictionary
class NotificationEventInit:
    """WebIDL source: @webref/idl/notifications.idl"""

    def __init__(self, notification: Notification, action: str = ""):
        self.notification = notification
        self.action = action


@js.dictionary
class PushEventInit:
    """WebIDL source: @webref/idl/push-api.idl"""

    def __init__(
        self,
        data: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | str
        | None = None,
        notification: Notification | None = None,
    ):
        self.data = data
        self.notification = notification


@js.dictionary
class PushPermissionDescriptor:
    """WebIDL source: @webref/idl/push-api.idl"""

    def __init__(self, name: str, userVisibleOnly: bool = False):
        self.name = name
        self.userVisibleOnly = userVisibleOnly


@js.dictionary
class PushSubscriptionChangeEventInit:
    """WebIDL source: @webref/idl/push-api.idl"""

    def __init__(
        self,
        newSubscription: PushSubscription | None = None,
        oldSubscription: PushSubscription | None = None,
    ):
        self.newSubscription = newSubscription
        self.oldSubscription = oldSubscription


@js.dictionary
class FetchEventInit:
    """WebIDL source: @webref/idl/service-workers.idl"""

    def __init__(
        self,
        request: Request,
        clientId: str = "",
        handled: None = None,
        preloadResponse: object | None = None,
        replacesClientId: str = "",
        resultingClientId: str = "",
    ):
        self.request = request
        self.clientId = clientId
        self.handled = handled
        self.preloadResponse = preloadResponse
        self.replacesClientId = replacesClientId
        self.resultingClientId = resultingClientId


@js.native
class ExtendableMessageEvent(ExtendableEvent):
    """WebIDL source: @webref/idl/service-workers.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ExtendableMessageEvent

    Browser support: Chrome 51, Safari 11.1"""

    def __init__(
        self,
        type: str,
        *,
        data: object | None = None,
        origin: str = "",
        lastEventId: str = "",
        source: Client | ServiceWorker | MessagePort | None = None,
        ports: list[MessagePort] | None = None,
    ):
        super().__init__()
        self.data: object = data
        self.lastEventId: str = lastEventId
        self.origin: str = origin
        self.ports: list[MessagePort] = ports
        self.source: Client | ServiceWorker | MessagePort | None = source


@js.native
class FetchEvent(ExtendableEvent):
    """WebIDL source: @webref/idl/service-workers.idl

    MDN: https://developer.mozilla.org/docs/Web/API/FetchEvent

    Browser support: Chrome 40, Safari 11.1"""

    def __init__(self, type: str, eventInitDict: FetchEventInit):
        super().__init__()
        self.clientId = eventInitDict.clientId
        self.handled = eventInitDict.handled
        self.preloadResponse = eventInitDict.preloadResponse
        self.replacesClientId = eventInitDict.replacesClientId
        self.request = eventInitDict.request
        self.resultingClientId = eventInitDict.resultingClientId

    def respondWith(self, r: Response | Awaitable[Response]) -> None: ...


@js.native
class InstallEvent(ExtendableEvent):
    """WebIDL source: @webref/idl/service-workers.idl

    MDN: https://developer.mozilla.org/docs/Web/API/InstallEvent

    Browser support: Chrome 40, Safari 27"""

    def __init__(self, type: str):
        super().__init__()

    async def addRoutes(
        self, *, condition: RouterCondition, source: RouterSourceDict | str
    ) -> None: ...


@js.native
class NotificationEvent(ExtendableEvent):
    """WebIDL source: @webref/idl/notifications.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NotificationEvent

    Browser support: Chrome 42, Safari 16"""

    def __init__(self, type: str, eventInitDict: NotificationEventInit):
        super().__init__()
        self.action = eventInitDict.action
        self.notification = eventInitDict.notification


@js.native
class PushEvent(ExtendableEvent):
    """WebIDL source: @webref/idl/push-api.idl

    MDN: https://developer.mozilla.org/docs/Web/API/PushEvent

    Browser support: Chrome 42, Safari 16"""

    def __init__(
        self,
        type: str,
        *,
        data: Int8Array
        | Int16Array
        | Int32Array
        | Uint8Array
        | Uint16Array
        | Uint32Array
        | Uint8ClampedArray
        | BigInt64Array
        | BigUint64Array
        | Float16Array
        | Float32Array
        | Float64Array
        | DataView
        | ArrayBuffer
        | str
        | None = None,
        notification: Notification | None = None,
    ):
        super().__init__()
        self.data: PushMessageData | None = data
        self.notification: Notification | None = notification


@js.native
class PushSubscriptionChangeEvent(ExtendableEvent):
    """WebIDL source: @webref/idl/push-api.idl

    Browser support: Chrome 138, Safari 16"""

    def __init__(
        self,
        type: str,
        *,
        newSubscription: PushSubscription | None = None,
        oldSubscription: PushSubscription | None = None,
    ):
        super().__init__()
        self.newSubscription: PushSubscription | None = newSubscription
        self.oldSubscription: PushSubscription | None = oldSubscription


@js.inline("self")
def service_worker_scope() -> ServiceWorkerGlobalScope: ...


@js.native
class WindowClient(Client):
    """WebIDL source: @webref/idl/service-workers.idl

    MDN: https://developer.mozilla.org/docs/Web/API/WindowClient

    Browser support: Chrome 42, Safari 11.1"""

    def __init__(self):
        super().__init__()
        self.ancestorOrigins: list[str] = []
        self.focused: bool = False
        self.visibilityState: str = ""

    async def focus(self) -> WindowClient: ...

    async def navigate(self, url: str) -> WindowClient | None: ...
