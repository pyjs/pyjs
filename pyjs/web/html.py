from pyjs import js
from pyjs.javascript import Float16Array, Uint8ClampedArray
from pyjs.web.dom import (
    CSSStyleProperties,
    Document,
    DocumentFragment,
    DOMRect,
    DOMTokenList,
    Element,
    HTMLCollection,
    Node,
    NodeList,
    ShadowRoot,
    Storage,
    Text,
    Window,
)
from pyjs.web.events import AbortSignal, Event, EventTarget, MessagePort
from pyjs.web.files import Blob, File, FileList
from pyjs.web.geometry import DOMMatrix, DOMMatrix2DInit, DOMPointInit
from pyjs.web.svg import SVGImageElement


@js.dictionary
class AssignedNodesOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, flatten: bool = False):
        self.flatten = flatten


@js.native
class AudioTrack:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/AudioTrack

    Browser support: Safari 8"""

    def __init__(self):
        self.enabled: bool = False
        self.id: str = ""
        self.kind: str = ""
        self.label: str = ""
        self.language: str = ""


@js.native
class AudioTrackList(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/AudioTrackList

    Browser support: Safari 7"""

    def __init__(self):
        super().__init__()
        self.length: int = 0
        self.onaddtrack: callable = None
        self.onchange: callable = None
        self.onremovetrack: callable = None

    @js.inline("{self}[{index}]")
    def __getitem__(self, index: int) -> AudioTrack: ...

    def getTrackById(self, id: str) -> AudioTrack | None: ...


@js.native
class BarProp:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/BarProp

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.visible: bool = False


@js.native
class BeforeUnloadEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/BeforeUnloadEvent

    Browser support: Chrome 30, Safari 7"""

    def __init__(self):
        super().__init__()
        self.returnValue: str = ""


@js.native
class BroadcastChannel(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/BroadcastChannel

    Browser support: Chrome 54, Safari 15.4"""

    def __init__(self, name: str):
        super().__init__()
        self.name: str = name
        self.onmessage: callable = None
        self.onmessageerror: callable = None

    def close(self) -> None: ...

    def postMessage(self, message: object) -> None: ...


@js.native
class CanvasGradient:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CanvasGradient

    Browser support: Chrome 1, Safari 2"""

    def addColorStop(self, offset: float, color: str) -> None: ...


@js.native
class CanvasPattern:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CanvasPattern

    Browser support: Chrome 1, Safari 2"""

    def setTransform(self, transform: DOMMatrix2DInit | None = None) -> None: ...


@js.native
class CanvasRenderingContext2D:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CanvasRenderingContext2D

    Browser support: Chrome 1, Safari 2"""

    pass

    def __init__(self):
        self.canvas: HTMLCanvasElement = None
        self.direction: str = ""
        self.fillStyle: str | CanvasGradient | CanvasPattern = None
        self.filter: str = ""
        self.font: str = ""
        self.fontKerning: str = ""
        self.fontStretch: str = ""
        self.fontVariantCaps: str = ""
        self.globalAlpha: float = 0.0
        self.globalCompositeOperation: str = ""
        self.imageSmoothingEnabled: bool = False
        self.imageSmoothingQuality: str = ""
        self.lang: str = ""
        self.letterSpacing: str = ""
        self.lineCap: str = ""
        self.lineDashOffset: float = 0.0
        self.lineJoin: str = ""
        self.lineWidth: float = 0.0
        self.miterLimit: float = 0.0
        self.shadowBlur: float = 0.0
        self.shadowColor: str = ""
        self.shadowOffsetX: float = 0.0
        self.shadowOffsetY: float = 0.0
        self.strokeStyle: str | CanvasGradient | CanvasPattern = None
        self.textAlign: str = ""
        self.textBaseline: str = ""
        self.textRendering: str = ""
        self.wordSpacing: str = ""

    def arc(
        self,
        x: float,
        y: float,
        radius: float,
        startAngle: float,
        endAngle: float,
        counterclockwise: bool = False,
    ) -> None: ...

    def arcTo(
        self, x1: float, y1: float, x2: float, y2: float, radius: float
    ) -> None: ...

    def beginPath(self) -> None: ...

    def bezierCurveTo(
        self, cp1x: float, cp1y: float, cp2x: float, cp2y: float, x: float, y: float
    ) -> None: ...

    def clearRect(self, x: float, y: float, w: float, h: float) -> None: ...

    def clip(self, fillRule: str = "nonzero") -> None: ...

    def closePath(self) -> None: ...

    def createConicGradient(
        self, startAngle: float, x: float, y: float
    ) -> CanvasGradient: ...

    def createImageData(
        self,
        sw: int,
        sh: int,
        *,
        colorSpace: str | None = None,
        pixelFormat: str = "rgba-unorm8",
    ) -> ImageData: ...

    def createLinearGradient(
        self, x0: float, y0: float, x1: float, y1: float
    ) -> CanvasGradient: ...

    def createPattern(
        self,
        image: HTMLImageElement
        | SVGImageElement
        | HTMLVideoElement
        | HTMLCanvasElement
        | ImageBitmap
        | OffscreenCanvas
        | VideoFrame,
        repetition: str,
    ) -> CanvasPattern | None: ...

    def createRadialGradient(
        self, x0: float, y0: float, r0: float, x1: float, y1: float, r1: float
    ) -> CanvasGradient: ...

    def drawFocusIfNeeded(self, element: Element) -> None: ...

    def drawImage(
        self,
        image: HTMLImageElement
        | SVGImageElement
        | HTMLVideoElement
        | HTMLCanvasElement
        | ImageBitmap
        | OffscreenCanvas
        | VideoFrame,
        dx: float,
        dy: float,
    ) -> None: ...

    def ellipse(
        self,
        x: float,
        y: float,
        radiusX: float,
        radiusY: float,
        rotation: float,
        startAngle: float,
        endAngle: float,
        counterclockwise: bool = False,
    ) -> None: ...

    def fill(self, fillRule: str = "nonzero") -> None: ...

    def fillRect(self, x: float, y: float, w: float, h: float) -> None: ...

    def fillText(
        self, text: str, x: float, y: float, maxWidth: float | None = None
    ) -> None: ...

    def getContextAttributes(self) -> CanvasRenderingContext2DSettings: ...

    def getImageData(
        self,
        sx: int,
        sy: int,
        sw: int,
        sh: int,
        *,
        colorSpace: str | None = None,
        pixelFormat: str = "rgba-unorm8",
    ) -> ImageData: ...

    def getLineDash(self) -> list[float]: ...

    def getTransform(self) -> DOMMatrix: ...

    def isContextLost(self) -> bool: ...

    def isPointInPath(self, x: float, y: float, fillRule: str = "nonzero") -> bool: ...

    def isPointInStroke(self, x: float, y: float) -> bool: ...

    def lineTo(self, x: float, y: float) -> None: ...

    def measureText(self, text: str) -> TextMetrics: ...

    def moveTo(self, x: float, y: float) -> None: ...

    def putImageData(self, imageData: ImageData, dx: int, dy: int) -> None: ...

    def quadraticCurveTo(self, cpx: float, cpy: float, x: float, y: float) -> None: ...

    def rect(self, x: float, y: float, w: float, h: float) -> None: ...

    def reset(self) -> None: ...

    def resetTransform(self) -> None: ...

    def restore(self) -> None: ...

    def rotate(self, angle: float) -> None: ...

    def roundRect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        radii: float | DOMPointInit | list[float | DOMPointInit] = 0,
    ) -> None: ...

    def save(self) -> None: ...

    def scale(self, x: float, y: float) -> None: ...

    def setLineDash(self, segments: list[float]) -> None: ...

    def setTransform(
        self, a: float, b: float, c: float, d: float, e: float, f: float
    ) -> None: ...

    def stroke(self) -> None: ...

    def strokeRect(self, x: float, y: float, w: float, h: float) -> None: ...

    def strokeText(
        self, text: str, x: float, y: float, maxWidth: float | None = None
    ) -> None: ...

    def transform(
        self, a: float, b: float, c: float, d: float, e: float, f: float
    ) -> None: ...

    def translate(self, x: float, y: float) -> None: ...


@js.dictionary
class CanvasRenderingContext2DSettings:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        alpha: bool = True,
        colorSpace: str = "srgb",
        colorType: str = "unorm8",
        desynchronized: bool = False,
        willReadFrequently: bool = False,
    ):
        self.alpha = alpha
        self.colorSpace = colorSpace
        self.colorType = colorType
        self.desynchronized = desynchronized
        self.willReadFrequently = willReadFrequently


@js.native
class CloseWatcher(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CloseWatcher

    Browser support: Chrome 126, Safari preview"""

    def __init__(self, *, signal: AbortSignal | None = None):
        super().__init__()
        self.oncancel: callable = None
        self.onclose: callable = None

    def close(self) -> None: ...

    def destroy(self) -> None: ...

    def requestClose(self) -> None: ...


@js.dictionary
class CloseWatcherOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, signal: AbortSignal | None = None):
        if signal is not None:
            self.signal = signal


@js.native
class CommandEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CommandEvent

    Browser support: Chrome 135, Safari 26.2"""

    def __init__(self, type: str, *, source: Element | None = None, command: str = ""):
        super().__init__()
        self.command: str = command
        self.source: Element | None = source


@js.dictionary
class CommandEventInit:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, command: str = "", source: Element | None = None):
        self.command = command
        self.source = source


@js.native
class CustomElementRegistry:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CustomElementRegistry

    Browser support: Chrome 54, Safari 10.1"""

    def __init__(self): ...

    def define(
        self, name: str, constructor: callable, *, extends: str | None = None
    ) -> None: ...

    def get(self, name: str) -> callable | None: ...

    def getName(self, constructor: callable) -> str | None: ...

    def initialize(self, root: Node) -> None: ...

    def upgrade(self, root: Node) -> None: ...

    async def whenDefined(self, name: str) -> callable: ...


customElements = CustomElementRegistry()
js.native(customElements)


@js.native
class CustomStateSet:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CustomStateSet

    Browser support: Chrome 90, Safari 17.4"""

    pass


@js.native
class DOMParser:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMParser

    Browser support: Chrome 1, Safari 1.3"""

    def __init__(self): ...

    def parseFromString(self, string: TrustedHTML | str, type: str) -> Document: ...


@js.native
class DOMStringList:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMStringList

    Browser support: Chrome 1, Safari 5.1"""

    def __init__(self):
        self.length: int = 0

    def contains(self, string: str) -> bool: ...

    def item(self, index: int) -> str | None: ...


@js.native
class DOMStringMap:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMStringMap

    Browser support: Chrome 7, Safari 5.1"""

    def __init__(self):
        self.map: dict[str, str] = {}

    @js.inline("delete {self}[{name}]")
    def __delitem__(self, name: str) -> None: ...

    @js.inline("{self}[{name}]")
    def __getitem__(self, name: str) -> str:
        return self.map[name]

    @js.inline("{self}[{name}] = {value}")
    def __setitem__(self, name: str, value: str) -> None:
        self.map[name] = value


@js.native
class EditContext(EventTarget):
    """WebIDL source: @webref/idl/edit-context.idl

    MDN: https://developer.mozilla.org/docs/Web/API/EditContext

    Browser support: Chrome 121"""

    pass


@js.dictionary
class ElementDefinitionOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, extends: str | None = None):
        self.extends = extends


