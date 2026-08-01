from pyjs import js


@js(builtin=True)
class AbortSignal:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/AbortSignal

    Browser support: Chrome 66, Safari 11.1"""

    pass


@js(builtin=True)
class Event:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Event

    Browser support: Chrome 1, Safari 1"""

    AT_TARGET = 2
    BUBBLING_PHASE = 3
    CAPTURING_PHASE = 1
    NONE = 0

    def __init__(
        self,
        type: str,
        *,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
    ):
        self.bubbles: bool = bubbles
        self.cancelable: bool = cancelable
        self.cancelBubble: bool = False
        self.composed: bool = composed
        self.currentTarget: EventTarget | None = None
        self.defaultPrevented: bool = False
        self.eventPhase: int = 0
        self.isTrusted: bool = False
        self.returnValue: bool = False
        self.srcElement: EventTarget | None = None
        self.target: EventTarget | None = None
        self.timeStamp: float = 0.0
        self.type: str = type

    def composedPath(self) -> list[EventTarget]: ...

    def initEvent(
        self, type: str, bubbles: bool = False, cancelable: bool = False
    ) -> None: ...

    def preventDefault(self) -> None: ...

    def stopImmediatePropagation(self) -> None: ...

    def stopPropagation(self) -> None: ...


@js
class EventInit:
    """WebIDL source: @webref/idl/dom.idl"""

    def __init__(
        self, bubbles: bool = False, cancelable: bool = False, composed: bool = False
    ):
        self.bubbles = bubbles
        self.cancelable = cancelable
        self.composed = composed


@js(builtin=True)
class EventListener:
    """WebIDL source: @webref/idl/dom.idl"""

    pass


@js
class EventListenerOptions:
    """WebIDL source: @webref/idl/dom.idl"""

    def __init__(self, capture: bool = False):
        self.capture = capture


@js(builtin=True)
class EventTarget:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/EventTarget

    Browser support: Chrome 1, Safari 1"""

    def __init__(self): ...

    def addEventListener(
        self,
        type: str,
        callback: EventListener | None,
        *,
        capture: bool = False,
        passive: bool | None = None,
        once: bool = False,
        signal: AbortSignal | None = None,
    ) -> None: ...

    def dispatchEvent(self, event: Event) -> bool: ...

    def removeEventListener(
        self, type: str, callback: EventListener | None, *, capture: bool = False
    ) -> None: ...

    def when(
        self, type: str, *, capture: bool = False, passive: bool | None = None
    ) -> Observable: ...


@js(builtin=True)
class InputDeviceCapabilities:
    """WebIDL source: @webref/idl/input-device-capabilities.idl

    MDN: https://developer.mozilla.org/docs/Web/API/InputDeviceCapabilities

    Browser support: Chrome 47"""

    pass


@js(builtin=True)
class MessagePort:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MessagePort

    Browser support: Chrome 2, Safari 5"""

    pass


@js(builtin=True)
class Observable:
    """WebIDL source: @webref/idl/observable.idl

    Browser support: Chrome 135"""

    pass


@js
class ObservableEventListenerOptions:
    """WebIDL source: @webref/idl/observable.idl"""

    def __init__(self, capture: bool = False, passive: bool | None = None):
        self.capture = capture
        self.passive = passive


@js(builtin=True)
class ServiceWorker:
    """WebIDL source: @webref/idl/service-workers.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ServiceWorker

    Browser support: Chrome 40, Safari 11.1"""

    pass


@js(builtin=True)
class Window:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Window

    Browser support: Chrome 1, Safari 1"""

    pass


@js(builtin=True)
class WindowProxy:
    """WebIDL source: @webref/idl/unknown"""

    pass


@js
class AddEventListenerOptions(EventListenerOptions):
    """WebIDL source: @webref/idl/dom.idl"""

    def __init__(
        self,
        capture: bool = False,
        once: bool = False,
        passive: bool | None = None,
        signal: AbortSignal | None = None,
    ):
        self.capture = capture
        self.once = once
        self.passive = passive
        self.signal = signal


@js(builtin=True)
class CustomEvent(Event):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CustomEvent

    Browser support: Chrome 5, Safari 5"""

    def __init__(
        self,
        type: str,
        *,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        detail: object | None = None,
    ):
        super().__init__(type, bubbles=bubbles, cancelable=cancelable, composed=composed)
        self.detail: object = detail

    def initCustomEvent(
        self,
        type: str,
        bubbles: bool = False,
        cancelable: bool = False,
        detail: object | None = None,
    ) -> None: ...


