from pyjs import js, js_object
from pyjs.web.dom import (
    CSSStyleProperties,
    Document,
    DOMRect,
    DOMTokenList,
    Element,
    Node,
    NodeList,
    Window,
)
from pyjs.web.files import FileList


@js(builtin=True)
class CanvasRenderingContext2D:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CanvasRenderingContext2D

    Browser support: Chrome 1, Safari 2"""

    pass


@js(builtin=True)
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
js_object(customElements, builtin=True)


@js(builtin=True)
class DOMStringList:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMStringList

    Browser support: Chrome 1, Safari 5.1"""

    def __init__(self):
        self.length: int = 0

    def contains(self, string: str) -> bool: ...

    @js(inline="{self}[{index}]")
    def item(self, index: int) -> str | None: ...


@js(builtin=True)
class DOMStringMap:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMStringMap

    Browser support: Chrome 7, Safari 5.1"""

    def __init__(self):
        self.map: dict[str, str] = {}

    @js(inline="delete {self}[{name}]")
    def __delitem__(self, name: str) -> None: ...

    @js(inline="{self}[{name}]")
    def __getitem__(self, name: str) -> str:
        return self.map[name]

    @js(inline="{self}[{name}] = {value}")
    def __setitem__(self, name: str, value: str) -> None:
        self.map[name] = value


@js(builtin=True)
class EditContext:
    """WebIDL source: @webref/idl/edit-context.idl

    MDN: https://developer.mozilla.org/docs/Web/API/EditContext

    Browser support: Chrome 121"""

    pass


@js
class ElementDefinitionOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, extends: str | None = None):
        self.extends = extends


@js(builtin=True)
class ElementInternals:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ElementInternals

    Browser support: Chrome 77, Safari 16.4"""

    pass


@js(builtin=True)
class FileSystemEntry:
    """WebIDL source: @webref/idl/entries-api.idl

    MDN: https://developer.mozilla.org/docs/Web/API/FileSystemEntry

    Browser support: Chrome 8, Safari 11.1"""

    pass


@js
class FocusOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, focusVisible: bool | None = None, preventScroll: bool = False):
        self.focusVisible = focusVisible
        self.preventScroll = preventScroll


@js(builtin=True)
class GPUCanvasContext:
    """WebIDL source: @webref/idl/webgpu.idl

    MDN: https://developer.mozilla.org/docs/Web/API/GPUCanvasContext

    Browser support: Chrome 144, Safari 26"""

    pass


@js(builtin=True)
class HTMLDataListElement:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLDataListElement

    Browser support: Chrome 20, Safari 12.1"""

    pass


@js(builtin=True)
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


@js(builtin=True)
class HTMLFormControlsCollection:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLFormControlsCollection

    Browser support: Chrome 1, Safari 3"""

    pass


@js(builtin=True)
class ImageBitmapRenderingContext:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ImageBitmapRenderingContext

    Browser support: Chrome 66, Safari 11.1"""

    pass


@js(builtin=True)
class MediaStream:
    """WebIDL source: @webref/idl/mediacapture-streams.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MediaStream

    Browser support: Chrome 55, Safari 11"""

    pass


@js(builtin=True)
class OffscreenCanvas:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/OffscreenCanvas

    Browser support: Chrome 69, Safari 16.4"""

    pass


@js(builtin=True)
class PermissionsPolicy:
    """WebIDL source: @webref/idl/permissions-policy.idl

    Browser support: Chrome preview"""

    pass


@js
class ShowPopoverOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, source: HTMLElement | None = None):
        self.source = source


@js(builtin=True)
class StylePropertyMap:
    """WebIDL source: @webref/idl/css-typed-om.idl

    MDN: https://developer.mozilla.org/docs/Web/API/StylePropertyMap

    Browser support: Chrome 66, Safari 16.4"""

    pass


@js(builtin=True)
class TrustedHTML:
    """WebIDL source: @webref/idl/trusted-types.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TrustedHTML

    Browser support: Chrome 83, Safari 26"""

    pass


@js(builtin=True)
class ValidityState:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ValidityState

    Browser support: Chrome 4, Safari 5"""

    pass


@js(builtin=True)
class WebGL2RenderingContext:
    """WebIDL source: @webref/idl/webgl2.idl

    MDN: https://developer.mozilla.org/docs/Web/API/WebGL2RenderingContext

    Browser support: Chrome 56, Safari 15"""

    pass


@js(builtin=True)
class WebGLRenderingContext:
    """WebIDL source: @webref/idl/webgl1.idl

    MDN: https://developer.mozilla.org/docs/Web/API/WebGLRenderingContext

    Browser support: Chrome 9, Safari 5.1"""

    pass


@js(builtin=True)
class WindowProxy:
    """WebIDL source: @webref/idl/unknown"""

    pass


@js(builtin=True)
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


@js(builtin=True)
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


@js(builtin=True)
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


@js(builtin=True)
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


@js(builtin=True)
class HTMLDivElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLDivElement

    Browser support: Chrome 1, Safari 3"""

    tagName = nodeName = "DIV"

    def __init__(self):
        super().__init__()
        self.align: str = "left"


@js(builtin=True)
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

    @js(inline="{self}[{index}]")
    def __getitem__(self, index: int) -> Element: ...

    def checkValidity(self) -> bool: ...

    def reportValidity(self) -> bool: ...

    def requestSubmit(self, submitter: HTMLElement | None = None) -> None: ...

    def reset(self) -> None: ...

    def submit(self) -> None: ...


@js(builtin=True)
class HTMLHeadingElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLHeadingElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.align: str = ""


@js(builtin=True)
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


@js(builtin=True)
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


@js(builtin=True)
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


@js(builtin=True)
class HTMLParagraphElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLParagraphElement

    Browser support: Chrome 1, Safari 3"""

    tagName = nodeName = "P"

    def __init__(self):
        super().__init__()
        self.align: str = ""


@js(builtin=True)
class HTMLSpanElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLSpanElement

    Browser support: Chrome 15, Safari 6"""

    tagName = nodeName = "SPAN"

    def __init__(self):
        super().__init__()


@js(builtin=True)
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


@js
class TogglePopoverOptions(ShowPopoverOptions):
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, force: bool | None = None, source: HTMLElement | None = None):
        self.force = force
        self.source = source