@js.native
class ElementInternals:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ElementInternals

    Browser support: Chrome 77, Safari 16.4"""

    pass

    def __init__(self):
        self.form: HTMLFormElement | None = None
        self.labels: NodeList[Node] = None
        self.shadowRoot: ShadowRoot | None = None
        self.states: CustomStateSet = None
        self.validationMessage: str = ""
        self.validity: ValidityState = None
        self.willValidate: bool = False

    def checkValidity(self) -> bool: ...

    def reportValidity(self) -> bool: ...

    def setFormValue(
        self,
        value: File | str | FormData | None,
        state: File | str | FormData | None = None,
    ) -> None: ...

    def setValidity(
        self,
        flags: ValidityStateFlags | None = None,
        message: str | None = None,
        anchor: HTMLElement | None = None,
    ) -> None: ...


@js.native
class EventSource(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/EventSource

    Browser support: Chrome 6, Safari 5"""

    CLOSED = 2
    CONNECTING = 0
    OPEN = 1

    def __init__(self, url: str, *, withCredentials: bool = False):
        super().__init__()
        self.onerror: callable = None
        self.onmessage: callable = None
        self.onopen: callable = None
        self.readyState: int = 0
        self.url: str = url
        self.withCredentials: bool = withCredentials

    def close(self) -> None: ...


@js.dictionary
class EventSourceInit:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, withCredentials: bool = False):
        self.withCredentials = withCredentials


@js.native
class External:
    """WebIDL source: @webref/idl/html.idl

    Browser support: Chrome 1"""

    def AddSearchProvider(self) -> None: ...

    def IsSearchProviderInstalled(self) -> None: ...


@js.native
class FileSystemEntry:
    """WebIDL source: @webref/idl/entries-api.idl

    MDN: https://developer.mozilla.org/docs/Web/API/FileSystemEntry

    Browser support: Chrome 8, Safari 11.1"""

    pass


@js.dictionary
class FocusOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, focusVisible: bool | None = None, preventScroll: bool = False):
        self.focusVisible = focusVisible
        self.preventScroll = preventScroll


@js.native
class FormData:
    """WebIDL source: @webref/idl/xhr.idl

    MDN: https://developer.mozilla.org/docs/Web/API/FormData

    Browser support: Chrome 5, Safari 5"""

    pass


@js.native
class FormDataEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/FormDataEvent

    Browser support: Chrome 77, Safari 15"""

    def __init__(self, type: str, eventInitDict: FormDataEventInit):
        super().__init__()
        self.formData = eventInitDict.formData


@js.dictionary
class FormDataEventInit:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, formData: FormData):
        self.formData = formData


@js.dictionary
class GetHTMLOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        serializableShadowRoots: bool = False,
        shadowRoots: list[ShadowRoot] | None = None,
    ):
        self.serializableShadowRoots = serializableShadowRoots
        if shadowRoots is None:
            shadowRoots = []
        self.shadowRoots = shadowRoots


@js.native
class GPUCanvasContext:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUCanvasContext

    Browser support: Chrome 144, Safari 26"""

    pass


@js.native
class HashChangeEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HashChangeEvent

    Browser support: Chrome 8, Safari 5"""

    def __init__(self, type: str, *, oldURL: str = "", newURL: str = ""):
        super().__init__()
        self.newURL: str = newURL
        self.oldURL: str = oldURL


@js.dictionary
class HashChangeEventInit:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, newURL: str = "", oldURL: str = ""):
        self.newURL = newURL
        self.oldURL = oldURL


@js.native
class HTMLAllCollection:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLAllCollection

    Browser support: Chrome 5, Safari 5"""

    def __init__(self):
        self.length: int = 0

    @js.inline("{self}[{index}]")
    def __getitem__(self, index: int) -> Element: ...

    def item(
        self, nameOrIndex: str | None = None
    ) -> HTMLCollection[Element] | Element | None: ...

    def namedItem(self, name: str) -> HTMLCollection[Element] | Element | None: ...


@js.native
class HTMLElement(Element):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLElement

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.accessKey: str = ""
        self.accessKeyLabel: str = ""
        self.attributeStyleMap: StylePropertyMap = None
        self.autocapitalize: str = ""
        self.autocorrect: bool = False
        self.autofocus: bool = False
        self.contentEditable: str = ""
        self.dataset: DOMStringMap = DOMStringMap()
        self.dir: str = ""
        self.draggable: bool = False
        self.editContext: EditContext | None = None
        self.enterKeyHint: str = ""
        self.hidden: bool | float | str | None = None
        self.inert: bool = False
        self.innerText: str = ""
        self.inputMode: str = ""
        self.isContentEditable: bool = False
        self.lang: str = ""
        self.nonce: str = ""
        self.offsetHeight: int = 0
        self.offsetLeft: int = 0
        self.offsetParent: Element | None = None
        self.offsetTop: int = 0
        self.offsetWidth: int = 0
        self.onabort: callable = None
        self.onanimationcancel: callable = None
        self.onanimationend: callable = None
        self.onanimationiteration: callable = None
        self.onanimationstart: callable = None
        self.onauxclick: callable = None
        self.onbeforeinput: callable = None
        self.onbeforematch: callable = None
        self.onbeforetoggle: callable = None
        self.onbeforexrselect: callable = None
        self.onblur: callable = None
        self.oncancel: callable = None
        self.oncanplay: callable = None
        self.oncanplaythrough: callable = None
        self.onchange: callable = None
        self.onclick: callable = None
        self.onclose: callable = None
        self.oncommand: callable = None
        self.oncontextlost: callable = None
        self.oncontextmenu: callable = None
        self.oncontextrestored: callable = None
        self.oncopy: callable = None
        self.oncuechange: callable = None
        self.oncut: callable = None
        self.ondblclick: callable = None
        self.ondrag: callable = None
        self.ondragend: callable = None
        self.ondragenter: callable = None
        self.ondragleave: callable = None
        self.ondragover: callable = None
        self.ondragstart: callable = None
        self.ondrop: callable = None
        self.ondurationchange: callable = None
        self.onemptied: callable = None
        self.onended: callable = None
        self.onerror: callable | None = None
        self.onfencedtreeclick: callable = None
        self.onfocus: callable = None
        self.onformdata: callable = None
        self.ongotpointercapture: callable = None
        self.oninput: callable = None
        self.oninvalid: callable = None
        self.onkeydown: callable = None
        self.onkeypress: callable = None
        self.onkeyup: callable = None
        self.onload: callable = None
        self.onloadeddata: callable = None
        self.onloadedmetadata: callable = None
        self.onloadstart: callable = None
        self.onlostpointercapture: callable = None
        self.onmousedown: callable = None
        self.onmouseenter: callable = None
        self.onmouseleave: callable = None
        self.onmousemove: callable = None
        self.onmouseout: callable = None
        self.onmouseover: callable = None
        self.onmouseup: callable = None
        self.onpaste: callable = None
        self.onpause: callable = None
        self.onplay: callable = None
        self.onplaying: callable = None
        self.onpointercancel: callable = None
        self.onpointerdown: callable = None
        self.onpointerenter: callable = None
        self.onpointerleave: callable = None
        self.onpointermove: callable = None
        self.onpointerout: callable = None
        self.onpointerover: callable = None
        self.onpointerrawupdate: callable = None
        self.onpointerup: callable = None
        self.onprogress: callable = None
        self.onratechange: callable = None
        self.onreset: callable = None
        self.onresize: callable = None
        self.onscroll: callable = None
        self.onscrollend: callable = None
        self.onsecuritypolicyviolation: callable = None
        self.onseeked: callable = None
        self.onseeking: callable = None
        self.onselect: callable = None
        self.onselectionchange: callable = None
        self.onselectstart: callable = None
        self.onslotchange: callable = None
        self.onsnapchanged: callable = None
        self.onsnapchanging: callable = None
        self.onstalled: callable = None
        self.onsubmit: callable = None
        self.onsuspend: callable = None
        self.ontimeupdate: callable = None
        self.ontoggle: callable = None
        self.ontouchcancel: callable = None
        self.ontouchend: callable = None
        self.ontouchmove: callable = None
        self.ontouchstart: callable = None
        self.ontransitioncancel: callable = None
        self.ontransitionend: callable = None
        self.ontransitionrun: callable = None
        self.ontransitionstart: callable = None
        self.onvolumechange: callable = None
        self.onwaiting: callable = None
        self.onwebkitanimationend: callable = None
        self.onwebkitanimationiteration: callable = None
        self.onwebkitanimationstart: callable = None
        self.onwebkittransitionend: callable = None
        self.onwheel: callable = None
        self.outerText: str = ""
        self.popover: str | None = None
        self.scrollParent: Element | None = None
        self.spellcheck: bool = False
        self.style: CSSStyleProperties = CSSStyleProperties()
        self.scrollHeight = 0
        self.scrollTop = 0
        self.tabIndex: int = 0
        self.title: str = ""
        self.translate: bool = False
        self.virtualKeyboardPolicy: str = ""
        self.writingSuggestions: str = ""

    def attachInternals(self) -> ElementInternals: ...

    def blur(self) -> None: ...

    def click(self) -> None: ...

    def focus(
        self, *, preventScroll: bool = False, focusVisible: bool | None = None
    ) -> None: ...

    def getBoundingClientRect(self) -> DOMRect:
        return DOMRect()

    def hidePopover(self) -> None: ...

    def showPopover(self, *, source: HTMLElement | None = None) -> None: ...

    def togglePopover(
        self, *, source: HTMLElement | None = None, force: bool | None = None
    ) -> bool: ...


@js.native
class HTMLFormControlsCollection(HTMLCollection[Element]):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLFormControlsCollection

    Browser support: Chrome 1, Safari 3"""

    pass

    def namedItem(self, name: str) -> RadioNodeList | Element | None: ...


@js.native
class HTMLOptionsCollection(HTMLCollection[Element]):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLOptionsCollection

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.length: int = 0
        self.selectedIndex: int = 0

    @js.inline("{self}[{index}] = {option}")
    def __setitem__(self, index: int, option: HTMLOptionElement | None) -> None: ...

    def add(
        self,
        element: HTMLOptionElement | HTMLOptGroupElement,
        before: HTMLElement | int | None = None,
    ) -> None: ...

    def remove(self, index: int) -> None: ...


@js.native
class ImageBitmap:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ImageBitmap

    Browser support: Chrome 50, Safari 15"""

    def __init__(self):
        self.height: int = 0
        self.width: int = 0

    def close(self) -> None: ...


@js.dictionary
class ImageBitmapOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        colorSpaceConversion: str = "default",
        imageOrientation: str = "from-image",
        premultiplyAlpha: str = "default",
        resizeHeight: int | None = None,
        resizeQuality: str = "low",
        resizeWidth: int | None = None,
    ):
        self.colorSpaceConversion = colorSpaceConversion
        self.imageOrientation = imageOrientation
        self.premultiplyAlpha = premultiplyAlpha
        if resizeHeight is not None:
            self.resizeHeight = resizeHeight
        self.resizeQuality = resizeQuality
        if resizeWidth is not None:
            self.resizeWidth = resizeWidth


@js.native
class ImageBitmapRenderingContext:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ImageBitmapRenderingContext

    Browser support: Chrome 66, Safari 11.1"""

    pass

    def __init__(self):
        self.canvas: HTMLCanvasElement | OffscreenCanvas = None

    def transferFromImageBitmap(self, bitmap: ImageBitmap | None) -> None: ...


@js.dictionary
class ImageBitmapRenderingContextSettings:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, alpha: bool = True):
        self.alpha = alpha


@js.native
class ImageData:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ImageData

    Browser support: Chrome 1, Safari 3.1"""

    def __init__(
        self,
        sw: int,
        sh: int,
        *,
        colorSpace: str | None = None,
        pixelFormat: str = "rgba-unorm8",
    ):
        self.colorSpace: str = colorSpace
        self.data: Uint8ClampedArray | Float16Array = None
        self.height: int = 0
        self.pixelFormat: str = pixelFormat
        self.width: int = 0