@js
class CustomEventInit(EventInit):
    """WebIDL source: @webref/idl/dom.idl"""

    def __init__(
        self,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        detail: object | None = None,
    ):
        self.bubbles = bubbles
        self.cancelable = cancelable
        self.composed = composed
        self.detail = detail


@js(builtin=True)
class ErrorEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ErrorEvent

    Browser support: Chrome 10, Safari 6"""

    def __init__(
        self,
        type: str,
        *,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        message: str = "",
        filename: str = "",
        lineno: int = 0,
        colno: int = 0,
        error: object | None = None,
    ):
        super().__init__(type, bubbles=bubbles, cancelable=cancelable, composed=composed)
        self.colno: int = colno
        self.error: object = error
        self.filename: str = filename
        self.lineno: int = lineno
        self.message: str = message


@js
class ErrorEventInit(EventInit):
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        bubbles: bool = False,
        cancelable: bool = False,
        colno: int = 0,
        composed: bool = False,
        error: object | None = None,
        filename: str = "",
        lineno: int = 0,
        message: str = "",
    ):
        self.bubbles = bubbles
        self.cancelable = cancelable
        self.colno = colno
        self.composed = composed
        self.error = error
        self.filename = filename
        self.lineno = lineno
        self.message = message


@js(builtin=True)
class MessageEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MessageEvent

    Browser support: Chrome 2, Safari 4"""

    def __init__(
        self,
        type: str,
        *,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        data: object | None = None,
        origin: str = "",
        lastEventId: str = "",
        source: Window | MessagePort | ServiceWorker | None = None,
        ports: list[MessagePort] | None = None,
    ):
        super().__init__(type, bubbles=bubbles, cancelable=cancelable, composed=composed)
        self.data: object = data
        self.lastEventId: str = lastEventId
        self.origin: str = origin
        self.ports: list[MessagePort] = []
        if ports is not None:
            self.ports = ports
        self.source: Window | MessagePort | ServiceWorker | None = source

    def initMessageEvent(
        self,
        type: str,
        bubbles: bool = False,
        cancelable: bool = False,
        data: object | None = None,
        origin: str = "",
        lastEventId: str = "",
        source: Window | MessagePort | ServiceWorker | None = None,
        ports: list[MessagePort] | None = None,
    ) -> None: ...


@js
class MessageEventInit(EventInit):
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        data: object | None = None,
        lastEventId: str = "",
        origin: str = "",
        ports: list[MessagePort] | None = None,
        source: Window | MessagePort | ServiceWorker | None = None,
    ):
        self.bubbles = bubbles
        self.cancelable = cancelable
        self.composed = composed
        self.data = data
        self.lastEventId = lastEventId
        self.origin = origin
        self.ports = ports
        self.source = source


@js(builtin=True)
class ProgressEvent(Event):
    """WebIDL source: @webref/idl/xhr.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ProgressEvent

    Browser support: Chrome 1, Safari 3.1"""

    def __init__(
        self,
        type: str,
        *,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        lengthComputable: bool = False,
        loaded: float = 0,
        total: float = 0,
    ):
        super().__init__(type, bubbles=bubbles, cancelable=cancelable, composed=composed)
        self.lengthComputable: bool = lengthComputable
        self.loaded: float = loaded
        self.total: float = total


@js
class ProgressEventInit(EventInit):
    """WebIDL source: @webref/idl/xhr.idl"""

    def __init__(
        self,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        lengthComputable: bool = False,
        loaded: float = 0,
        total: float = 0,
    ):
        self.bubbles = bubbles
        self.cancelable = cancelable
        self.composed = composed
        self.lengthComputable = lengthComputable
        self.loaded = loaded
        self.total = total