@js.dictionary
class ImageDataSettings:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, colorSpace: str | None = None, pixelFormat: str = "rgba-unorm8"):
        if colorSpace is not None:
            self.colorSpace = colorSpace
        self.pixelFormat = pixelFormat


@js.dictionary
class ImageEncodeOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, quality: float | None = None, type: str = "image/png"):
        if quality is not None:
            self.quality = quality
        self.type = type


@js.native
class MediaError:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MediaError

    Browser support: Chrome 3, Safari 3.1"""

    MEDIA_ERR_ABORTED = 1
    MEDIA_ERR_DECODE = 3
    MEDIA_ERR_NETWORK = 2
    MEDIA_ERR_SRC_NOT_SUPPORTED = 4

    def __init__(self):
        self.code: int = 0
        self.message: str = ""


@js.native
class MediaSource(EventTarget):
    """WebIDL source: @webref/idl/media-source.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MediaSource

    Browser support: Chrome 31, Safari 8"""

    pass


@js.native
class MediaStream(EventTarget):
    """WebIDL source: @webref/idl/mediacapture-streams.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MediaStream

    Browser support: Chrome 55, Safari 11"""

    pass


@js.native
class MessageChannel:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MessageChannel

    Browser support: Chrome 2, Safari 5"""

    def __init__(self):
        self.port1: MessagePort = None
        self.port2: MessagePort = None


@js.native
class MimeType:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MimeType

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.description: str = ""
        self.enabledPlugin: Plugin = None
        self.suffixes: str = ""
        self.type: str = ""


@js.native
class MimeTypeArray:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MimeTypeArray

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.length: int = 0

    def item(self, index: int) -> MimeType | None: ...

    def namedItem(self, name: str) -> MimeType | None: ...


@js.native
class NavigateEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NavigateEvent

    Browser support: Chrome 102, Safari 26.2"""

    def __init__(self, type: str, eventInitDict: NavigateEventInit):
        super().__init__()
        self.canIntercept = eventInitDict.canIntercept
        self.destination = eventInitDict.destination
        self.downloadRequest = eventInitDict.downloadRequest
        self.formData = eventInitDict.formData
        self.hashChange = eventInitDict.hashChange
        self.hasUAVisualTransition = eventInitDict.hasUAVisualTransition
        self.info = getattr(eventInitDict, "info", None)
        self.navigationType = eventInitDict.navigationType
        self.signal = eventInitDict.signal
        self.sourceElement = eventInitDict.sourceElement
        self.userInitiated = eventInitDict.userInitiated

    def intercept(
        self,
        *,
        precommitHandler: callable | None = None,
        handler: callable | None = None,
        focusReset: str | None = None,
        scroll: str | None = None,
    ) -> None: ...

    def scroll(self) -> None: ...


@js.dictionary
class NavigateEventInit:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        destination: NavigationDestination,
        signal: AbortSignal,
        canIntercept: bool = False,
        downloadRequest: str | None = None,
        formData: FormData | None = None,
        hashChange: bool = False,
        hasUAVisualTransition: bool = False,
        info: object | None = None,
        navigationType: str = "push",
        sourceElement: Element | None = None,
        userInitiated: bool = False,
    ):
        self.destination = destination
        self.signal = signal
        self.canIntercept = canIntercept
        self.downloadRequest = downloadRequest
        self.formData = formData
        self.hashChange = hashChange
        self.hasUAVisualTransition = hasUAVisualTransition
        if info is not None:
            self.info = info
        self.navigationType = navigationType
        self.sourceElement = sourceElement
        self.userInitiated = userInitiated


@js.native
class Navigation(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Navigation

    Browser support: Chrome 102, Safari 26.2"""

    def __init__(self):
        super().__init__()
        self.activation: NavigationActivation | None = None
        self.canGoBack: bool = False
        self.canGoForward: bool = False
        self.currentEntry: NavigationHistoryEntry | None = None
        self.oncurrententrychange: callable = None
        self.onnavigate: callable = None
        self.onnavigateerror: callable = None
        self.onnavigatesuccess: callable = None
        self.transition: NavigationTransition | None = None

    def back(self, *, info: object | None = None) -> NavigationResult: ...

    def entries(self) -> list[NavigationHistoryEntry]: ...

    def forward(self, *, info: object | None = None) -> NavigationResult: ...

    def navigate(
        self,
        url: str,
        *,
        info: object | None = None,
        state: object | None = None,
        history: str = "auto",
    ) -> NavigationResult: ...

    def reload(
        self, *, info: object | None = None, state: object | None = None
    ) -> NavigationResult: ...

    def traverseTo(self, key: str, *, info: object | None = None) -> NavigationResult: ...

    def updateCurrentEntry(
        self, options: NavigationUpdateCurrentEntryOptions
    ) -> None: ...


@js.native
class NavigationActivation:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NavigationActivation

    Browser support: Chrome 123, Safari 26.2"""

    def __init__(self):
        self.entry: NavigationHistoryEntry = None
        self.navigationType: str = ""


@js.native
class NavigationCurrentEntryChangeEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NavigationCurrentEntryChangeEvent

    Browser support: Chrome 102, Safari 26.2"""

    def __init__(self, type: str, eventInitDict: NavigationCurrentEntryChangeEventInit):
        super().__init__()
        self.navigationType = eventInitDict.navigationType


@js.dictionary
class NavigationCurrentEntryChangeEventInit:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, from_: NavigationHistoryEntry, navigationType: str | None = None):
        self.from_ = from_
        self.navigationType = navigationType


@js.native
class NavigationDestination:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NavigationDestination

    Browser support: Chrome 102, Safari 26.2"""

    def __init__(self):
        self.id: str = ""
        self.index: int = 0
        self.key: str = ""
        self.sameDocument: bool = False
        self.url: str = ""

    def getState(self) -> object: ...


@js.native
class NavigationHistoryEntry(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NavigationHistoryEntry

    Browser support: Chrome 102, Safari 26.2"""

    def __init__(self):
        super().__init__()
        self.id: str = ""
        self.index: int = 0
        self.key: str = ""
        self.ondispose: callable = None
        self.sameDocument: bool = False
        self.url: str | None = None

    def getState(self) -> object: ...


@js.dictionary
class NavigationInterceptOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        focusReset: str | None = None,
        handler: callable | None = None,
        precommitHandler: callable | None = None,
        scroll: str | None = None,
    ):
        if focusReset is not None:
            self.focusReset = focusReset
        if handler is not None:
            self.handler = handler
        if precommitHandler is not None:
            self.precommitHandler = precommitHandler
        if scroll is not None:
            self.scroll = scroll


@js.dictionary
class NavigationOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, info: object | None = None):
        if info is not None:
            self.info = info


@js.native
class NavigationPrecommitController:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NavigationPrecommitController

    Browser support: Chrome 141"""

    def addHandler(self, handler: callable) -> None: ...

    def redirect(
        self,
        url: str,
        *,
        info: object | None = None,
        state: object | None = None,
        history: str = "auto",
    ) -> None: ...


@js.dictionary
class NavigationResult:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        committed: NavigationHistoryEntry | None = None,
        finished: NavigationHistoryEntry | None = None,
    ):
        if committed is not None:
            self.committed = committed
        if finished is not None:
            self.finished = finished


@js.native
class NavigationTransition:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NavigationTransition

    Browser support: Chrome 102, Safari 26.2"""

    def __init__(self):
        self.committed: None = None
        self.finished: None = None
        self.navigationType: str = ""
        self.to: NavigationDestination = None


@js.dictionary
class NavigationUpdateCurrentEntryOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, state: object):
        self.state = state


@js.native
class NotRestoredReasonDetails:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NotRestoredReasonDetails

    Browser support: Chrome 125"""

    def __init__(self):
        self.reason: str = ""

    def toJSON(self) -> object: ...


@js.native
class NotRestoredReasons:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NotRestoredReasons

    Browser support: Chrome 125"""

    def __init__(self):
        self.children: list[NotRestoredReasons] | None = None
        self.id: str | None = None
        self.name: str | None = None
        self.reasons: list[NotRestoredReasonDetails] | None = None
        self.src: str | None = None
        self.url: str | None = None

    def toJSON(self) -> object: ...


@js.native
class OffscreenCanvas(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/OffscreenCanvas

    Browser support: Chrome 69, Safari 16.4"""

    pass

    def __init__(self, width: int, height: int):
        super().__init__()
        self.height: int = height
        self.oncontextlost: callable = None
        self.oncontextrestored: callable = None
        self.width: int = width

    async def convertToBlob(
        self, *, type: str = "image/png", quality: float | None = None
    ) -> Blob: ...

    def getContext(
        self, contextId: str, options: object | None = None
    ) -> (
        OffscreenCanvasRenderingContext2D
        | ImageBitmapRenderingContext
        | WebGLRenderingContext
        | WebGL2RenderingContext
        | GPUCanvasContext
        | None
    ): ...

    def transferToImageBitmap(self) -> ImageBitmap: ...


@js.native
class OffscreenCanvasRenderingContext2D:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/OffscreenCanvasRenderingContext2D

    Browser support: Chrome 69, Safari 16.4"""

    def __init__(self):
        self.canvas: OffscreenCanvas = None
        self.direction: str = ""
        self.fillStyle: str | CanvasGradient | CanvasPattern = None
        self.filter: str = ""
        self.font: str = ""
        self.fontKerning: str = ""
        self.fontStretch: str = ""
        self.fontVariantCaps: str = ""
        self.globalAlpha: float = 0.0
        self.globalCompositeOperation: str = ""
        self.imageSmoothingEnabled: bool = False
        self.imageSmoothingQuality: str = ""
        self.lang: str = ""
        self.letterSpacing: str = ""
        self.lineCap: str = ""
        self.lineDashOffset: float = 0.0
        self.lineJoin: str = ""
        self.lineWidth: float = 0.0
        self.miterLimit: float = 0.0
        self.shadowBlur: float = 0.0
        self.shadowColor: str = ""
        self.shadowOffsetX: float = 0.0
        self.shadowOffsetY: float = 0.0
        self.strokeStyle: str | CanvasGradient | CanvasPattern = None
        self.textAlign: str = ""
        self.textBaseline: str = ""
        self.textRendering: str = ""
        self.wordSpacing: str = ""

    def arc(
        self,
        x: float,
        y: float,
        radius: float,
        startAngle: float,
        endAngle: float,
        counterclockwise: bool = False,
    ) -> None: ...

    def arcTo(
        self, x1: float, y1: float, x2: float, y2: float, radius: float
    ) -> None: ...

    def beginPath(self) -> None: ...

    def bezierCurveTo(
        self, cp1x: float, cp1y: float, cp2x: float, cp2y: float, x: float, y: float
    ) -> None: ...

    def clearRect(self, x: float, y: float, w: float, h: float) -> None: ...

    def clip(self, fillRule: str = "nonzero") -> None: ...

    def closePath(self) -> None: ...

    def createConicGradient(
        self, startAngle: float, x: float, y: float
    ) -> CanvasGradient: ...

    def createImageData(
        self,
        sw: int,
        sh: int,
        *,
        colorSpace: str | None = None,
        pixelFormat: str = "rgba-unorm8",
    ) -> ImageData: ...

    def createLinearGradient(
        self, x0: float, y0: float, x1: float, y1: float
    ) -> CanvasGradient: ...

    def createPattern(
        self,
        image: HTMLImageElement
        | SVGImageElement
        | HTMLVideoElement
        | HTMLCanvasElement
        | ImageBitmap
        | OffscreenCanvas
        | VideoFrame,
        repetition: str,
    ) -> CanvasPattern | None: ...

    def createRadialGradient(
        self, x0: float, y0: float, r0: float, x1: float, y1: float, r1: float
    ) -> CanvasGradient: ...

    def drawImage(
        self,
        image: HTMLImageElement
        | SVGImageElement
        | HTMLVideoElement
        | HTMLCanvasElement
        | ImageBitmap
        | OffscreenCanvas
        | VideoFrame,
        dx: float,
        dy: float,
    ) -> None: ...

    def ellipse(
        self,
        x: float,
        y: float,
        radiusX: float,
        radiusY: float,
        rotation: float,
        startAngle: float,
        endAngle: float,
        counterclockwise: bool = False,
    ) -> None: ...

    def fill(self, fillRule: str = "nonzero") -> None: ...

    def fillRect(self, x: float, y: float, w: float, h: float) -> None: ...

    def fillText(
        self, text: str, x: float, y: float, maxWidth: float | None = None
    ) -> None: ...

    def getContextAttributes(self) -> CanvasRenderingContext2DSettings: ...

    def getImageData(
        self,
        sx: int,
        sy: int,
        sw: int,
        sh: int,
        *,
        colorSpace: str | None = None,
        pixelFormat: str = "rgba-unorm8",
    ) -> ImageData: ...

    def getLineDash(self) -> list[float]: ...

    def getTransform(self) -> DOMMatrix: ...

    def isContextLost(self) -> bool: ...

    def isPointInPath(self, x: float, y: float, fillRule: str = "nonzero") -> bool: ...

    def isPointInStroke(self, x: float, y: float) -> bool: ...

    def lineTo(self, x: float, y: float) -> None: ...

    def measureText(self, text: str) -> TextMetrics: ...

    def moveTo(self, x: float, y: float) -> None: ...

    def putImageData(self, imageData: ImageData, dx: int, dy: int) -> None: ...

    def quadraticCurveTo(self, cpx: float, cpy: float, x: float, y: float) -> None: ...

    def rect(self, x: float, y: float, w: float, h: float) -> None: ...

    def reset(self) -> None: ...

    def resetTransform(self) -> None: ...

    def restore(self) -> None: ...

    def rotate(self, angle: float) -> None: ...

    def roundRect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        radii: float | DOMPointInit | list[float | DOMPointInit] = 0,
    ) -> None: ...

    def save(self) -> None: ...

    def scale(self, x: float, y: float) -> None: ...

    def setLineDash(self, segments: list[float]) -> None: ...

    def setTransform(
        self, a: float, b: float, c: float, d: float, e: float, f: float
    ) -> None: ...

    def stroke(self) -> None: ...

    def strokeRect(self, x: float, y: float, w: float, h: float) -> None: ...

    def strokeText(
        self, text: str, x: float, y: float, maxWidth: float | None = None
    ) -> None: ...

    def transform(
        self, a: float, b: float, c: float, d: float, e: float, f: float
    ) -> None: ...

    def translate(self, x: float, y: float) -> None: ...


@js.native
class Origin:
    """WebIDL source: @webref/idl/html.idl

    Browser support: Chrome 145, Safari 26.5"""

    def __init__(self):
        self.opaque: bool = False

    @staticmethod
    @js.inline("{self}.from({_args_joined})")
    def from_(value: object) -> Origin: ...

    def isSameOrigin(self, other: Origin) -> bool: ...

    def isSameSite(self, other: Origin) -> bool: ...


@js.native
class PageRevealEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/PageRevealEvent

    Browser support: Chrome 123, Safari 18.2"""

    def __init__(self, type: str, *, viewTransition: ViewTransition | None = None):
        super().__init__()
        self.viewTransition: ViewTransition | None = viewTransition


@js.dictionary
class PageRevealEventInit:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, viewTransition: ViewTransition | None = None):
        self.viewTransition = viewTransition


@js.native
class PageSwapEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/PageSwapEvent

    Browser support: Chrome 124, Safari 18.2"""

    def __init__(
        self,
        type: str,
        *,
        activation: NavigationActivation | None = None,
        viewTransition: ViewTransition | None = None,
    ):
        super().__init__()
        self.activation: NavigationActivation | None = activation
        self.viewTransition: ViewTransition | None = viewTransition


@js.dictionary
class PageSwapEventInit:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        activation: NavigationActivation | None = None,
        viewTransition: ViewTransition | None = None,
    ):
        self.activation = activation
        self.viewTransition = viewTransition


@js.native
class PageTransitionEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/PageTransitionEvent

    Browser support: Chrome 4, Safari 5"""

    def __init__(self, type: str, *, persisted: bool = False):
        super().__init__()
        self.persisted: bool = persisted


@js.dictionary
class PageTransitionEventInit:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, persisted: bool = False):
        self.persisted = persisted


@js.dictionary
class ParseHTMLUnsafeOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, sanitizer: Sanitizer | SanitizerConfig | str | None = None):
        if sanitizer is None:
            sanitizer = Sanitizer()
        self.sanitizer = sanitizer


@js.native
class Path2D:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Path2D

    Browser support: Chrome 36, Safari 8"""

    def __init__(self, path: Path2D | str | None = None): ...

    def addPath(self, path: Path2D, transform: DOMMatrix2DInit | None = None) -> None: ...

    def arc(
        self,
        x: float,
        y: float,
        radius: float,
        startAngle: float,
        endAngle: float,
        counterclockwise: bool = False,
    ) -> None: ...

    def arcTo(
        self, x1: float, y1: float, x2: float, y2: float, radius: float
    ) -> None: ...

    def bezierCurveTo(
        self, cp1x: float, cp1y: float, cp2x: float, cp2y: float, x: float, y: float
    ) -> None: ...

    def closePath(self) -> None: ...

    def ellipse(
        self,
        x: float,
        y: float,
        radiusX: float,
        radiusY: float,
        rotation: float,
        startAngle: float,
        endAngle: float,
        counterclockwise: bool = False,
    ) -> None: ...

    def lineTo(self, x: float, y: float) -> None: ...

    def moveTo(self, x: float, y: float) -> None: ...

    def quadraticCurveTo(self, cpx: float, cpy: float, x: float, y: float) -> None: ...

    def rect(self, x: float, y: float, w: float, h: float) -> None: ...

    def roundRect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        radii: float | DOMPointInit | list[float | DOMPointInit] = 0,
    ) -> None: ...


@js.native
class PerformanceEntry:
    """WebIDL source: @webref/idl/performance-timeline.idl

    MDN: https://developer.mozilla.org/docs/Web/API/PerformanceEntry

    Browser support: Chrome 46, Safari 11"""

    pass


@js.native
class PermissionsPolicy:
    """WebIDL source: @webref/idl/permissions-policy.idl

    Browser support: Chrome preview"""

    pass


@js.native
class Plugin:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Plugin

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.description: str = ""
        self.filename: str = ""
        self.length: int = 0
        self.name: str = ""

    def item(self, index: int) -> MimeType | None: ...

    def namedItem(self, name: str) -> MimeType | None: ...


@js.native
class PluginArray:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/PluginArray

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.length: int = 0

    def item(self, index: int) -> Plugin | None: ...

    def namedItem(self, name: str) -> Plugin | None: ...

    def refresh(self) -> None: ...


@js.native
class PopStateEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/PopStateEvent

    Browser support: Chrome 4, Safari 6"""

    def __init__(
        self,
        type: str,
        *,
        state: object | None = None,
        hasUAVisualTransition: bool = False,
    ):
        super().__init__()
        self.hasUAVisualTransition: bool = hasUAVisualTransition
        self.state: object = state


@js.dictionary
class PopStateEventInit:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, hasUAVisualTransition: bool = False, state: object | None = None):
        self.hasUAVisualTransition = hasUAVisualTransition
        self.state = state


@js.native
class RadioNodeList(NodeList[Node]):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/RadioNodeList

    Browser support: Chrome 21, Safari 7"""

    def __init__(self):
        super().__init__()
        self.value: str = ""


@js.native
class Sanitizer:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Sanitizer

    Browser support: Chrome 146"""

    def __init__(
        self,
        *,
        elements: list[str | SanitizerElementNamespaceWithAttributes] | None = None,
        removeElements: list[str | SanitizerElementNamespace] | None = None,
        replaceWithChildrenElements: list[str | SanitizerElementNamespace] | None = None,
        processingInstructions: list[str | SanitizerProcessingInstruction] | None = None,
        removeProcessingInstructions: list[str | SanitizerProcessingInstruction]
        | None = None,
        attributes: list[str | SanitizerAttributeNamespace] | None = None,
        removeAttributes: list[str | SanitizerAttributeNamespace] | None = None,
        comments: bool | None = None,
        dataAttributes: bool | None = None,
    ): ...

    def allowAttribute(self, *, name: str, namespace: str | None = None) -> bool: ...

    def allowElement(
        self,
        *,
        name: str,
        namespace: str | None = "http://www.w3.org/1999/xhtml",
        attributes: list[str | SanitizerAttributeNamespace] | None = None,
        removeAttributes: list[str | SanitizerAttributeNamespace] | None = None,
    ) -> bool: ...

    def allowProcessingInstruction(self, *, target: str) -> bool: ...

    def get(self) -> SanitizerConfig: ...

    def removeAttribute(self, *, name: str, namespace: str | None = None) -> bool: ...

    def removeElement(
        self, *, name: str, namespace: str | None = "http://www.w3.org/1999/xhtml"
    ) -> bool: ...

    def removeProcessingInstruction(self, *, target: str) -> bool: ...

    def removeUnsafe(self) -> bool: ...

    def replaceElementWithChildren(
        self, *, name: str, namespace: str | None = "http://www.w3.org/1999/xhtml"
    ) -> bool: ...

    def setComments(self, allow: bool) -> bool: ...

    def setDataAttributes(self, allow: bool) -> bool: ...


@js.dictionary
class SanitizerAttributeNamespace:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, name: str, namespace: str | None = None):
        self.name = name
        self.namespace = namespace


@js.dictionary
class SanitizerConfig:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        attributes: list[str | SanitizerAttributeNamespace] | None = None,
        comments: bool | None = None,
        dataAttributes: bool | None = None,
        elements: list[str | SanitizerElementNamespaceWithAttributes] | None = None,
        processingInstructions: list[str | SanitizerProcessingInstruction] | None = None,
        removeAttributes: list[str | SanitizerAttributeNamespace] | None = None,
        removeElements: list[str | SanitizerElementNamespace] | None = None,
        removeProcessingInstructions: list[str | SanitizerProcessingInstruction]
        | None = None,
        replaceWithChildrenElements: list[str | SanitizerElementNamespace] | None = None,
    ):
        if attributes is not None:
            self.attributes = attributes
        if comments is not None:
            self.comments = comments
        if dataAttributes is not None:
            self.dataAttributes = dataAttributes
        if elements is not None:
            self.elements = elements
        if processingInstructions is not None:
            self.processingInstructions = processingInstructions
        if removeAttributes is not None:
            self.removeAttributes = removeAttributes
        if removeElements is not None:
            self.removeElements = removeElements
        if removeProcessingInstructions is not None:
            self.removeProcessingInstructions = removeProcessingInstructions
        if replaceWithChildrenElements is not None:
            self.replaceWithChildrenElements = replaceWithChildrenElements


@js.dictionary
class SanitizerElementNamespace:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, name: str, namespace: str | None = "http://www.w3.org/1999/xhtml"):
        self.name = name
        self.namespace = namespace


@js.dictionary
class SanitizerProcessingInstruction:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, target: str):
        self.target = target


@js.dictionary
class SetHTMLOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, sanitizer: Sanitizer | SanitizerConfig | str = "default"):
        self.sanitizer = sanitizer


@js.dictionary
class SetHTMLUnsafeOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        runScripts: bool = False,
        sanitizer: Sanitizer | SanitizerConfig | str | None = None,
    ):
        self.runScripts = runScripts
        if sanitizer is None:
            sanitizer = Sanitizer()
        self.sanitizer = sanitizer


@js.native
class SharedWorker(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SharedWorker

    Browser support: Chrome 5, Safari 16"""

    def __init__(
        self,
        scriptURL: TrustedScriptURL | str,
        *,
        name: str = "",
        type: str = "classic",
        credentials: str = "same-origin",
        extendedLifetime: bool = False,
    ):
        super().__init__()
        self.onerror: callable = None
        self.port: MessagePort = None