@js(builtin=True)
class PromiseRejectionEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/PromiseRejectionEvent

    Browser support: Chrome 49, Safari 11"""

    def __init__(
        self,
        type: str,
        *,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        promise: object,
        reason: object | None = None,
    ):
        super().__init__(type, bubbles=bubbles, cancelable=cancelable, composed=composed)
        self.promise: object = promise
        self.reason: object = reason


@js
class PromiseRejectionEventInit(EventInit):
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        promise: object,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        reason: object | None = None,
    ):
        self.promise = promise
        self.bubbles = bubbles
        self.cancelable = cancelable
        self.composed = composed
        self.reason = reason


@js(builtin=True)
class UIEvent(Event):
    """WebIDL source: @webref/idl/uievents.idl

    MDN: https://developer.mozilla.org/docs/Web/API/UIEvent

    Browser support: Chrome 1, Safari 1"""

    def __init__(
        self,
        type: str,
        *,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        sourceCapabilities: InputDeviceCapabilities | None = None,
        view: Window | None = None,
        detail: int = 0,
        which: int = 0,
    ):
        super().__init__(type, bubbles=bubbles, cancelable=cancelable, composed=composed)
        self.detail: int = detail
        self.sourceCapabilities: InputDeviceCapabilities | None = sourceCapabilities
        self.view: Window | None = view
        self.which: int = which

    def initUIEvent(
        self,
        typeArg: str,
        bubblesArg: bool = False,
        cancelableArg: bool = False,
        viewArg: Window | None = None,
        detailArg: int = 0,
    ) -> None: ...


@js
class UIEventInit(EventInit):
    """WebIDL source: @webref/idl/uievents.idl"""

    def __init__(
        self,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        detail: int = 0,
        sourceCapabilities: InputDeviceCapabilities | None = None,
        view: Window | None = None,
        which: int = 0,
    ):
        self.bubbles = bubbles
        self.cancelable = cancelable
        self.composed = composed
        self.detail = detail
        self.sourceCapabilities = sourceCapabilities
        self.view = view
        self.which = which


@js
class EventModifierInit(UIEventInit):
    """WebIDL source: @webref/idl/uievents.idl"""

    def __init__(
        self,
        altKey: bool = False,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        ctrlKey: bool = False,
        detail: int = 0,
        metaKey: bool = False,
        modifierAltGraph: bool = False,
        modifierCapsLock: bool = False,
        modifierFn: bool = False,
        modifierFnLock: bool = False,
        modifierHyper: bool = False,
        modifierNumLock: bool = False,
        modifierScrollLock: bool = False,
        modifierSuper: bool = False,
        modifierSymbol: bool = False,
        modifierSymbolLock: bool = False,
        shiftKey: bool = False,
        sourceCapabilities: InputDeviceCapabilities | None = None,
        view: Window | None = None,
        which: int = 0,
    ):
        self.altKey = altKey
        self.bubbles = bubbles
        self.cancelable = cancelable
        self.composed = composed
        self.ctrlKey = ctrlKey
        self.detail = detail
        self.metaKey = metaKey
        self.modifierAltGraph = modifierAltGraph
        self.modifierCapsLock = modifierCapsLock
        self.modifierFn = modifierFn
        self.modifierFnLock = modifierFnLock
        self.modifierHyper = modifierHyper
        self.modifierNumLock = modifierNumLock
        self.modifierScrollLock = modifierScrollLock
        self.modifierSuper = modifierSuper
        self.modifierSymbol = modifierSymbol
        self.modifierSymbolLock = modifierSymbolLock
        self.shiftKey = shiftKey
        self.sourceCapabilities = sourceCapabilities
        self.view = view
        self.which = which


@js(builtin=True)
class FocusEvent(UIEvent):
    """WebIDL source: @webref/idl/uievents.idl

    MDN: https://developer.mozilla.org/docs/Web/API/FocusEvent

    Browser support: Chrome 26, Safari 7"""

    def __init__(
        self,
        type: str,
        *,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        sourceCapabilities: InputDeviceCapabilities | None = None,
        view: Window | None = None,
        detail: int = 0,
        which: int = 0,
        relatedTarget: EventTarget | None = None,
    ):
        super().__init__(
            type,
            bubbles=bubbles,
            cancelable=cancelable,
            composed=composed,
            sourceCapabilities=sourceCapabilities,
            view=view,
            detail=detail,
            which=which,
        )
        self.relatedTarget: EventTarget | None = relatedTarget


@js
class FocusEventInit(UIEventInit):
    """WebIDL source: @webref/idl/uievents.idl"""

    def __init__(
        self,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        detail: int = 0,
        relatedTarget: EventTarget | None = None,
        sourceCapabilities: InputDeviceCapabilities | None = None,
        view: Window | None = None,
        which: int = 0,
    ):
        self.bubbles = bubbles
        self.cancelable = cancelable
        self.composed = composed
        self.detail = detail
        self.relatedTarget = relatedTarget
        self.sourceCapabilities = sourceCapabilities
        self.view = view
        self.which = which


@js(builtin=True)
class KeyboardEvent(UIEvent):
    """WebIDL source: @webref/idl/uievents.idl

    MDN: https://developer.mozilla.org/docs/Web/API/KeyboardEvent

    Browser support: Chrome 1, Safari 1.2"""

    DOM_KEY_LOCATION_LEFT = 1
    DOM_KEY_LOCATION_NUMPAD = 3
    DOM_KEY_LOCATION_RIGHT = 2
    DOM_KEY_LOCATION_STANDARD = 0

    def __init__(
        self,
        type: str,
        *,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        sourceCapabilities: InputDeviceCapabilities | None = None,
        view: Window | None = None,
        detail: int = 0,
        which: int = 0,
        ctrlKey: bool = False,
        shiftKey: bool = False,
        altKey: bool = False,
        metaKey: bool = False,
        modifierAltGraph: bool = False,
        modifierCapsLock: bool = False,
        modifierFn: bool = False,
        modifierFnLock: bool = False,
        modifierHyper: bool = False,
        modifierNumLock: bool = False,
        modifierScrollLock: bool = False,
        modifierSuper: bool = False,
        modifierSymbol: bool = False,
        modifierSymbolLock: bool = False,
        key: str = "",
        code: str = "",
        location: int = 0,
        repeat: bool = False,
        isComposing: bool = False,
        charCode: int = 0,
        keyCode: int = 0,
    ):
        super().__init__(
            type,
            bubbles=bubbles,
            cancelable=cancelable,
            composed=composed,
            sourceCapabilities=sourceCapabilities,
            view=view,
            detail=detail,
            which=which,
        )
        self.altKey: bool = altKey
        self.charCode: int = charCode
        self.code: str = code
        self.ctrlKey: bool = ctrlKey
        self.isComposing: bool = isComposing
        self.key: str = key
        self.keyCode: int = keyCode
        self.location: int = location
        self.metaKey: bool = metaKey
        self.repeat: bool = repeat
        self.shiftKey: bool = shiftKey

    def getModifierState(self, keyArg: str) -> bool: ...

    def initKeyboardEvent(
        self,
        typeArg: str,
        bubblesArg: bool = False,
        cancelableArg: bool = False,
        viewArg: Window | None = None,
        keyArg: str = "",
        locationArg: int = 0,
        ctrlKey: bool = False,
        altKey: bool = False,
        shiftKey: bool = False,
        metaKey: bool = False,
    ) -> None: ...


@js(builtin=True)
class MouseEvent(UIEvent):
    """WebIDL source: @webref/idl/pointerevents.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MouseEvent

    Browser support: Chrome 1, Safari 1"""

    def __init__(
        self,
        type: str,
        *,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        sourceCapabilities: InputDeviceCapabilities | None = None,
        view: Window | None = None,
        detail: int = 0,
        which: int = 0,
        ctrlKey: bool = False,
        shiftKey: bool = False,
        altKey: bool = False,
        metaKey: bool = False,
        modifierAltGraph: bool = False,
        modifierCapsLock: bool = False,
        modifierFn: bool = False,
        modifierFnLock: bool = False,
        modifierHyper: bool = False,
        modifierNumLock: bool = False,
        modifierScrollLock: bool = False,
        modifierSuper: bool = False,
        modifierSymbol: bool = False,
        modifierSymbolLock: bool = False,
        screenX: int = 0,
        screenY: int = 0,
        clientX: int = 0,
        clientY: int = 0,
        button: int = 0,
        buttons: int = 0,
        relatedTarget: EventTarget | None = None,
        movementX: float = 0,
        movementY: float = 0,
    ):
        super().__init__(
            type,
            bubbles=bubbles,
            cancelable=cancelable,
            composed=composed,
            sourceCapabilities=sourceCapabilities,
            view=view,
            detail=detail,
            which=which,
        )
        self.altKey: bool = altKey
        self.button: int = button
        self.buttons: int = buttons
        self.clientX: int = clientX
        self.clientY: int = clientY
        self.ctrlKey: bool = ctrlKey
        self.layerX: int = 0
        self.layerY: int = 0
        self.metaKey: bool = metaKey
        self.movementX: float = movementX
        self.movementY: float = movementY
        self.offsetX: float = 0.0
        self.offsetY: float = 0.0
        self.pageX: float = 0.0
        self.pageY: float = 0.0
        self.relatedTarget: EventTarget | None = relatedTarget
        self.screenX: int = screenX
        self.screenY: int = screenY
        self.shiftKey: bool = shiftKey
        self.x: float = 0.0
        self.y: float = 0.0

    def getModifierState(self, keyArg: str) -> bool: ...

    def initMouseEvent(
        self,
        typeArg: str,
        bubblesArg: bool = False,
        cancelableArg: bool = False,
        viewArg: Window | None = None,
        detailArg: int = 0,
        screenXArg: int = 0,
        screenYArg: int = 0,
        clientXArg: int = 0,
        clientYArg: int = 0,
        ctrlKeyArg: bool = False,
        altKeyArg: bool = False,
        shiftKeyArg: bool = False,
        metaKeyArg: bool = False,
        buttonArg: int = 0,
        relatedTargetArg: EventTarget | None = None,
    ) -> None: ...


@js
class KeyboardEventInit(EventModifierInit):
    """WebIDL source: @webref/idl/uievents.idl"""

    def __init__(
        self,
        altKey: bool = False,
        bubbles: bool = False,
        cancelable: bool = False,
        charCode: int = 0,
        code: str = "",
        composed: bool = False,
        ctrlKey: bool = False,
        detail: int = 0,
        isComposing: bool = False,
        key: str = "",
        keyCode: int = 0,
        location: int = 0,
        metaKey: bool = False,
        modifierAltGraph: bool = False,
        modifierCapsLock: bool = False,
        modifierFn: bool = False,
        modifierFnLock: bool = False,
        modifierHyper: bool = False,
        modifierNumLock: bool = False,
        modifierScrollLock: bool = False,
        modifierSuper: bool = False,
        modifierSymbol: bool = False,
        modifierSymbolLock: bool = False,
        repeat: bool = False,
        shiftKey: bool = False,
        sourceCapabilities: InputDeviceCapabilities | None = None,
        view: Window | None = None,
        which: int = 0,
    ):
        self.altKey = altKey
        self.bubbles = bubbles
        self.cancelable = cancelable
        self.charCode = charCode
        self.code = code
        self.composed = composed
        self.ctrlKey = ctrlKey
        self.detail = detail
        self.isComposing = isComposing
        self.key = key
        self.keyCode = keyCode
        self.location = location
        self.metaKey = metaKey
        self.modifierAltGraph = modifierAltGraph
        self.modifierCapsLock = modifierCapsLock
        self.modifierFn = modifierFn
        self.modifierFnLock = modifierFnLock
        self.modifierHyper = modifierHyper
        self.modifierNumLock = modifierNumLock
        self.modifierScrollLock = modifierScrollLock
        self.modifierSuper = modifierSuper
        self.modifierSymbol = modifierSymbol
        self.modifierSymbolLock = modifierSymbolLock
        self.repeat = repeat
        self.shiftKey = shiftKey
        self.sourceCapabilities = sourceCapabilities
        self.view = view
        self.which = which


@js
class MouseEventInit(EventModifierInit):
    """WebIDL source: @webref/idl/pointerevents.idl"""

    def __init__(
        self,
        altKey: bool = False,
        bubbles: bool = False,
        button: int = 0,
        buttons: int = 0,
        cancelable: bool = False,
        clientX: int = 0,
        clientY: int = 0,
        composed: bool = False,
        ctrlKey: bool = False,
        detail: int = 0,
        metaKey: bool = False,
        modifierAltGraph: bool = False,
        modifierCapsLock: bool = False,
        modifierFn: bool = False,
        modifierFnLock: bool = False,
        modifierHyper: bool = False,
        modifierNumLock: bool = False,
        modifierScrollLock: bool = False,
        modifierSuper: bool = False,
        modifierSymbol: bool = False,
        modifierSymbolLock: bool = False,
        movementX: float = 0,
        movementY: float = 0,
        relatedTarget: EventTarget | None = None,
        screenX: int = 0,
        screenY: int = 0,
        shiftKey: bool = False,
        sourceCapabilities: InputDeviceCapabilities | None = None,
        view: Window | None = None,
        which: int = 0,
    ):
        self.altKey = altKey
        self.bubbles = bubbles
        self.button = button
        self.buttons = buttons
        self.cancelable = cancelable
        self.clientX = clientX
        self.clientY = clientY
        self.composed = composed
        self.ctrlKey = ctrlKey
        self.detail = detail
        self.metaKey = metaKey
        self.modifierAltGraph = modifierAltGraph
        self.modifierCapsLock = modifierCapsLock
        self.modifierFn = modifierFn
        self.modifierFnLock = modifierFnLock
        self.modifierHyper = modifierHyper
        self.modifierNumLock = modifierNumLock
        self.modifierScrollLock = modifierScrollLock
        self.modifierSuper = modifierSuper
        self.modifierSymbol = modifierSymbol
        self.modifierSymbolLock = modifierSymbolLock
        self.movementX = movementX
        self.movementY = movementY
        self.relatedTarget = relatedTarget
        self.screenX = screenX
        self.screenY = screenY
        self.shiftKey = shiftKey
        self.sourceCapabilities = sourceCapabilities
        self.view = view
        self.which = which


@js(builtin=True)
class PointerEvent(MouseEvent):
    """WebIDL source: @webref/idl/pointerevents.idl

    MDN: https://developer.mozilla.org/docs/Web/API/PointerEvent

    Browser support: Chrome 55, Safari 13"""

    def __init__(
        self,
        type: str,
        *,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        sourceCapabilities: InputDeviceCapabilities | None = None,
        view: Window | None = None,
        detail: int = 0,
        which: int = 0,
        ctrlKey: bool = False,
        shiftKey: bool = False,
        altKey: bool = False,
        metaKey: bool = False,
        modifierAltGraph: bool = False,
        modifierCapsLock: bool = False,
        modifierFn: bool = False,
        modifierFnLock: bool = False,
        modifierHyper: bool = False,
        modifierNumLock: bool = False,
        modifierScrollLock: bool = False,
        modifierSuper: bool = False,
        modifierSymbol: bool = False,
        modifierSymbolLock: bool = False,
        screenX: int = 0,
        screenY: int = 0,
        clientX: int = 0,
        clientY: int = 0,
        button: int = 0,
        buttons: int = 0,
        relatedTarget: EventTarget | None = None,
        movementX: float = 0,
        movementY: float = 0,
        pointerId: int = 0,
        width: float = 1,
        height: float = 1,
        pressure: float = 0,
        tangentialPressure: float = 0,
        tiltX: int | None = None,
        tiltY: int | None = None,
        twist: int = 0,
        altitudeAngle: float | None = None,
        azimuthAngle: float | None = None,
        pointerType: str = "",
        isPrimary: bool = False,
        persistentDeviceId: int = 0,
        coalescedEvents: list[PointerEvent] | None = None,
        predictedEvents: list[PointerEvent] | None = None,
    ):
        super().__init__(
            type,
            bubbles=bubbles,
            cancelable=cancelable,
            composed=composed,
            sourceCapabilities=sourceCapabilities,
            view=view,
            detail=detail,
            which=which,
            ctrlKey=ctrlKey,
            shiftKey=shiftKey,
            altKey=altKey,
            metaKey=metaKey,
            screenX=screenX,
            screenY=screenY,
            clientX=clientX,
            clientY=clientY,
            button=button,
            buttons=buttons,
            relatedTarget=relatedTarget,
            movementX=movementX,
            movementY=movementY,
        )
        self.altitudeAngle: float = altitudeAngle
        self.azimuthAngle: float = azimuthAngle
        self.height: float = height
        self.isPrimary: bool = isPrimary
        self.persistentDeviceId: int = persistentDeviceId
        self.pointerId: int = pointerId
        self.pointerType: str = pointerType
        self.pressure: float = pressure
        self.tangentialPressure: float = tangentialPressure
        self.tiltX: int = tiltX
        self.tiltY: int = tiltY
        self.twist: int = twist
        self.width: float = width

    def getCoalescedEvents(self) -> list[PointerEvent]: ...

    def getPredictedEvents(self) -> list[PointerEvent]: ...


@js(builtin=True)
class WheelEvent(MouseEvent):
    """WebIDL source: @webref/idl/pointerevents.idl

    MDN: https://developer.mozilla.org/docs/Web/API/WheelEvent

    Browser support: Chrome 1, Safari 3"""

    DOM_DELTA_LINE = 1
    DOM_DELTA_PAGE = 2
    DOM_DELTA_PIXEL = 0

    def __init__(
        self,
        type: str,
        *,
        bubbles: bool = False,
        cancelable: bool = False,
        composed: bool = False,
        sourceCapabilities: InputDeviceCapabilities | None = None,
        view: Window | None = None,
        detail: int = 0,
        which: int = 0,
        ctrlKey: bool = False,
        shiftKey: bool = False,
        altKey: bool = False,
        metaKey: bool = False,
        modifierAltGraph: bool = False,
        modifierCapsLock: bool = False,
        modifierFn: bool = False,
        modifierFnLock: bool = False,
        modifierHyper: bool = False,
        modifierNumLock: bool = False,
        modifierScrollLock: bool = False,
        modifierSuper: bool = False,
        modifierSymbol: bool = False,
        modifierSymbolLock: bool = False,
        screenX: int = 0,
        screenY: int = 0,
        clientX: int = 0,
        clientY: int = 0,
        button: int = 0,
        buttons: int = 0,
        relatedTarget: EventTarget | None = None,
        movementX: float = 0,
        movementY: float = 0,
        deltaX: float = 0.0,
        deltaY: float = 0.0,
        deltaZ: float = 0.0,
        deltaMode: int = 0,
        momentum: bool = False,
    ):
        super().__init__(
            type,
            bubbles=bubbles,
            cancelable=cancelable,
            composed=composed,
            sourceCapabilities=sourceCapabilities,
            view=view,
            detail=detail,
            which=which,
            ctrlKey=ctrlKey,
            shiftKey=shiftKey,
            altKey=altKey,
            metaKey=metaKey,
            screenX=screenX,
            screenY=screenY,
            clientX=clientX,
            clientY=clientY,
            button=button,
            buttons=buttons,
            relatedTarget=relatedTarget,
            movementX=movementX,
            movementY=movementY,
        )
        self.deltaMode: int = deltaMode
        self.deltaX: float = deltaX
        self.deltaY: float = deltaY
        self.deltaZ: float = deltaZ
        self.momentum: bool = momentum


@js
class PointerEventInit(MouseEventInit):
    """WebIDL source: @webref/idl/pointerevents.idl"""

    def __init__(
        self,
        altitudeAngle: float | None = None,
        altKey: bool = False,
        azimuthAngle: float | None = None,
        bubbles: bool = False,
        button: int = 0,
        buttons: int = 0,
        cancelable: bool = False,
        clientX: int = 0,
        clientY: int = 0,
        coalescedEvents: list[PointerEvent] | None = None,
        composed: bool = False,
        ctrlKey: bool = False,
        detail: int = 0,
        height: float = 1,
        isPrimary: bool = False,
        metaKey: bool = False,
        modifierAltGraph: bool = False,
        modifierCapsLock: bool = False,
        modifierFn: bool = False,
        modifierFnLock: bool = False,
        modifierHyper: bool = False,
        modifierNumLock: bool = False,
        modifierScrollLock: bool = False,
        modifierSuper: bool = False,
        modifierSymbol: bool = False,
        modifierSymbolLock: bool = False,
        movementX: float = 0,
        movementY: float = 0,
        persistentDeviceId: int = 0,
        pointerId: int = 0,
        pointerType: str = "",
        predictedEvents: list[PointerEvent] | None = None,
        pressure: float = 0,
        relatedTarget: EventTarget | None = None,
        screenX: int = 0,
        screenY: int = 0,
        shiftKey: bool = False,
        sourceCapabilities: InputDeviceCapabilities | None = None,
        tangentialPressure: float = 0,
        tiltX: int | None = None,
        tiltY: int | None = None,
        twist: int = 0,
        view: Window | None = None,
        which: int = 0,
        width: float = 1,
    ):
        self.altitudeAngle = altitudeAngle
        self.altKey = altKey
        self.azimuthAngle = azimuthAngle
        self.bubbles = bubbles
        self.button = button
        self.buttons = buttons
        self.cancelable = cancelable
        self.clientX = clientX
        self.clientY = clientY
        self.coalescedEvents = coalescedEvents
        self.composed = composed
        self.ctrlKey = ctrlKey
        self.detail = detail
        self.height = height
        self.isPrimary = isPrimary
        self.metaKey = metaKey
        self.modifierAltGraph = modifierAltGraph
        self.modifierCapsLock = modifierCapsLock
        self.modifierFn = modifierFn
        self.modifierFnLock = modifierFnLock
        self.modifierHyper = modifierHyper
        self.modifierNumLock = modifierNumLock
        self.modifierScrollLock = modifierScrollLock
        self.modifierSuper = modifierSuper
        self.modifierSymbol = modifierSymbol
        self.modifierSymbolLock = modifierSymbolLock
        self.movementX = movementX
        self.movementY = movementY
        self.persistentDeviceId = persistentDeviceId
        self.pointerId = pointerId
        self.pointerType = pointerType
        self.predictedEvents = predictedEvents
        self.pressure = pressure
        self.relatedTarget = relatedTarget
        self.screenX = screenX
        self.screenY = screenY
        self.shiftKey = shiftKey
        self.sourceCapabilities = sourceCapabilities
        self.tangentialPressure = tangentialPressure
        self.tiltX = tiltX
        self.tiltY = tiltY
        self.twist = twist
        self.view = view
        self.which = which
        self.width = width


@js
class WheelEventInit(MouseEventInit):
    """WebIDL source: @webref/idl/pointerevents.idl"""

    def __init__(
        self,
        altKey: bool = False,
        bubbles: bool = False,
        button: int = 0,
        buttons: int = 0,
        cancelable: bool = False,
        clientX: int = 0,
        clientY: int = 0,
        composed: bool = False,
        ctrlKey: bool = False,
        deltaMode: int = 0,
        deltaX: float = 0.0,
        deltaY: float = 0.0,
        deltaZ: float = 0.0,
        detail: int = 0,
        metaKey: bool = False,
        modifierAltGraph: bool = False,
        modifierCapsLock: bool = False,
        modifierFn: bool = False,
        modifierFnLock: bool = False,
        modifierHyper: bool = False,
        modifierNumLock: bool = False,
        modifierScrollLock: bool = False,
        modifierSuper: bool = False,
        modifierSymbol: bool = False,
        modifierSymbolLock: bool = False,
        momentum: bool = False,
        movementX: float = 0,
        movementY: float = 0,
        relatedTarget: EventTarget | None = None,
        screenX: int = 0,
        screenY: int = 0,
        shiftKey: bool = False,
        sourceCapabilities: InputDeviceCapabilities | None = None,
        view: Window | None = None,
        which: int = 0,
    ):
        self.altKey = altKey
        self.bubbles = bubbles
        self.button = button
        self.buttons = buttons
        self.cancelable = cancelable
        self.clientX = clientX
        self.clientY = clientY
        self.composed = composed
        self.ctrlKey = ctrlKey
        self.deltaMode = deltaMode
        self.deltaX = deltaX
        self.deltaY = deltaY
        self.deltaZ = deltaZ
        self.detail = detail
        self.metaKey = metaKey
        self.modifierAltGraph = modifierAltGraph
        self.modifierCapsLock = modifierCapsLock
        self.modifierFn = modifierFn
        self.modifierFnLock = modifierFnLock
        self.modifierHyper = modifierHyper
        self.modifierNumLock = modifierNumLock
        self.modifierScrollLock = modifierScrollLock
        self.modifierSuper = modifierSuper
        self.modifierSymbol = modifierSymbol
        self.modifierSymbolLock = modifierSymbolLock
        self.momentum = momentum
        self.movementX = movementX
        self.movementY = movementY
        self.relatedTarget = relatedTarget
        self.screenX = screenX
        self.screenY = screenY
        self.shiftKey = shiftKey
        self.sourceCapabilities = sourceCapabilities
        self.view = view
        self.which = which