@js.dictionary
class ShowPopoverOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, source: HTMLElement | None = None):
        self.source = source


@js.native
class StorageEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/StorageEvent

    Browser support: Chrome 1, Safari 4"""

    def __init__(
        self,
        type: str,
        *,
        key: str | None = None,
        oldValue: str | None = None,
        newValue: str | None = None,
        url: str = "",
        storageArea: Storage | None = None,
    ):
        super().__init__()
        self.key: str | None = key
        self.newValue: str | None = newValue
        self.oldValue: str | None = oldValue
        self.storageArea: Storage | None = storageArea
        self.url: str = url

    def initStorageEvent(
        self,
        type: str,
        bubbles: bool = False,
        cancelable: bool = False,
        key: str | None = None,
        oldValue: str | None = None,
        newValue: str | None = None,
        url: str = "",
        storageArea: Storage | None = None,
    ) -> None: ...


@js.dictionary
class StorageEventInit:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        key: str | None = None,
        newValue: str | None = None,
        oldValue: str | None = None,
        storageArea: Storage | None = None,
        url: str = "",
    ):
        self.key = key
        self.newValue = newValue
        self.oldValue = oldValue
        self.storageArea = storageArea
        self.url = url


@js.dictionary
class StructuredSerializeOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, transfer: list[object] | None = None):
        if transfer is None:
            transfer = []
        self.transfer = transfer


@js.native
class StylePropertyMapReadOnly:
    """WebIDL source: @webref/idl/css-typed-om.idl

    MDN: https://developer.mozilla.org/docs/Web/API/StylePropertyMapReadOnly

    Browser support: Chrome 66, Safari 16.4"""

    pass


@js.native
class SubmitEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SubmitEvent

    Browser support: Chrome 81, Safari 15"""

    def __init__(self, type: str, *, submitter: HTMLElement | None = None):
        super().__init__()
        self.submitter: HTMLElement | None = submitter


@js.dictionary
class SubmitEventInit:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, submitter: HTMLElement | None = None):
        self.submitter = submitter


@js.native
class TextMetrics:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TextMetrics

    Browser support: Chrome 2, Safari 4"""

    def __init__(self):
        self.actualBoundingBoxAscent: float = 0.0
        self.actualBoundingBoxDescent: float = 0.0
        self.actualBoundingBoxLeft: float = 0.0
        self.actualBoundingBoxRight: float = 0.0
        self.alphabeticBaseline: float = 0.0
        self.emHeightAscent: float = 0.0
        self.emHeightDescent: float = 0.0
        self.fontBoundingBoxAscent: float = 0.0
        self.fontBoundingBoxDescent: float = 0.0
        self.hangingBaseline: float = 0.0
        self.ideographicBaseline: float = 0.0
        self.width: float = 0.0


@js.native
class TextTrack(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TextTrack

    Browser support: Chrome 23, Safari 6"""

    def __init__(self):
        super().__init__()
        self.activeCues: TextTrackCueList | None = None
        self.cues: TextTrackCueList | None = None
        self.id: str = ""
        self.inBandMetadataTrackDispatchType: str = ""
        self.kind: str = ""
        self.label: str = ""
        self.language: str = ""
        self.mode: str = ""
        self.oncuechange: callable = None

    def addCue(self, cue: TextTrackCue) -> None: ...

    def removeCue(self, cue: TextTrackCue) -> None: ...


@js.native
class TextTrackCue(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TextTrackCue

    Browser support: Chrome 23, Safari 6"""

    def __init__(self):
        super().__init__()
        self.endTime: float = 0.0
        self.id: str = ""
        self.onenter: callable = None
        self.onexit: callable = None
        self.pauseOnExit: bool = False
        self.startTime: float = 0.0
        self.track: TextTrack | None = None


@js.native
class TextTrackCueList:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TextTrackCueList

    Browser support: Chrome 23, Safari 6"""

    def __init__(self):
        self.length: int = 0

    @js.inline("{self}[{index}]")
    def __getitem__(self, index: int) -> TextTrackCue: ...

    def getCueById(self, id: str) -> TextTrackCue | None: ...


@js.native
class TextTrackList(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TextTrackList

    Browser support: Chrome 23, Safari 6"""

    def __init__(self):
        super().__init__()
        self.length: int = 0
        self.onaddtrack: callable = None
        self.onchange: callable = None
        self.onremovetrack: callable = None

    @js.inline("{self}[{index}]")
    def __getitem__(self, index: int) -> TextTrack: ...

    def getTrackById(self, id: str) -> TextTrack | None: ...


@js.native
class TimeRanges:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TimeRanges

    Browser support: Chrome 6, Safari 3.1"""

    def __init__(self):
        self.length: int = 0

    def end(self, index: int) -> float: ...

    def start(self, index: int) -> float: ...


@js.native
class ToggleEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ToggleEvent

    Browser support: Chrome 114, Safari 17"""

    def __init__(
        self,
        type: str,
        *,
        oldState: str = "",
        newState: str = "",
        source: Element | None = None,
    ):
        super().__init__()
        self.newState: str = newState
        self.oldState: str = oldState
        self.source: Element | None = source


@js.dictionary
class ToggleEventInit:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self, newState: str = "", oldState: str = "", source: Element | None = None
    ):
        self.newState = newState
        self.oldState = oldState
        self.source = source


@js.native
class TrackEvent(Event):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TrackEvent

    Browser support: Chrome 23, Safari 6"""

    def __init__(
        self, type: str, *, track: VideoTrack | AudioTrack | TextTrack | None = None
    ):
        super().__init__()
        self.track: VideoTrack | AudioTrack | TextTrack | None = track


@js.dictionary
class TrackEventInit:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, track: VideoTrack | AudioTrack | TextTrack | None = None):
        self.track = track


@js.native
class TrustedHTML:
    """WebIDL source: @webref/idl/trusted-types.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TrustedHTML

    Browser support: Chrome 83, Safari 26"""

    pass


@js.native
class TrustedScript:
    """WebIDL source: @webref/idl/trusted-types.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TrustedScript

    Browser support: Chrome 83, Safari 26"""

    pass


@js.native
class TrustedScriptURL:
    """WebIDL source: @webref/idl/trusted-types.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TrustedScriptURL

    Browser support: Chrome 83, Safari 26"""

    pass


@js.native
class UserActivation:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/UserActivation

    Browser support: Chrome 72, Safari 16.4"""

    def __init__(self):
        self.hasBeenActive: bool = False
        self.isActive: bool = False


@js.native
class ValidityState:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ValidityState

    Browser support: Chrome 4, Safari 5"""

    pass

    def __init__(self):
        self.badInput: bool = False
        self.customError: bool = False
        self.patternMismatch: bool = False
        self.rangeOverflow: bool = False
        self.rangeUnderflow: bool = False
        self.stepMismatch: bool = False
        self.tooLong: bool = False
        self.tooShort: bool = False
        self.typeMismatch: bool = False
        self.valid: bool = False
        self.valueMissing: bool = False


@js.dictionary
class ValidityStateFlags:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        badInput: bool = False,
        customError: bool = False,
        patternMismatch: bool = False,
        rangeOverflow: bool = False,
        rangeUnderflow: bool = False,
        stepMismatch: bool = False,
        tooLong: bool = False,
        tooShort: bool = False,
        typeMismatch: bool = False,
        valueMissing: bool = False,
    ):
        self.badInput = badInput
        self.customError = customError
        self.patternMismatch = patternMismatch
        self.rangeOverflow = rangeOverflow
        self.rangeUnderflow = rangeUnderflow
        self.stepMismatch = stepMismatch
        self.tooLong = tooLong
        self.tooShort = tooShort
        self.typeMismatch = typeMismatch
        self.valueMissing = valueMissing


@js.native
class VideoFrame:
    """WebIDL source: @webref/idl/webcodecs.idl

    MDN: https://developer.mozilla.org/docs/Web/API/VideoFrame

    Browser support: Chrome 94, Safari 16.4"""

    pass


@js.native
class VideoTrack:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/VideoTrack

    Browser support: Safari 7"""

    def __init__(self):
        self.id: str = ""
        self.kind: str = ""
        self.label: str = ""
        self.language: str = ""
        self.selected: bool = False


@js.native
class VideoTrackList(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/VideoTrackList

    Browser support: Safari 7"""

    def __init__(self):
        super().__init__()
        self.length: int = 0
        self.onaddtrack: callable = None
        self.onchange: callable = None
        self.onremovetrack: callable = None
        self.selectedIndex: int = 0

    @js.inline("{self}[{index}]")
    def __getitem__(self, index: int) -> VideoTrack: ...

    def getTrackById(self, id: str) -> VideoTrack | None: ...


@js.native
class ViewTransition:
    """WebIDL source: @webref/idl/css-view-transitions.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ViewTransition

    Browser support: Chrome 111, Safari 18"""

    pass


@js.native
class WebGL2RenderingContext:
    """WebIDL source: @webref/idl/webgl2.idl

    MDN: https://developer.mozilla.org/docs/Web/API/WebGL2RenderingContext

    Browser support: Chrome 56, Safari 15"""

    pass


@js.native
class WebGLRenderingContext:
    """WebIDL source: @webref/idl/webgl1.idl

    MDN: https://developer.mozilla.org/docs/Web/API/WebGLRenderingContext

    Browser support: Chrome 9, Safari 5.1"""

    pass


@js.native
class Worker(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Worker

    Browser support: Chrome 2, Safari 4"""

    def __init__(
        self,
        scriptURL: TrustedScriptURL | str,
        *,
        name: str = "",
        type: str = "classic",
        credentials: str = "same-origin",
    ):
        super().__init__()
        self.onerror: callable = None
        self.onmessage: callable = None
        self.onmessageerror: callable = None

    def postMessage(self, message: object, transfer: list[object]) -> None: ...

    def terminate(self) -> None: ...


@js.native
class WorkerGlobalScope(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/WorkerGlobalScope

    Browser support: Chrome 4, Safari 4"""

    def __init__(self):
        super().__init__()
        self.crossOriginIsolated: bool = False
        self.isSecureContext: bool = False
        self.location: WorkerLocation = None
        self.navigator: WorkerNavigator = None
        self.onerror: callable | None = None
        self.onlanguagechange: callable = None
        self.onoffline: callable = None
        self.ononline: callable = None
        self.onrejectionhandled: callable = None
        self.onunhandledrejection: callable = None
        self.origin: str = ""
        self.self: WorkerGlobalScope = None

    def atob(self, data: str) -> str: ...

    def btoa(self, data: str) -> str: ...

    def clearInterval(self, id: int = 0) -> None: ...

    def clearTimeout(self, id: int = 0) -> None: ...

    async def createImageBitmap(
        self,
        image: HTMLImageElement
        | SVGImageElement
        | HTMLVideoElement
        | HTMLCanvasElement
        | ImageBitmap
        | OffscreenCanvas
        | VideoFrame
        | Blob
        | ImageData,
        *,
        imageOrientation: str = "from-image",
        premultiplyAlpha: str = "default",
        colorSpaceConversion: str = "default",
        resizeWidth: int | None = None,
        resizeHeight: int | None = None,
        resizeQuality: str = "low",
    ) -> ImageBitmap: ...

    def importScripts(self, *urls: TrustedScriptURL | str) -> None: ...

    def queueMicrotask(self, callback: callable) -> None: ...

    def reportError(self, e: object) -> None: ...

    def setInterval(
        self,
        handler: str | callable | TrustedScript,
        timeout: int = 0,
        *arguments: object,
    ) -> int: ...

    def setTimeout(
        self,
        handler: str | callable | TrustedScript,
        timeout: int = 0,
        *arguments: object,
    ) -> int: ...

    def structuredClone(
        self, value: object, *, transfer: list[object] | None = None
    ) -> object: ...


@js.native
class WorkerLocation:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/WorkerLocation

    Browser support: Chrome 4, Safari 4"""

    def __init__(self):
        self.hash: str = ""
        self.host: str = ""
        self.hostname: str = ""
        self.href: str = ""
        self.origin: str = ""
        self.pathname: str = ""
        self.port: str = ""
        self.protocol: str = ""
        self.search: str = ""


@js.native
class WorkerNavigator:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/WorkerNavigator

    Browser support: Chrome 4, Safari 4"""

    def __init__(self):
        self.appCodeName: str = ""
        self.appName: str = ""
        self.appVersion: str = ""
        self.hardwareConcurrency: int = 0
        self.language: str = ""
        self.languages: list[str] = []
        self.onLine: bool = False
        self.oscpu: str = ""
        self.platform: str = ""
        self.product: str = ""
        self.productSub: str = ""
        self.userAgent: str = ""
        self.vendor: str = ""
        self.vendorSub: str = ""

    def taintEnabled(self) -> bool: ...


@js.dictionary
class WorkerOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self, credentials: str = "same-origin", name: str = "", type: str = "classic"
    ):
        self.credentials = credentials
        self.name = name
        self.type = type


@js.native
class Worklet:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Worklet

    Browser support: Chrome 65, Safari 14.1"""

    async def addModule(
        self, moduleURL: str, *, credentials: str = "same-origin"
    ) -> None: ...


@js.native
class WorkletGlobalScope:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/WorkletGlobalScope

    Browser support: Chrome 65, Safari 14.1"""

    pass


@js.dictionary
class WorkletOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, credentials: str = "same-origin"):
        self.credentials = credentials


@js.native
class XMLSerializer:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/XMLSerializer

    Browser support: Chrome 1, Safari 3"""

    def __init__(self): ...

    def serializeToString(self, root: Node) -> str: ...


@js.dictionary
class NavigationNavigateOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        history: str = "auto",
        info: object | None = None,
        state: object | None = None,
    ):
        self.history = history
        if info is not None:
            self.info = info
        if state is not None:
            self.state = state


@js.dictionary
class NavigationReloadOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, info: object | None = None, state: object | None = None):
        if info is not None:
            self.info = info
        if state is not None:
            self.state = state


@js.dictionary
class SanitizerElementNamespaceWithAttributes:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        name: str,
        attributes: list[str | SanitizerAttributeNamespace] | None = None,
        namespace: str | None = "http://www.w3.org/1999/xhtml",
        removeAttributes: list[str | SanitizerAttributeNamespace] | None = None,
    ):
        self.name = name
        if attributes is not None:
            self.attributes = attributes
        self.namespace = namespace
        if removeAttributes is not None:
            self.removeAttributes = removeAttributes


@js.dictionary
class SharedWorkerOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(
        self,
        credentials: str = "same-origin",
        extendedLifetime: bool = False,
        name: str = "",
        type: str = "classic",
    ):
        self.credentials = credentials
        self.extendedLifetime = extendedLifetime
        self.name = name
        self.type = type


@js.dictionary
class TogglePopoverOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, force: bool | None = None, source: HTMLElement | None = None):
        self.force = force
        self.source = source


@js.dictionary
class WindowPostMessageOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, targetOrigin: str = "/", transfer: list[object] | None = None):
        self.targetOrigin = targetOrigin
        if transfer is None:
            transfer = []
        self.transfer = transfer


@js.native
class HTMLDataListElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLDataListElement

    Browser support: Chrome 20, Safari 12.1"""

    pass

    def __init__(self):
        super().__init__()
        self.options: HTMLCollection[Element] = None


@js.native
class HTMLDataElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLDataElement

    Browser support: Chrome 62, Safari 10"""

    def __init__(self):
        super().__init__()
        self.value: str = ""


@js.native
class HTMLTimeElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLTimeElement

    Browser support: Chrome 62, Safari 10"""

    def __init__(self):
        super().__init__()
        self.dateTime: str = ""


@js.native
class HTMLTitleElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLTitleElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.text: str = ""


@js.native
class HTMLTrackElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLTrackElement

    Browser support: Chrome 23, Safari 6"""

    ERROR = 3
    LOADED = 2
    LOADING = 1
    NONE = 0

    def __init__(self):
        super().__init__()
        self.default: bool = False
        self.kind: str = ""
        self.label: str = ""
        self.readyState: int = 0
        self.src: str = ""
        self.srclang: str = ""
        self.track: TextTrack = None


@js.native
class HTMLUListElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLUListElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.compact: bool = False
        self.type: str = ""


@js.native
class HTMLUnknownElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLUnknownElement

    Browser support: Chrome 15, Safari 6"""

    pass


@js.native
class StylePropertyMap(StylePropertyMapReadOnly):
    """WebIDL source: @webref/idl/css-typed-om.idl

    MDN: https://developer.mozilla.org/docs/Web/API/StylePropertyMap

    Browser support: Chrome 66, Safari 16.4"""

    pass


@js.native
class SharedWorkerGlobalScope(WorkerGlobalScope):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SharedWorkerGlobalScope

    Browser support: Chrome 4, Safari 16"""

    def __init__(self):
        super().__init__()
        self.name: str = ""
        self.onconnect: callable = None

    def close(self) -> None: ...


@js.native
class DedicatedWorkerGlobalScope(WorkerGlobalScope):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DedicatedWorkerGlobalScope

    Browser support: Chrome 4, Safari 4"""

    def __init__(self):
        super().__init__()
        self.name: str = ""
        self.onmessage: callable = None
        self.onmessageerror: callable = None

    def cancelAnimationFrame(self, handle: int) -> None: ...

    def close(self) -> None: ...

    def postMessage(self, message: object, transfer: list[object]) -> None: ...

    def requestAnimationFrame(self, callback: callable) -> int: ...


@js.native
class HTMLAnchorElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLAnchorElement

    Browser support: Chrome 1, Safari 1"""

    tagName = nodeName = "A"

    def __init__(self):
        super().__init__()
        self.attributionSourceId: int = 0
        self.charset: str = ""
        self.coords: str = ""
        self.download: str = ""
        self.hash: str = ""
        self.host: str = ""
        self.hostname: str = ""
        self.href: str = ""
        self.hreflang: str = ""
        self.name: str = ""
        self.origin: str = ""
        self.password: str = ""
        self.pathname: str = ""
        self.ping: str = ""
        self.port: str = ""
        self.protocol: str = ""
        self.referrerPolicy: str = ""
        self.rel: str = ""
        self.relList: DOMTokenList = None
        self.rev: str = ""
        self.search: str = ""
        self.shape: str = ""
        self.target: str = ""
        self.text: str = ""
        self.type: str = ""
        self.username: str = ""


@js.native
class HTMLAreaElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLAreaElement

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.alt: str = ""
        self.coords: str = ""
        self.download: str = ""
        self.hash: str = ""
        self.host: str = ""
        self.hostname: str = ""
        self.href: str = ""
        self.noHref: bool = False
        self.origin: str = ""
        self.password: str = ""
        self.pathname: str = ""
        self.ping: str = ""
        self.port: str = ""
        self.protocol: str = ""
        self.referrerPolicy: str = ""
        self.rel: str = ""
        self.relList: DOMTokenList = None
        self.search: str = ""
        self.shape: str = ""
        self.target: str = ""
        self.username: str = ""


@js.native
class HTMLBaseElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLBaseElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.href: str = ""
        self.target: str = ""


@js.native
class HTMLBodyElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLBodyElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.aLink: str = ""
        self.background: str = ""
        self.bgColor: str = ""
        self.link: str = ""
        self.onafterprint: callable = None
        self.onbeforeprint: callable = None
        self.onbeforeunload: callable | None = None
        self.onhashchange: callable = None
        self.onlanguagechange: callable = None
        self.onmessage: callable = None
        self.onmessageerror: callable = None
        self.onoffline: callable = None
        self.ononline: callable = None
        self.onpagehide: callable = None
        self.onpagereveal: callable = None
        self.onpageshow: callable = None
        self.onpageswap: callable = None
        self.onpopstate: callable = None
        self.onrejectionhandled: callable = None
        self.onstorage: callable = None
        self.onunhandledrejection: callable = None
        self.onunload: callable = None
        self.text: str = ""
        self.vLink: str = ""


@js.native
class HTMLBRElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLBRElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.clear: str = ""


@js.native
class HTMLButtonElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLButtonElement

    Browser support: Chrome 1, Safari 3"""

    tagName = nodeName = "BUTTON"

    def __init__(self):
        super().__init__()
        self.command: str = ""
        self.commandForElement: Element | None = None
        self.disabled: bool = False
        self.form: HTMLFormElement | None = None
        self.formAction: str = ""
        self.formEnctype: str = ""
        self.formMethod: str = ""
        self.formNoValidate: bool = False
        self.formTarget: str = ""
        self.labels: NodeList[Node] = None
        self.name: str = ""
        self.popoverTargetAction: str = ""
        self.popoverTargetElement: Element | None = None
        self.type: str = ""
        self.validationMessage: str = ""
        self.validity: ValidityState = None
        self.value: str = ""
        self.willValidate: bool = False

    def checkValidity(self) -> bool: ...

    def reportValidity(self) -> bool: ...

    def setCustomValidity(self, error: str) -> None: ...


@js.native
class HTMLCanvasElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLCanvasElement

    Browser support: Chrome 1, Safari 2"""

    tagName = nodeName = "CANVAS"

    def __init__(self):
        super().__init__()
        self.height: int = 150
        self.width: int = 300

    def captureStream(self, frameRequestRate: float | None = None) -> MediaStream: ...

    def getContext(
        self, contextId: str, options: object | None = None
    ) -> (
        CanvasRenderingContext2D
        | ImageBitmapRenderingContext
        | WebGLRenderingContext
        | WebGL2RenderingContext
        | GPUCanvasContext
        | None
    ): ...

    def toBlob(
        self, callback: callable, type: str = "image/png", quality: object | None = None
    ) -> None: ...

    def toDataURL(
        self, type: str = "image/png", quality: object | None = None
    ) -> str: ...

    def transferControlToOffscreen(self) -> OffscreenCanvas: ...


@js.native
class HTMLDetailsElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLDetailsElement

    Browser support: Chrome 10, Safari 6"""

    def __init__(self):
        super().__init__()
        self.name: str = ""
        self.open: bool = False


@js.native
class HTMLDialogElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLDialogElement

    Browser support: Chrome 37, Safari 15.4"""

    tagName = nodeName = "DIALOG"

    def __init__(self):
        super().__init__()
        self.closedBy: str = ""
        self.open: bool = False
        self.returnValue: str = ""

    def close(self, returnValue: str | None = None) -> None: ...

    def requestClose(self, returnValue: str | None = None) -> None: ...

    def show(self) -> None: ...

    def showModal(self) -> None: ...


@js.native
class HTMLDirectoryElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.compact: bool = False


@js.native
class HTMLDivElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLDivElement

    Browser support: Chrome 1, Safari 3"""

    tagName = nodeName = "DIV"

    def __init__(self):
        super().__init__()
        self.align: str = "left"


@js.native
class HTMLDListElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLDListElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.compact: bool = False


@js.native
class HTMLEmbedElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLEmbedElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.align: str = ""
        self.height: str = ""
        self.name: str = ""
        self.src: str = ""
        self.type: str = ""
        self.width: str = ""

    def getSVGDocument(self) -> Document | None: ...


@js.native
class HTMLFieldSetElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLFieldSetElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.disabled: bool = False
        self.elements: HTMLCollection[Element] = None
        self.form: HTMLFormElement | None = None
        self.name: str = ""
        self.type: str = ""
        self.validationMessage: str = ""
        self.validity: ValidityState = None
        self.willValidate: bool = False

    def checkValidity(self) -> bool: ...

    def reportValidity(self) -> bool: ...

    def setCustomValidity(self, error: str) -> None: ...


@js.native
class HTMLFontElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLFontElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.color: str = ""
        self.face: str = ""
        self.size: str = ""


@js.native
class HTMLFormElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLFormElement

    Browser support: Chrome 1, Safari 3"""

    tagName = nodeName = "FORM"

    def __init__(self):
        super().__init__()
        self.acceptCharset: str = ""
        self.action: str = ""
        self.autocomplete: str = ""
        self.elements: HTMLFormControlsCollection = None
        self.encoding: str = ""
        self.enctype: str = ""
        self.length: int = 0
        self.method: str = ""
        self.name: str = ""
        self.noValidate: bool = False
        self.rel: str = ""
        self.relList: DOMTokenList = None
        self.target: str = ""

    @js.inline("{self}[{index}]")
    def __getitem__(self, index: int) -> Element: ...

    def checkValidity(self) -> bool: ...

    def reportValidity(self) -> bool: ...

    def requestSubmit(self, submitter: HTMLElement | None = None) -> None: ...

    def reset(self) -> None: ...

    def submit(self) -> None: ...


@js.native
class HTMLFrameElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.contentDocument: Document | None = None
        self.contentWindow: Window | None = None
        self.frameBorder: str = ""
        self.longDesc: str = ""
        self.marginHeight: str = ""
        self.marginWidth: str = ""
        self.name: str = ""
        self.noResize: bool = False
        self.scrolling: str = ""
        self.src: str = ""


@js.native
class HTMLFrameSetElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLFrameSetElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.cols: str = ""
        self.onafterprint: callable = None
        self.onbeforeprint: callable = None
        self.onbeforeunload: callable | None = None
        self.onhashchange: callable = None
        self.onlanguagechange: callable = None
        self.onmessage: callable = None
        self.onmessageerror: callable = None
        self.onoffline: callable = None
        self.ononline: callable = None
        self.onpagehide: callable = None
        self.onpagereveal: callable = None
        self.onpageshow: callable = None
        self.onpageswap: callable = None
        self.onpopstate: callable = None
        self.onrejectionhandled: callable = None
        self.onstorage: callable = None
        self.onunhandledrejection: callable = None
        self.onunload: callable = None
        self.rows: str = ""


@js.native
class HTMLHeadElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLHeadElement

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()


@js.native
class HTMLHeadingElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLHeadingElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.align: str = ""


@js.native
class HTMLHRElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLHRElement

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.align: str = ""
        self.color: str = ""
        self.noShade: bool = False
        self.size: str = ""
        self.width: str = ""


@js.native
class HTMLHtmlElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLHtmlElement

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.version: str = ""


@js.native
class HTMLIFrameElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLIFrameElement

    Browser support: Chrome 1, Safari 3"""

    tagName = nodeName = "IFRAME"

    def __init__(self):
        super().__init__()
        self.align: str = ""
        self.allow: str = ""
        self.allowFullscreen: bool = False
        self.contentDocument: Document | None = None
        self.contentWindow: Window | None = None
        self.credentialless: bool = False
        self.csp: str = ""
        self.frameBorder: str = ""
        self.height: str = ""
        self.loading: str = ""
        self.longDesc: str = ""
        self.marginHeight: str = ""
        self.marginWidth: str = ""
        self.name: str = ""
        self.permissionsPolicy: PermissionsPolicy = None
        self.privateToken: str = ""
        self.referrerPolicy: str = ""
        self.sandbox: DOMTokenList = None
        self.scrolling: str = ""
        self.src: str = ""
        self.srcdoc: TrustedHTML | str = None
        self.width: str = ""

    def getSVGDocument(self) -> Document | None: ...


@js.native
class HTMLImageElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLImageElement

    Browser support: Chrome 1, Safari 1"""

    tagName = nodeName = "IMG"

    def __init__(self):
        super().__init__()
        self.align: str = ""
        self.alt: str = ""
        self.border: str = ""
        self.complete: bool = False
        self.controls: bool = False
        self.crossOrigin: str | None = None
        self.currentSrc: str = ""
        self.decoding: str = ""
        self.fetchPriority: str = ""
        self.height: int = 0
        self.hspace: int = 0
        self.isMap: bool = False
        self.loading: str = ""
        self.longDesc: str = ""
        self.lowsrc: str = ""
        self.name: str = ""
        self.naturalHeight: int = 0
        self.naturalWidth: int = 0
        self.referrerPolicy: str = ""
        self.sizes: str = ""
        self.src: str = ""
        self.srcset: str = ""
        self.useMap: str = ""
        self.vspace: int = 0
        self.width: int = 0
        self.x: int = 0
        self.y: int = 0

    async def decode(self) -> None: ...


@js.native
class HTMLInputElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLInputElement

    Browser support: Chrome 1, Safari 1"""

    tagName = nodeName = "INPUT"

    def __init__(self):
        super().__init__()
        self.accept: str = ""
        self.align: str = ""
        self.alpha: bool = False
        self.alt: str = ""
        self.autocomplete: str = ""
        self.checked: bool = False
        self.colorSpace: str = ""
        self.defaultChecked: bool = False
        self.defaultValue: str = ""
        self.dirName: str = ""
        self.disabled: bool = False
        self.files: FileList | None = None
        self.form: HTMLFormElement | None = None
        self.formAction: str = ""
        self.formEnctype: str = ""
        self.formMethod: str = ""
        self.formNoValidate: bool = False
        self.formTarget: str = ""
        self.height: int = 0
        self.indeterminate: bool = False
        self.labels: NodeList[Node] | None = None
        self.list: HTMLDataListElement | None = None
        self.max: str = ""
        self.maxLength: int = 0
        self.min: str = ""
        self.minLength: int = 0
        self.multiple: bool = False
        self.name: str = ""
        self.pattern: str = ""
        self.placeholder: str = ""
        self.popoverTargetAction: str = ""
        self.popoverTargetElement: Element | None = None
        self.readOnly: bool = False
        self.required: bool = False
        self.selectionDirection: str | None = None
        self.selectionEnd: int | None = None
        self.selectionStart: int | None = None
        self.size: int = 0
        self.src: str = ""
        self.step: str = ""
        self.type: str = ""
        self.useMap: str = ""
        self.validationMessage: str = ""
        self.validity: ValidityState = None
        self.value: str = ""
        self.valueAsDate: object | None = None
        self.valueAsNumber: float = 0.0
        self.webkitdirectory: bool = False
        self.webkitEntries: list[FileSystemEntry] = []
        self.width: int = 0
        self.willValidate: bool = False

    def checkValidity(self) -> bool: ...

    def reportValidity(self) -> bool: ...

    def select(self) -> None: ...

    def setCustomValidity(self, error: str) -> None: ...

    def setRangeText(self, replacement: str) -> None: ...

    def setSelectionRange(
        self, start: int, end: int, direction: str | None = None
    ) -> None: ...

    def showPicker(self) -> None: ...

    def stepDown(self, n: int = 1) -> None: ...

    def stepUp(self, n: int = 1) -> None: ...


@js.native
class HTMLLabelElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLLabelElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.control: HTMLElement | None = None
        self.form: HTMLFormElement | None = None
        self.htmlFor: str = ""


@js.native
class HTMLLegendElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLLegendElement

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.align: str = ""
        self.form: HTMLFormElement | None = None


@js.native
class HTMLLIElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLLIElement

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.type: str = ""
        self.value: int = 0


@js.native
class HTMLLinkElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLLinkElement

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.blocking: DOMTokenList = None
        self.charset: str = ""
        self.crossOrigin: str | None = None
        self.disabled: bool = False
        self.fetchPriority: str = ""
        self.href: str = ""
        self.hreflang: str = ""
        self.imageSizes: str = ""
        self.imageSrcset: str = ""
        self.integrity: str = ""
        self.media: str = ""
        self.referrerPolicy: str = ""
        self.rel: str = ""
        self.relList: DOMTokenList = None
        self.rev: str = ""
        self.sizes: DOMTokenList = None
        self.target: str = ""
        self.type: str = ""


@js.native
class HTMLMapElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLMapElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.areas: HTMLCollection[Element] = None
        self.name: str = ""


@js.native
class HTMLMarqueeElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLMarqueeElement

    Browser support: Chrome 1, Safari 1.2"""

    def __init__(self):
        super().__init__()
        self.behavior: str = ""
        self.bgColor: str = ""
        self.direction: str = ""
        self.height: str = ""
        self.hspace: int = 0
        self.loop: int = 0
        self.scrollAmount: int = 0
        self.scrollDelay: int = 0
        self.trueSpeed: bool = False
        self.vspace: int = 0
        self.width: str = ""

    def start(self) -> None: ...

    def stop(self) -> None: ...


@js.native
class HTMLMediaElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLMediaElement

    Browser support: Chrome 3, Safari 3.1"""

    HAVE_CURRENT_DATA = 2
    HAVE_ENOUGH_DATA = 4
    HAVE_FUTURE_DATA = 3
    HAVE_METADATA = 1
    HAVE_NOTHING = 0
    NETWORK_EMPTY = 0
    NETWORK_IDLE = 1
    NETWORK_LOADING = 2
    NETWORK_NO_SOURCE = 3

    def __init__(self):
        super().__init__()
        self.audioTracks: AudioTrackList = None
        self.autoplay: bool = False
        self.buffered: TimeRanges = None
        self.controls: bool = False
        self.crossOrigin: str | None = None
        self.currentSrc: str = ""
        self.currentTime: float = 0.0
        self.defaultMuted: bool = False
        self.defaultPlaybackRate: float = 0.0
        self.duration: float = 0.0
        self.ended: bool = False
        self.error: MediaError | None = None
        self.loading: str = ""
        self.loop: bool = False
        self.muted: bool = False
        self.networkState: int = 0
        self.paused: bool = False
        self.playbackRate: float = 0.0
        self.played: TimeRanges = None
        self.preload: str = ""
        self.preservesPitch: bool = False
        self.readyState: int = 0
        self.seekable: TimeRanges = None
        self.seeking: bool = False
        self.src: str = ""
        self.srcObject: MediaStream | MediaSource | Blob | None = None
        self.textTracks: TextTrackList = None
        self.videoTracks: VideoTrackList = None
        self.volume: float = 0.0

    def addTextTrack(
        self, kind: str, label: str = "", language: str = ""
    ) -> TextTrack: ...

    def canPlayType(self, type: str) -> str: ...

    def fastSeek(self, time: float) -> None: ...

    def getStartDate(self) -> object: ...

    def load(self) -> None: ...

    def pause(self) -> None: ...

    async def play(self) -> None: ...


@js.native
class HTMLMenuElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLMenuElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.compact: bool = False


@js.native
class HTMLMetaElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLMetaElement

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.content: str = ""
        self.httpEquiv: str = ""
        self.media: str = ""
        self.name: str = ""
        self.scheme: str = ""


@js.native
class HTMLMeterElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLMeterElement

    Browser support: Chrome 6, Safari 6"""

    def __init__(self):
        super().__init__()
        self.high: float = 0.0
        self.labels: NodeList[Node] = None
        self.low: float = 0.0
        self.max: float = 0.0
        self.min: float = 0.0
        self.optimum: float = 0.0
        self.value: float = 0.0


@js.native
class HTMLModElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLModElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.cite: str = ""
        self.dateTime: str = ""


@js.native
class HTMLObjectElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLObjectElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.align: str = ""
        self.archive: str = ""
        self.border: str = ""
        self.code: str = ""
        self.codeBase: str = ""
        self.codeType: str = ""
        self.contentDocument: Document | None = None
        self.contentWindow: Window | None = None
        self.data: str = ""
        self.declare: bool = False
        self.form: HTMLFormElement | None = None
        self.height: str = ""
        self.hspace: int = 0
        self.name: str = ""
        self.standby: str = ""
        self.type: str = ""
        self.useMap: str = ""
        self.validationMessage: str = ""
        self.validity: ValidityState = None
        self.vspace: int = 0
        self.width: str = ""
        self.willValidate: bool = False

    def checkValidity(self) -> bool: ...

    def getSVGDocument(self) -> Document | None: ...

    def reportValidity(self) -> bool: ...

    def setCustomValidity(self, error: str) -> None: ...


@js.native
class HTMLOListElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLOListElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.compact: bool = False
        self.reversed: bool = False
        self.start: int = 0
        self.type: str = ""


@js.native
class HTMLOptGroupElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLOptGroupElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.disabled: bool = False
        self.label: str = ""


@js.native
class HTMLOptionElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLOptionElement

    Browser support: Chrome 1, Safari 1.2"""

    def __init__(self):
        super().__init__()
        self.defaultSelected: bool = False
        self.disabled: bool = False
        self.form: HTMLFormElement | None = None
        self.index: int = 0
        self.label: str = ""
        self.selected: bool = False
        self.text: str = ""
        self.value: str = ""


@js.native
class HTMLOutputElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLOutputElement

    Browser support: Chrome 9, Safari 5.1"""

    def __init__(self):
        super().__init__()
        self.defaultValue: str = ""
        self.form: HTMLFormElement | None = None
        self.htmlFor: DOMTokenList = None
        self.labels: NodeList[Node] = None
        self.name: str = ""
        self.type: str = ""
        self.validationMessage: str = ""
        self.validity: ValidityState = None
        self.value: str = ""
        self.willValidate: bool = False

    def checkValidity(self) -> bool: ...

    def reportValidity(self) -> bool: ...

    def setCustomValidity(self, error: str) -> None: ...


@js.native
class HTMLParagraphElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLParagraphElement

    Browser support: Chrome 1, Safari 3"""

    tagName = nodeName = "P"

    def __init__(self):
        super().__init__()
        self.align: str = ""


@js.native
class HTMLParamElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLParamElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.name: str = ""
        self.type: str = ""
        self.value: str = ""
        self.valueType: str = ""


@js.native
class HTMLPictureElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLPictureElement

    Browser support: Chrome 38, Safari 9.1"""

    def __init__(self):
        super().__init__()


@js.native
class HTMLPreElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLPreElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.width: int = 0


@js.native
class HTMLProgressElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLProgressElement

    Browser support: Chrome 6, Safari 6"""

    def __init__(self):
        super().__init__()
        self.labels: NodeList[Node] = None
        self.max: float = 0.0
        self.position: float = 0.0
        self.value: float = 0.0


@js.native
class HTMLQuoteElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLQuoteElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.cite: str = ""


@js.native
class HTMLScriptElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLScriptElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.blocking: DOMTokenList = None
        self.charset: str = ""
        self.crossOrigin: str | None = None
        self.defer: bool = False
        self.event: str = ""
        self.fetchPriority: str = ""
        self.htmlFor: str = ""
        self.integrity: str = ""
        self.noModule: bool = False
        self.referrerPolicy: str = ""
        self.src: str = ""
        self.text: str = ""
        self.type: str = ""

    @staticmethod
    def supports(type: str) -> bool: ...


@js.native
class HTMLSelectedContentElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLSelectedContentElement

    Browser support: Chrome 135, Safari 27"""

    def __init__(self):
        super().__init__()


@js.native
class HTMLSelectElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLSelectElement

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.autocomplete: str = ""
        self.disabled: bool = False
        self.form: HTMLFormElement | None = None
        self.labels: NodeList[Node] = None
        self.length: int = 0
        self.multiple: bool = False
        self.name: str = ""
        self.options: HTMLOptionsCollection = None
        self.required: bool = False
        self.selectedIndex: int = 0
        self.selectedOptions: HTMLCollection[Element] = None
        self.size: int = 0
        self.type: str = ""
        self.validationMessage: str = ""
        self.validity: ValidityState = None
        self.value: str = ""
        self.willValidate: bool = False

    @js.inline("{self}[{index}] = {option}")
    def __setitem__(self, index: int, option: HTMLOptionElement | None) -> None: ...

    def add(
        self,
        element: HTMLOptionElement | HTMLOptGroupElement,
        before: HTMLElement | int | None = None,
    ) -> None: ...

    def checkValidity(self) -> bool: ...

    def item(self, index: int) -> HTMLOptionElement | None: ...

    def namedItem(self, name: str) -> HTMLOptionElement | None: ...

    def remove(self) -> None: ...

    def reportValidity(self) -> bool: ...

    def setCustomValidity(self, error: str) -> None: ...

    def showPicker(self) -> None: ...


@js.native
class HTMLSlotElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLSlotElement

    Browser support: Chrome 53, Safari 10"""

    def __init__(self):
        super().__init__()
        self.name: str = ""

    def assign(self, *nodes: Element | Text) -> None: ...

    def assignedElements(self, *, flatten: bool = False) -> list[Element]: ...

    def assignedNodes(self, *, flatten: bool = False) -> list[Node]: ...


@js.native
class HTMLSourceElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLSourceElement

    Browser support: Chrome 3, Safari 3.1"""

    def __init__(self):
        super().__init__()
        self.height: int = 0
        self.media: str = ""
        self.sizes: str = ""
        self.src: str = ""
        self.srcset: str = ""
        self.type: str = ""
        self.width: int = 0


@js.native
class HTMLSpanElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLSpanElement

    Browser support: Chrome 15, Safari 6"""

    tagName = nodeName = "SPAN"

    def __init__(self):
        super().__init__()


@js.native
class HTMLStyleElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLStyleElement

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.blocking: DOMTokenList = None
        self.disabled: bool = False
        self.media: str = ""
        self.type: str = ""


@js.native
class HTMLTableCaptionElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLTableCaptionElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.align: str = ""


@js.native
class HTMLTableCellElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLTableCellElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.abbr: str = ""
        self.align: str = ""
        self.axis: str = ""
        self.bgColor: str = ""
        self.cellIndex: int = 0
        self.ch: str = ""
        self.chOff: str = ""
        self.colSpan: int = 0
        self.headers: str = ""
        self.height: str = ""
        self.noWrap: bool = False
        self.rowSpan: int = 0
        self.scope: str = ""
        self.vAlign: str = ""
        self.width: str = ""


@js.native
class HTMLTableColElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLTableColElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.align: str = ""
        self.ch: str = ""
        self.chOff: str = ""
        self.span: int = 0
        self.vAlign: str = ""
        self.width: str = ""


@js.native
class HTMLTableElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLTableElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.align: str = ""
        self.bgColor: str = ""
        self.border: str = ""
        self.caption: HTMLTableCaptionElement | None = None
        self.cellPadding: str = ""
        self.cellSpacing: str = ""
        self.frame: str = ""
        self.rows: HTMLCollection[Element] = None
        self.rules: str = ""
        self.summary: str = ""
        self.tBodies: HTMLCollection[Element] = None
        self.tFoot: HTMLTableSectionElement | None = None
        self.tHead: HTMLTableSectionElement | None = None
        self.width: str = ""

    def createCaption(self) -> HTMLTableCaptionElement: ...

    def createTBody(self) -> HTMLTableSectionElement: ...

    def createTFoot(self) -> HTMLTableSectionElement: ...

    def createTHead(self) -> HTMLTableSectionElement: ...

    def deleteCaption(self) -> None: ...

    def deleteRow(self, index: int) -> None: ...

    def deleteTFoot(self) -> None: ...

    def deleteTHead(self) -> None: ...

    def insertRow(self, index: int = -1) -> HTMLTableRowElement: ...


@js.native
class HTMLTableRowElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLTableRowElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.align: str = ""
        self.bgColor: str = ""
        self.cells: HTMLCollection[Element] = None
        self.ch: str = ""
        self.chOff: str = ""
        self.rowIndex: int = 0
        self.sectionRowIndex: int = 0
        self.vAlign: str = ""

    def deleteCell(self, index: int) -> None: ...

    def insertCell(self, index: int = -1) -> HTMLTableCellElement: ...


@js.native
class HTMLTableSectionElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLTableSectionElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.align: str = ""
        self.ch: str = ""
        self.chOff: str = ""
        self.rows: HTMLCollection[Element] = None
        self.vAlign: str = ""

    def deleteRow(self, index: int) -> None: ...

    def insertRow(self, index: int = -1) -> HTMLTableRowElement: ...


@js.native
class HTMLTemplateElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLTemplateElement

    Browser support: Chrome 26, Safari 8"""

    def __init__(self):
        super().__init__()
        self.content: DocumentFragment = None
        self.shadowRootClonable: bool = False
        self.shadowRootCustomElementRegistry: str = ""
        self.shadowRootDelegatesFocus: bool = False
        self.shadowRootMode: str = ""
        self.shadowRootSerializable: bool = False
        self.shadowRootSlotAssignment: str = ""


@js.native
class HTMLTextAreaElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLTextAreaElement

    Browser support: Chrome 1, Safari 1"""

    tagName = nodeName = "TEXTAREA"

    def __init__(self):
        super().__init__()
        self.autocomplete: str = ""
        self.cols: int = 0
        self.defaultValue: str = ""
        self.dirName: str = ""
        self.disabled: bool = False
        self.form: HTMLFormElement | None = None
        self.labels: NodeList[Node] = None
        self.maxLength: int = 0
        self.minLength: int = 0
        self.name: str = ""
        self.placeholder: str = ""
        self.readOnly: bool = False
        self.required: bool = False
        self.rows: int = 0
        self.selectionDirection: str = ""
        self.selectionEnd: int = 0
        self.selectionStart: int = 0
        self.textLength: int = 0
        self.type: str = ""
        self.validationMessage: str = ""
        self.validity: ValidityState = None
        self.value: str = ""
        self.willValidate: bool = False
        self.wrap: str = ""

    def checkValidity(self) -> bool: ...

    def reportValidity(self) -> bool: ...

    def select(self) -> None: ...

    def setCustomValidity(self, error: str) -> None: ...

    def setRangeText(self, replacement: str) -> None: ...

    def setSelectionRange(
        self, start: int, end: int, direction: str | None = None
    ) -> None: ...


@js.native
class VisibilityStateEntry(PerformanceEntry):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/VisibilityStateEntry

    Browser support: Chrome 115"""

    def __init__(self):
        super().__init__()
        self.duration: int = 0
        self.entryType: str = ""
        self.name: str = ""
        self.startTime: float = 0.0


@js.native
class HTMLAudioElement(HTMLMediaElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLAudioElement

    Browser support: Chrome 3, Safari 3.1"""

    def __init__(self):
        super().__init__()


@js.native
class HTMLVideoElement(HTMLMediaElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLVideoElement

    Browser support: Chrome 3, Safari 3.1"""

    def __init__(self):
        super().__init__()
        self.height: int = 0
        self.playsInline: bool = False
        self.poster: str = ""
        self.videoHeight: int = 0
        self.videoWidth: int = 0
        self.width: int = 0
