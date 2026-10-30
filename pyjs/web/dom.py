import weakref
from collections.abc import Iterator

from pyjs import js, nojs
from pyjs.web._dom_storage import (
    _AttributeItems,
    _child_offset,
    _ChildNodeItems,
    _DefaultCollector,
    _element_text_content,
    _ElementItems,
    _get_parts,
    _parts,
    _set_element_text_content,
)
from pyjs.web.console import Console
from pyjs.web.events import AbortSignal, Event, EventListener, EventTarget

_html_element_factory = None


@js.dictionary
class CSSStyleSheetInit:
    """WebIDL source: @webref/idl/cssom.idl"""

    def __init__(
        self,
        baseURL: str | None = None,
        disabled: bool = False,
        media: MediaList | str = "",
    ):
        self.baseURL = baseURL
        self.disabled = disabled
        self.media = media


@js.native
class CustomElementRegistry:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CustomElementRegistry

    Browser support: Chrome 54, Safari 10.1"""

    pass


@js.native
class DOMException(Exception):
    """WebIDL source: @webref/idl/webidl.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMException

    Browser support: Chrome 1, Safari 1"""

    pass
    ABORT_ERR = 20
    DATA_CLONE_ERR = 25
    DOMSTRING_SIZE_ERR = 2
    HIERARCHY_REQUEST_ERR = 3
    INDEX_SIZE_ERR = 1
    INUSE_ATTRIBUTE_ERR = 10
    INVALID_ACCESS_ERR = 15
    INVALID_CHARACTER_ERR = 5
    INVALID_MODIFICATION_ERR = 13
    INVALID_NODE_TYPE_ERR = 24
    INVALID_STATE_ERR = 11
    NAMESPACE_ERR = 14
    NETWORK_ERR = 19
    NO_DATA_ALLOWED_ERR = 6
    NO_MODIFICATION_ALLOWED_ERR = 7
    NOT_FOUND_ERR = 8
    NOT_SUPPORTED_ERR = 9
    QUOTA_EXCEEDED_ERR = 22
    SECURITY_ERR = 18
    SYNTAX_ERR = 12
    TIMEOUT_ERR = 23
    TYPE_MISMATCH_ERR = 17
    URL_MISMATCH_ERR = 21
    VALIDATION_ERR = 16
    WRONG_DOCUMENT_ERR = 4

    def __init__(self, message: str = "", name: str = "Error"):
        self.code: int = 0
        self.message: str = message
        self.name: str = name


@js.native
class DOMImplementation:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMImplementation

    Browser support: Chrome 1, Safari 1"""

    def createDocument(
        self,
        namespace: str | None,
        qualifiedName: str,
        doctype: DocumentType | None = None,
    ) -> XMLDocument: ...

    def createDocumentType(
        self, name: str, publicId: str, systemId: str
    ) -> DocumentType: ...

    def createHTMLDocument(self, title: str | None = None) -> Document: ...

    def hasFeature(self) -> bool: ...


@js.dictionary
class DOMPointInit:
    """WebIDL source: @webref/idl/geometry.idl"""

    def __init__(self, w: float = 1, x: float = 0, y: float = 0, z: float = 0):
        self.w = w
        self.x = x
        self.y = y
        self.z = z


@js.native
class DOMPointReadOnly:
    """WebIDL source: @webref/idl/geometry.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMPointReadOnly

    Browser support: Chrome 61, Safari 10.1"""

    pass


@js.native
class DOMQuad:
    """WebIDL source: @webref/idl/geometry.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMQuad

    Browser support: Chrome 61, Safari 11"""

    pass


@js.dictionary
class DOMQuadInit:
    """WebIDL source: @webref/idl/geometry.idl"""

    def __init__(
        self,
        p1: DOMPointInit | None = None,
        p2: DOMPointInit | None = None,
        p3: DOMPointInit | None = None,
        p4: DOMPointInit | None = None,
    ):
        if p1 is not None:
            self.p1 = p1
        if p2 is not None:
            self.p2 = p2
        if p3 is not None:
            self.p3 = p3
        if p4 is not None:
            self.p4 = p4


@js.dictionary
class DOMRectInit:
    """WebIDL source: @webref/idl/geometry.idl"""

    def __init__(self, height: float = 0, width: float = 0, x: float = 0, y: float = 0):
        self.height = height
        self.width = width
        self.x = x
        self.y = y


@js.native
class DOMRectList:
    """WebIDL source: @webref/idl/geometry.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMRectList

    Browser support: Chrome 61, Safari 10.1"""

    pass


@js.native
class DOMRectReadOnly:
    """WebIDL source: @webref/idl/geometry.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMRectReadOnly

    Browser support: Chrome 61, Safari 10.1"""

    def __init__(self, x: float = 0, y: float = 0, width: float = 0, height: float = 0):
        self.bottom: float = y + height
        self.height: float = height
        self.left: float = x
        self.right: float = x + width
        self.top: float = y
        self.width: float = width
        self.x: float = x
        self.y: float = y

    @staticmethod
    def fromRect(
        *, x: float = 0, y: float = 0, width: float = 0, height: float = 0
    ) -> DOMRectReadOnly: ...

    def toJSON(self) -> object: ...


@js.native
class DOMStringList:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMStringList

    Browser support: Chrome 1, Safari 5.1"""

    pass


@js.native
class DOMTokenList:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMTokenList

    Browser support: Chrome 8, Safari 5.1"""

    __slots__ = ("_tokens", "_element", "_attribute")

    def __init__(
        self,
        tokens: list[str] | None = None,
        *,
        element: object | None = None,
        attribute: str | None = None,
    ):
        if (element is None) != (attribute is None):
            raise ValueError("element and attribute must be provided together")
        if element is not None and tokens is not None:
            raise ValueError("tokens and element are mutually exclusive")
        self._tokens = [] if tokens is None else tokens
        self._element = element
        self._attribute = attribute

    def _read(self) -> list[str]:
        if self._element is None:
            return self._tokens
        return (self._element.getAttribute(self._attribute) or "").split()

    def _write(self, tokens: list[str]) -> None:
        if self._element is None:
            self._tokens[:] = tokens
        else:
            self._element.setAttribute(self._attribute, " ".join(tokens))

    @property
    def tokens(self) -> list[str]:
        return self._read()

    @tokens.setter
    def tokens(self, tokens: list[str]):
        self._write(tokens)

    @property
    def length(self) -> int:
        return len(self._read())

    @property
    def value(self) -> str:
        return " ".join(self._read())

    @value.setter
    def value(self, value: str):
        self._write(value.split())

    def add(self, *tokens: str) -> None:
        current = list(self._read())
        changed = False
        for token in tokens:
            if token not in current:
                current.append(token)
                changed = True
        if changed:
            self._write(current)

    def item(self, index: int) -> str | None:
        tokens = self._read()
        if index < 0 or index >= len(tokens):
            return None
        return tokens[index]

    def remove(self, *tokens: str) -> None:
        current = list(self._read())
        changed = False
        for token in tokens:
            if token in current:
                current.remove(token)
                changed = True
        if changed:
            self._write(current)

    def replace(self, token: str, newToken: str) -> bool:
        tokens = list(self._read())
        if token not in tokens:
            return False
        if token == newToken:
            return True
        index = tokens.index(token)
        if newToken in tokens:
            tokens.remove(token)
        else:
            tokens[index] = newToken
        self._write(tokens)
        return True

    def supports(self, token: str) -> bool: ...

    def toggle(self, token: str, force: bool | None = None) -> bool:
        tokens = list(self._read())
        present = token in tokens
        enabled = not present if force is None else force
        if enabled and (not present):
            tokens.append(token)
            self._write(tokens)
        elif not enabled and present:
            tokens.remove(token)
            self._write(tokens)
        return enabled

    def contains(self, token: str) -> bool:
        return token in self._read()


@js.native
class AbortController:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/AbortController

    Browser support: Chrome 66, Safari 12.1"""

    def __init__(self):
        self.signal: AbortSignal = None

    def abort(self, reason: object | None = None) -> None: ...


@js.native
class AbstractRange:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/AbstractRange

    Browser support: Chrome 90, Safari 14.1"""

    def __init__(self):
        self.collapsed: bool = False
        self.endContainer: Node = None
        self.endOffset: int = 0
        self.startContainer: Node = None
        self.startOffset: int = 0


@js.native
class BarProp:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/BarProp

    Browser support: Chrome 1, Safari 3"""

    pass


@js.native
class Blob:
    """WebIDL source: @webref/idl/FileAPI.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Blob

    Browser support: Chrome 5, Safari 6"""

    pass


@js.dictionary
class BoxQuadOptions:
    """WebIDL source: @webref/idl/cssom-view.idl"""

    def __init__(
        self,
        box: str = "border",
        relativeTo: Text | Element | CSSPseudoElement | Document | None = None,
    ):
        self.box = box
        if relativeTo is not None:
            self.relativeTo = relativeTo


@js.native
class CaretPosition:
    """WebIDL source: @webref/idl/cssom-view.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CaretPosition

    Browser support: Chrome 128, Safari 26.2"""

    def __init__(self):
        self.offset: int = 0
        self.offsetNode: Node = None

    def getClientRect(self) -> DOMRect | None: ...


@js.dictionary
class CaretPositionFromPointOptions:
    """WebIDL source: @webref/idl/cssom-view.idl"""

    def __init__(self, shadowRoots: list[ShadowRoot] | None = None):
        if shadowRoots is None:
            shadowRoots = []
        self.shadowRoots = shadowRoots


@js.dictionary
class CheckVisibilityOptions:
    """WebIDL source: @webref/idl/cssom-view.idl"""

    def __init__(
        self,
        checkOpacity: bool = False,
        checkVisibilityCSS: bool = False,
        contentVisibilityAuto: bool = False,
        opacityProperty: bool = False,
        visibilityProperty: bool = False,
    ):
        self.checkOpacity = checkOpacity
        self.checkVisibilityCSS = checkVisibilityCSS
        self.contentVisibilityAuto = contentVisibilityAuto
        self.opacityProperty = opacityProperty
        self.visibilityProperty = visibilityProperty


@js.dictionary
class ConvertCoordinateOptions:
    """WebIDL source: @webref/idl/cssom-view.idl"""

    def __init__(self, fromBox: str = "border", toBox: str = "border"):
        self.fromBox = fromBox
        self.toBox = toBox


@js.native
class CSSPseudoElement:
    """WebIDL source: @webref/idl/css-pseudo.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CSSPseudoElement

    Browser support: Chrome 149"""

    pass


@js.native
class CSSRule:
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CSSRule

    Browser support: Chrome 1, Safari 1"""

    CHARSET_RULE = 2
    FONT_FACE_RULE = 5
    IMPORT_RULE = 3
    MARGIN_RULE = 9
    MEDIA_RULE = 4
    NAMESPACE_RULE = 10
    PAGE_RULE = 6
    STYLE_RULE = 1

    def __init__(self):
        self.cssText: str = ""
        self.parentRule: CSSRule | None = None
        self.parentStyleSheet: CSSStyleSheet | None = None
        self.type: int = 0


@js.native
class CSSRuleList:
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CSSRuleList

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.length: int = 0

    def item(self, index: int) -> CSSRule | None: ...


@js.native
class CSSStyleDeclaration:
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CSSStyleDeclaration

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.display = "block"
        self.position = "static"
        self.visibility = "visible"
        self.overflow = "visible"
        self.left = "auto"
        self.top = "auto"
        self.width = "auto"
        self.height = "auto"
        self.zIndex = "auto"
        self.margin = ""
        self.padding = ""
        self.border = ""
        self.boxSizing = "content-box"
        self.cssText: str = ""
        self.length: int = 0
        self.parentRule: CSSRule | None = None

    def getPropertyPriority(self, property: str) -> str: ...

    def getPropertyValue(self, property: str) -> str: ...

    def item(self, index: int) -> str: ...

    def removeProperty(self, property: str) -> str: ...

    def setProperty(self, property: str, value: str, priority: str = "") -> None: ...


@js.dictionary
class ElementCreationOptions:
    """WebIDL source: @webref/idl/dom.idl"""

    def __init__(
        self,
        customElementRegistry: CustomElementRegistry | None = None,
        is_: str | None = None,
    ):
        self.customElementRegistry = customElementRegistry
        self.is_ = is_


@js.native
class External:
    """WebIDL source: @webref/idl/html.idl

    Browser support: Chrome 1"""

    pass


@js.dictionary
class GetRootNodeOptions:
    """WebIDL source: @webref/idl/dom.idl"""

    def __init__(self, composed: bool = False):
        self.composed = composed


@js.native
class History:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/History

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.length: int = 0
        self.scrollRestoration: str = ""
        self.state: object = None

    def back(self) -> None: ...

    def forward(self) -> None: ...

    def go(self, delta: int = 0) -> None: ...

    def pushState(self, data: object, unused: str, url: str | None = None) -> None: ...

    def replaceState(self, data: object, unused: str, url: str | None = None) -> None: ...


@js.native
class HTMLCollection[T]:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLCollection

    Browser support: Chrome 1, Safari 1"""

    __slots__ = ("_items",)

    def __init__(self, items=None):
        self._items = [] if items is None else items

    @property
    def length(self) -> int:
        return len(self._items)

    @js.inline("{self}[{index}]")
    def __getitem__(self, index: int) -> T:
        return self._items[index]

    @js.inline("{self}[Symbol.iterator]()")
    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

    @js.inline("{self}.length")
    def __len__(self) -> int:
        return len(self._items)

    @js.inline("{self}[{index}]")
    def item(self, index: int) -> Element | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    @js.inline("{self}[{name}]")
    def namedItem(self, name: str) -> Element | None:
        for item in self._items:
            if item.id == name or item.getAttribute("name") == name:
                return item
        return None

    def _append(self, item: T) -> None:
        self._items.append(item)

    def _clear(self) -> None:
        self._items.clear()

    def _remove(self, item: T) -> None:
        self._items.remove(item)


@js.native
class ImageBitmap:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ImageBitmap

    Browser support: Chrome 50, Safari 15"""

    pass


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
class ImageData:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ImageData

    Browser support: Chrome 1, Safari 3.1"""

    pass


@js.dictionary
class ImportNodeOptions:
    """WebIDL source: @webref/idl/dom.idl"""

    def __init__(
        self,
        customElementRegistry: CustomElementRegistry | None = None,
        selfOnly: bool = False,
    ):
        self.customElementRegistry = customElementRegistry
        self.selfOnly = selfOnly


@js.native
class MediaList:
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MediaList

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.length: int = 0
        self.mediaText: str = ""

    def appendMedium(self, medium: str) -> None: ...

    def deleteMedium(self, medium: str) -> None: ...

    def item(self, index: int) -> str | None: ...


@js.native
class MediaQueryListEvent(Event):
    """WebIDL source: @webref/idl/cssom-view.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MediaQueryListEvent

    Browser support: Chrome 39, Safari 14"""

    def __init__(self, type: str, *, media: str = "", matches: bool = False):
        super().__init__()
        self.matches: bool = matches
        self.media: str = media


@js.dictionary
class MediaQueryListEventInit:
    """WebIDL source: @webref/idl/cssom-view.idl"""

    def __init__(self, matches: bool = False, media: str = ""):
        self.matches = matches
        self.media = media


@js.native
class MimeTypeArray:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MimeTypeArray

    Browser support: Chrome 1, Safari 1"""

    pass


@js.native
class MutationObserver:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MutationObserver

    Browser support: Chrome 26, Safari 7"""

    def __init__(self, callback: callable): ...

    def disconnect(self) -> None: ...

    def observe(
        self,
        target: Node,
        *,
        childList: bool = False,
        attributes: bool | None = None,
        characterData: bool | None = None,
        subtree: bool = False,
        attributeOldValue: bool | None = None,
        characterDataOldValue: bool | None = None,
        attributeFilter: list[str] | None = None,
    ) -> None: ...

    def takeRecords(self) -> list[MutationRecord]: ...


@js.dictionary
class MutationObserverInit:
    """WebIDL source: @webref/idl/dom.idl"""

    def __init__(
        self,
        attributeFilter: list[str] | None = None,
        attributeOldValue: bool | None = None,
        attributes: bool | None = None,
        characterData: bool | None = None,
        characterDataOldValue: bool | None = None,
        childList: bool = False,
        subtree: bool = False,
    ):
        if attributeFilter is not None:
            self.attributeFilter = attributeFilter
        if attributeOldValue is not None:
            self.attributeOldValue = attributeOldValue
        if attributes is not None:
            self.attributes = attributes
        if characterData is not None:
            self.characterData = characterData
        if characterDataOldValue is not None:
            self.characterDataOldValue = characterDataOldValue
        self.childList = childList
        self.subtree = subtree


@js.native
class MutationRecord:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MutationRecord

    Browser support: Chrome 16, Safari 7"""

    def __init__(self):
        self.addedNodes: NodeList[Node] = None
        self.attributeName: str | None = None
        self.attributeNamespace: str | None = None
        self.nextSibling: Node | None = None
        self.oldValue: str | None = None
        self.previousSibling: Node | None = None
        self.removedNodes: NodeList[Node] = None
        self.target: Node = None
        self.type: str = ""


@js.native
class NamedNodeMap[T]:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NamedNodeMap

    Browser support: Chrome 1, Safari 1"""

    __slots__ = ("_attributes", "_owner")

    def __init__(self, attributes: dict[str, T] | None = None, owner=None):
        self._attributes = {} if attributes is None else attributes
        self._owner = owner

    def _materialize(self, name: str) -> Attr | None:
        value = self._attributes.get(name)
        if value is None:
            return None
        if isinstance(value, Attr):
            return value
        attribute = Attr()
        attribute.localName = name
        attribute.name = name
        attribute.ownerElement = self._owner
        attribute.value = value
        self._attributes[name] = attribute
        return attribute

    @property
    def length(self) -> int:
        return len(self._attributes)

    @js.inline("{self}[{key}]")
    def __getitem__(self, key: int | str) -> T:
        if isinstance(key, int):
            key = list(self._attributes)[key]
        attribute = self._materialize(key)
        if attribute is None:
            raise KeyError(key)
        return attribute

    @js.inline("{self}[Symbol.iterator]()")
    def __iter__(self) -> Iterator[T]:
        return (self._materialize(name) for name in self._attributes)

    @js.inline("{name} in {self}")
    def __contains__(self, name: str) -> bool:
        return name in self._attributes

    @js.inline("{self}.length")
    def __len__(self) -> int:
        return len(self._attributes)

    @js.inline("{self}[{qualifiedName}]")
    def getNamedItem(self, qualifiedName: str) -> Attr | None:
        return self._materialize(qualifiedName)

    def getNamedItemNS(self, namespace: str | None, localName: str) -> Attr | None:
        for attribute in self:
            if attribute.namespaceURI == namespace and attribute.localName == localName:
                return attribute
        return None

    @js.inline("{self}[{index}]")
    def item(self, index: int) -> Attr | None:
        if 0 <= index < len(self._attributes):
            return self._materialize(list(self._attributes)[index])
        return None

    def removeNamedItem(self, qualifiedName: str) -> Attr:
        attribute = self._materialize(qualifiedName)
        if attribute is None:
            raise KeyError(qualifiedName)
        del self._attributes[qualifiedName]
        attribute.ownerElement = None
        return attribute

    def removeNamedItemNS(self, namespace: str | None, localName: str) -> Attr:
        attribute = self.getNamedItemNS(namespace, localName)
        if attribute is None:
            raise ValueError(f"Attribute {localName!r} does not exist")
        return self.removeNamedItem(attribute.name)

    def setNamedItem(self, attr: Attr) -> Attr | None:
        previous = self._materialize(attr.name)
        attr.ownerElement = self._owner
        self._attributes[attr.name] = attr
        return previous

    def setNamedItemNS(self, attr: Attr) -> Attr | None:
        previous = self.getNamedItemNS(attr.namespaceURI, attr.localName)
        if previous is not None:
            if previous.name != attr.name:
                self.removeNamedItem(previous.name)
        self.setNamedItem(attr)
        return previous


_NODE_DEFAULTS = None


def _node_attribute(instance, name):
    global _NODE_DEFAULTS
    if _NODE_DEFAULTS is None:
        prototype = Node.__new__(Node)
        object.__setattr__(prototype, "__dict__", _DefaultCollector(Node))
        Node.__init__(prototype)
        _NODE_DEFAULTS = dict(vars(prototype))
    try:
        value = _NODE_DEFAULTS[name]
    except KeyError:
        raise AttributeError(name) from None
    if value is not None and (not isinstance(value, (bool, int, float, str, bytes))):
        value = type(value)()
        object.__setattr__(instance, name, value)
    return value


@js.native
class Node(EventTarget):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Node

    Browser support: Chrome 1, Safari 1"""

    nodeName = "undefined"
    __slots__ = ("_pyjs_parent",)

    def __init__(self):
        data = object.__getattribute__(self, "__dict__")
        if not isinstance(data, _DefaultCollector) or data.owner is not Node:
            return
        super().__init__()
        self.parentNode: Node | None = None
        self.previousSibling: Node | None = None
        self.baseURI: str = ""
        self.childNodes: NodeList[Node] = NodeList[Node]()
        self.firstChild: Node | None = None
        self.isConnected: bool = False
        self.lastChild: Node | None = None
        self.nextSibling: Node | None = None
        self.nodeType: int = 0
        self.nodeValue: str | None = None
        self.ownerDocument: Document | None = None
        self.parentElement: Element | None = None

    @nojs
    def __getattr__(self, name):
        return _node_attribute(self, name)

    @property
    def textContent(self) -> str | None:
        """Fallback storage for node kinds without specialized text semantics."""
        return self.__dict__.get("textContent", "")

    @textContent.setter
    def textContent(self, value: str | None):
        self.__dict__["textContent"] = value

    @property
    def parentNode(self) -> Node | None:
        try:
            parent = object.__getattribute__(self, "_pyjs_parent")
        except AttributeError:
            return None
        return parent()

    @parentNode.setter
    def parentNode(self, value: Node | None):
        if value is None:
            try:
                object.__delattr__(self, "_pyjs_parent")
            except AttributeError:
                pass
        else:
            object.__setattr__(self, "_pyjs_parent", weakref.ref(value))

    ATTRIBUTE_NODE = 2
    CDATA_SECTION_NODE = 4
    COMMENT_NODE = 8
    DOCUMENT_FRAGMENT_NODE = 11
    DOCUMENT_NODE = 9
    DOCUMENT_POSITION_CONTAINED_BY = 16
    DOCUMENT_POSITION_CONTAINS = 8
    DOCUMENT_POSITION_DISCONNECTED = 1
    DOCUMENT_POSITION_FOLLOWING = 4
    DOCUMENT_POSITION_IMPLEMENTATION_SPECIFIC = 32
    DOCUMENT_POSITION_PRECEDING = 2
    DOCUMENT_TYPE_NODE = 10
    ELEMENT_NODE = 1
    ENTITY_NODE = 6
    ENTITY_REFERENCE_NODE = 5
    NOTATION_NODE = 12
    PROCESSING_INSTRUCTION_NODE = 7
    TEXT_NODE = 3

    def appendChild(self, node: Node) -> Node: ...

    def cloneNode(self, subtree: bool = False) -> Node: ...

    def compareDocumentPosition(self, other: Node) -> int: ...

    def contains(self, other: Node | None) -> bool: ...

    def getRootNode(self, *, composed: bool = False) -> Node: ...

    def hasChildNodes(self) -> bool: ...

    def insertBefore(self, node: Node, child: Node | None) -> Node: ...

    def isDefaultNamespace(self, namespace: str | None) -> bool: ...

    def isEqualNode(self, otherNode: Node | None) -> bool: ...

    def isSameNode(self, otherNode: Node | None) -> bool: ...

    def lookupNamespaceURI(self, prefix: str | None) -> str | None: ...

    def lookupPrefix(self, namespace: str | None) -> str | None: ...

    def normalize(self) -> None: ...

    def removeChild(self, child: Node) -> Node: ...

    def replaceChild(self, node: Node, child: Node) -> Node: ...


@js.native
class NodeFilter:
    """WebIDL source: @webref/idl/dom.idl"""

    FILTER_ACCEPT = 1
    FILTER_REJECT = 2
    FILTER_SKIP = 3
    SHOW_ALL = 4294967295
    SHOW_ATTRIBUTE = 2
    SHOW_CDATA_SECTION = 8
    SHOW_COMMENT = 128
    SHOW_DOCUMENT = 256
    SHOW_DOCUMENT_FRAGMENT = 1024
    SHOW_DOCUMENT_TYPE = 512
    SHOW_ELEMENT = 1
    SHOW_ENTITY = 32
    SHOW_ENTITY_REFERENCE = 16
    SHOW_NOTATION = 2048
    SHOW_PROCESSING_INSTRUCTION = 64
    SHOW_TEXT = 4

    def acceptNode(self, node: Node) -> int: ...


@js.native
class NodeIterator:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NodeIterator

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.filter: NodeFilter | None = None
        self.pointerBeforeReferenceNode: bool = False
        self.referenceNode: Node = None
        self.root: Node = None
        self.whatToShow: int = 0

    def detach(self) -> None: ...

    def nextNode(self) -> Node | None: ...

    def previousNode(self) -> Node | None: ...


@js.native
class NodeList[T]:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NodeList

    Browser support: Chrome 1, Safari 1"""

    __slots__ = ("_items",)

    def __init__(self, items: list[T] | None = None):
        self._items = [] if items is None else items

    @property
    def length(self) -> int:
        return len(self._items)

    @js.inline("{self}[{index}]")
    def __getitem__(self, index: int) -> T:
        return self._items[index]

    @js.inline("{self}[Symbol.iterator]()")
    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

    @js.inline("{self}.length")
    def __len__(self) -> int:
        return len(self._items)

    @js.inline("{self}[{index}]")
    def item(self, index: int) -> Node | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def _append(self, item: T) -> None:
        self._items.append(item)

    def _clear(self) -> None:
        self._items.clear()

    def _remove(self, item: T) -> None:
        self._items.remove(item)


@js.native
class OffscreenCanvas(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/OffscreenCanvas

    Browser support: Chrome 69, Safari 16.4"""

    pass


@js.native
class PluginArray:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/PluginArray

    Browser support: Chrome 1, Safari 1"""

    pass


@js.dictionary
class QuotaExceededErrorOptions:
    """WebIDL source: @webref/idl/webidl.idl"""

    def __init__(self, quota: float | None = None, requested: float | None = None):
        if quota is not None:
            self.quota = quota
        if requested is not None:
            self.requested = requested


@js.native
class ResizeObserver:
    """WebIDL source: @webref/idl/resize-observer.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ResizeObserver

    Browser support: Chrome 64, Safari 13.1"""

    def __init__(self, callback: callable): ...

    def disconnect(self) -> None: ...

    def observe(self, target: Element, *, box: str = "content-box") -> None: ...

    def unobserve(self, target: Element) -> None: ...


@js.native
class ResizeObserverEntry:
    """WebIDL source: @webref/idl/resize-observer.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ResizeObserverEntry

    Browser support: Chrome 64, Safari 13.1"""

    def __init__(self):
        self.borderBoxSize: list[ResizeObserverSize] = []
        self.contentBoxSize: list[ResizeObserverSize] = []
        self.contentRect: DOMRectReadOnly = None
        self.devicePixelContentBoxSize: list[ResizeObserverSize] = []
        self.target: Element = None


@js.dictionary
class ResizeObserverOptions:
    """WebIDL source: @webref/idl/resize-observer.idl"""

    def __init__(self, box: str = "content-box"):
        self.box = box


@js.native
class ResizeObserverSize:
    """WebIDL source: @webref/idl/resize-observer.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ResizeObserverSize

    Browser support: Chrome 84, Safari 15.4"""

    def __init__(self):
        self.blockSize: float = 0.0
        self.inlineSize: float = 0.0


@js.native
class Screen:
    """WebIDL source: @webref/idl/cssom-view.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Screen

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.availHeight: int = 0
        self.availWidth: int = 0
        self.colorDepth: int = 0
        self.height: int = 0
        self.pixelDepth: int = 0
        self.width: int = 0


@js.dictionary
class ScrollOptions:
    """WebIDL source: @webref/idl/cssom-view.idl"""

    def __init__(self, behavior: str = "auto"):
        self.behavior = behavior


@js.dictionary
class ShadowRootInit:
    """WebIDL source: @webref/idl/dom.idl"""

    def __init__(
        self,
        mode: str,
        clonable: bool = False,
        customElementRegistry: CustomElementRegistry | None = None,
        delegatesFocus: bool = False,
        serializable: bool = False,
        slotAssignment: str = "named",
    ):
        self.mode = mode
        self.clonable = clonable
        self.customElementRegistry = customElementRegistry
        self.delegatesFocus = delegatesFocus
        self.serializable = serializable
        self.slotAssignment = slotAssignment


@js.dictionary
class StructuredSerializeOptions:
    """WebIDL source: @webref/idl/html.idl"""

    def __init__(self, transfer: list[object] | None = None):
        if transfer is None:
            transfer = []
        self.transfer = transfer


@js.native
class StyleSheet:
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/StyleSheet

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.disabled: bool = False
        self.href: str | None = None
        self.media: MediaList = None
        self.ownerNode: Element | ProcessingInstruction | None = None
        self.parentStyleSheet: CSSStyleSheet | None = None
        self.title: str | None = None
        self.type: str = ""


@js.native
class StyleSheetList:
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/StyleSheetList

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.length: int = 0

    def item(self, index: int) -> CSSStyleSheet | None: ...


@js.native
class TreeWalker:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TreeWalker

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.currentNode: Node = None
        self.filter: NodeFilter | None = None
        self.root: Node = None
        self.whatToShow: int = 0

    def firstChild(self) -> Node | None: ...

    def lastChild(self) -> Node | None: ...

    def nextNode(self) -> Node | None: ...

    def nextSibling(self) -> Node | None: ...

    def parentNode(self) -> Node | None: ...

    def previousNode(self) -> Node | None: ...

    def previousSibling(self) -> Node | None: ...


@js.native
class XPathEvaluator:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/XPathEvaluator

    Browser support: Chrome 1, Safari 3"""

    def __init__(self): ...

    def createExpression(
        self, expression: str, resolver: XPathNSResolver | None = None
    ) -> XPathExpression: ...

    def createNSResolver(self, nodeResolver: Node) -> Node: ...

    def evaluate(
        self,
        expression: str,
        contextNode: Node,
        resolver: XPathNSResolver | None = None,
        type: int = 0,
        result: XPathResult | None = None,
    ) -> XPathResult: ...


@js.native
class XPathExpression:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/XPathExpression

    Browser support: Chrome 1, Safari 3"""

    def evaluate(
        self, contextNode: Node, type: int = 0, result: XPathResult | None = None
    ) -> XPathResult: ...


@js.native
class XPathNSResolver:
    """WebIDL source: @webref/idl/dom.idl"""

    def lookupNamespaceURI(self, prefix: str | None) -> str | None: ...


@js.native
class XPathResult:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/XPathResult

    Browser support: Chrome 1, Safari 3"""

    ANY_TYPE = 0
    ANY_UNORDERED_NODE_TYPE = 8
    BOOLEAN_TYPE = 3
    FIRST_ORDERED_NODE_TYPE = 9
    NUMBER_TYPE = 1
    ORDERED_NODE_ITERATOR_TYPE = 5
    ORDERED_NODE_SNAPSHOT_TYPE = 7
    STRING_TYPE = 2
    UNORDERED_NODE_ITERATOR_TYPE = 4
    UNORDERED_NODE_SNAPSHOT_TYPE = 6

    def __init__(self):
        self.booleanValue: bool = False
        self.invalidIteratorState: bool = False
        self.numberValue: float = 0.0
        self.resultType: int = 0
        self.singleNodeValue: Node | None = None
        self.snapshotLength: int = 0
        self.stringValue: str = ""

    def iterateNext(self) -> Node | None: ...

    def snapshotItem(self, index: int) -> Node | None: ...


@js.native
class XSLTProcessor:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/XSLTProcessor

    Browser support: Chrome 1, Safari 3.1"""

    def __init__(self): ...

    def clearParameters(self) -> None: ...

    def getParameter(self, namespaceURI: str, localName: str) -> object: ...

    def importStylesheet(self, style: Node) -> None: ...

    def removeParameter(self, namespaceURI: str, localName: str) -> None: ...

    def reset(self) -> None: ...

    def setParameter(self, namespaceURI: str, localName: str, value: object) -> None: ...

    def transformToDocument(self, source: Node) -> Document: ...

    def transformToFragment(self, source: Node, output: Document) -> DocumentFragment: ...


@js.dictionary
class StaticRangeInit:
    """WebIDL source: @webref/idl/dom.idl"""

    def __init__(
        self, endContainer: Node, endOffset: int, startContainer: Node, startOffset: int
    ):
        self.endContainer = endContainer
        self.endOffset = endOffset
        self.startContainer = startContainer
        self.startOffset = startOffset


@js.native
class Storage:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Storage

    Browser support: Chrome 4, Safari 4"""

    def __init__(self):
        self.length: int = 0

    def clear(self) -> None: ...

    def getItem(self, key: str) -> str | None: ...

    def setItem(self, key: str, value: str) -> None: ...

    def key(self, index: int) -> str | None: ...

    def removeItem(self, key: str) -> None: ...


sessionStorage = Storage()
js.native(sessionStorage)
localStorage = Storage()
js.native(localStorage)


@js.native
class Clipboard:
    """WebIDL source: @webref/idl/clipboard-apis.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Clipboard

    Browser support: Chrome 66, Safari 13.1"""

    async def readText(self) -> str: ...

    async def writeText(self, value: str): ...


@js.native
class Navigation(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Navigation

    Browser support: Chrome 102, Safari 26.2"""

    pass


@js.native
class Navigator:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Navigator

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.clipboard: Clipboard = Clipboard()
        self.appCodeName: str = ""
        self.appName: str = ""
        self.appVersion: str = ""
        self.cookieEnabled: bool = False
        self.hardwareConcurrency: int = 0
        self.language: str = ""
        self.languages: list[str] = []
        self.mimeTypes: MimeTypeArray = None
        self.onLine: bool = False
        self.pdfViewerEnabled: bool = False
        self.platform: str = ""
        self.plugins: PluginArray = None
        self.product: str = ""
        self.productSub: str = ""
        self.userActivation: UserActivation = None
        self.userAgent: str = ""
        self.vendor: str = ""
        self.vendorSub: str = ""

    def javaEnabled(self) -> bool: ...

    def registerProtocolHandler(self, scheme: str, url: str) -> None: ...

    def unregisterProtocolHandler(self, scheme: str, url: str) -> None: ...


navigator = Navigator()
js.native(navigator)


@js.native
class MediaQueryList(EventTarget):
    """WebIDL source: @webref/idl/cssom-view.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MediaQueryList

    Browser support: Chrome 9, Safari 5.1"""

    def __init__(self):
        super().__init__()
        self.matches: bool = False
        self.media: str = ""
        self.onchange: callable = None

    def addListener(self, callback: EventListener | None) -> None: ...

    def removeListener(self, callback: EventListener | None) -> None: ...


@js.native
class TrustedScript:
    """WebIDL source: @webref/idl/trusted-types.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TrustedScript

    Browser support: Chrome 83, Safari 26"""

    pass


@js.native
class UserActivation:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/UserActivation

    Browser support: Chrome 72, Safari 16.4"""

    pass


@js.native
class VideoFrame:
    """WebIDL source: @webref/idl/webcodecs.idl

    MDN: https://developer.mozilla.org/docs/Web/API/VideoFrame

    Browser support: Chrome 94, Safari 16.4"""

    pass


@js.native
class VisualViewport(EventTarget):
    """WebIDL source: @webref/idl/cssom-view.idl

    MDN: https://developer.mozilla.org/docs/Web/API/VisualViewport

    Browser support: Chrome 61, Safari 13"""

    def __init__(self):
        super().__init__()
        self.height: float = 0.0
        self.offsetLeft: float = 0.0
        self.offsetTop: float = 0.0
        self.onresize: callable = None
        self.onscroll: callable = None
        self.onscrollend: callable = None
        self.pageLeft: float = 0.0
        self.pageTop: float = 0.0
        self.scale: float = 0.0
        self.width: float = 0.0


@js.native
class Window(EventTarget):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Window

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.console: Console = Console()
        self.clientInformation: Navigator = None
        self.closed: bool = False
        self.crossOriginIsolated: bool = False
        self.customElements: CustomElementRegistry = None
        self.devicePixelRatio: float = 0.0
        self.document: Document = None
        self.event: Event | None = None
        self.ongotpointercapture: callable = None
        self.onlostpointercapture: callable = None
        self.onpointercancel: callable = None
        self.onpointerdown: callable = None
        self.onpointerenter: callable = None
        self.onpointerleave: callable = None
        self.onpointermove: callable = None
        self.onpointerout: callable = None
        self.onpointerover: callable = None
        self.onpointerrawupdate: callable = None
        self.onpointerup: callable = None
        self.external: External = None
        self.frameElement: Element | None = None
        self.frames: Window = None
        self.history: History = None
        self.innerHeight: int = 0
        self.innerWidth: int = 0
        self.isSecureContext: bool = False
        self.length: int = 0
        self.localStorage: Storage = None
        self.location: Location = None
        self.locationbar: BarProp = None
        self.menubar: BarProp = None
        self.name: str = ""
        self.navigation: Navigation = None
        self.navigator: Navigator = None
        self.onabort: callable = None
        self.onafterprint: callable = None
        self.onauxclick: callable = None
        self.onbeforeinput: callable = None
        self.onbeforematch: callable = None
        self.onbeforeprint: callable = None
        self.onbeforetoggle: callable = None
        self.onbeforeunload: callable | None = None
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
        self.onfocus: callable = None
        self.onformdata: callable = None
        self.onhashchange: callable = None
        self.oninput: callable = None
        self.oninvalid: callable = None
        self.onkeydown: callable = None
        self.onkeypress: callable = None
        self.onkeyup: callable = None
        self.onlanguagechange: callable = None
        self.onload: callable = None
        self.onloadeddata: callable = None
        self.onloadedmetadata: callable = None
        self.onloadstart: callable = None
        self.onmessage: callable = None
        self.onmessageerror: callable = None
        self.onmousedown: callable = None
        self.onmouseenter: callable = None
        self.onmouseleave: callable = None
        self.onmousemove: callable = None
        self.onmouseout: callable = None
        self.onmouseover: callable = None
        self.onmouseup: callable = None
        self.onoffline: callable = None
        self.ononline: callable = None
        self.onpagehide: callable = None
        self.onpagereveal: callable = None
        self.onpageshow: callable = None
        self.onpageswap: callable = None
        self.onpaste: callable = None
        self.onpause: callable = None
        self.onplay: callable = None
        self.onplaying: callable = None
        self.onpopstate: callable = None
        self.onprogress: callable = None
        self.onratechange: callable = None
        self.onrejectionhandled: callable = None
        self.onreset: callable = None
        self.onresize: callable = None
        self.onscroll: callable = None
        self.onscrollend: callable = None
        self.onsecuritypolicyviolation: callable = None
        self.onseeked: callable = None
        self.onseeking: callable = None
        self.onselect: callable = None
        self.onslotchange: callable = None
        self.onstalled: callable = None
        self.onstorage: callable = None
        self.onsubmit: callable = None
        self.onsuspend: callable = None
        self.ontimeupdate: callable = None
        self.ontoggle: callable = None
        self.onunhandledrejection: callable = None
        self.onunload: callable = None
        self.onvolumechange: callable = None
        self.onwaiting: callable = None
        self.onwebkitanimationend: callable = None
        self.onwebkitanimationiteration: callable = None
        self.onwebkitanimationstart: callable = None
        self.onwebkittransitionend: callable = None
        self.onwheel: callable = None
        self.opener: object = None
        self.origin: str = ""
        self.originAgentCluster: bool = False
        self.outerHeight: int = 0
        self.outerWidth: int = 0
        self.pageXOffset: float = 0.0
        self.pageYOffset: float = 0.0
        self.parent: Window | None = None
        self.personalbar: BarProp = None
        self.screen: Screen = None
        self.screenLeft: int = 0
        self.screenTop: int = 0
        self.screenX: int = 0
        self.screenY: int = 0
        self.scrollbars: BarProp = None
        self.scrollX: float = 0.0
        self.scrollY: float = 0.0
        self.self: Window = None
        self.sessionStorage: Storage = None
        self.status: str = ""
        self.statusbar: BarProp = None
        self.toolbar: BarProp = None
        self.top: Window | None = None
        self.visualViewport: VisualViewport | None = None
        self.window: Window = None

    @js.inline("new {self}.Function({source})")
    def Function(self, source: str) -> callable: ...

    def matchMedia(self, query: str) -> MediaQueryList: ...

    @js.inline("{self}[{name}]")
    def __getitem__(self, name: str) -> object: ...

    def alert(self) -> None: ...

    def atob(self, data: str) -> str: ...

    def blur(self) -> None: ...

    def btoa(self, data: str) -> str: ...

    def cancelAnimationFrame(self, handle: int) -> None: ...

    def captureEvents(self) -> None: ...

    def clearInterval(self, id: int = 0) -> None: ...

    def clearTimeout(self, id: int = 0) -> None: ...

    def close(self) -> None: ...

    def confirm(self, message: str = "") -> bool: ...

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

    def focus(self) -> None: ...

    def getComputedStyle(
        self, elt: Element, pseudoElt: str | None = None
    ) -> CSSStyleProperties: ...

    def moveBy(self, x: int, y: int) -> None: ...

    def moveTo(self, x: int, y: int) -> None: ...

    def open(
        self, url: str = "", target: str = "_blank", features: str = ""
    ) -> Window | None: ...

    def postMessage(
        self, message: object, targetOrigin: str, transfer: list[object] | None = None
    ) -> None: ...

    def print(self) -> None: ...

    def prompt(self, message: str = "", default: str = "") -> str | None: ...

    def queueMicrotask(self, callback: callable) -> None: ...

    def releaseEvents(self) -> None: ...

    def reportError(self, e: object) -> None: ...

    def requestAnimationFrame(self, callback: callable) -> int: ...

    def resizeBy(self, x: int, y: int) -> None: ...

    def resizeTo(self, width: int, height: int) -> None: ...

    async def scroll(
        self,
        *,
        behavior: str = "auto",
        left: float | None = None,
        top: float | None = None,
    ) -> None: ...

    async def scrollBy(
        self,
        *,
        behavior: str = "auto",
        left: float | None = None,
        top: float | None = None,
    ) -> None: ...

    async def scrollTo(
        self,
        *,
        behavior: str = "auto",
        left: float | None = None,
        top: float | None = None,
    ) -> None: ...

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

    def stop(self) -> None: ...

    def structuredClone(
        self, value: object, *, transfer: list[object] | None = None
    ) -> object: ...


window = Window()
js.native(window)


@js.native
class IntersectionObserver:
    """WebIDL source: @webref/idl/intersection-observer.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IntersectionObserver

    Browser support: Chrome 51, Safari 12.1"""

    def __init__(
        self, callback: callable, options: IntersectionObserverInit | None = None
    ):
        self.delay: int = 0
        self.root: Element | Document | None = None
        self.rootMargin: str = ""
        self.scrollMargin: str = ""
        self.thresholds: list[float] = []
        self.trackVisibility: bool = False

    def disconnect(self) -> None: ...

    def observe(self, target: Element) -> None: ...

    def takeRecords(self) -> list[IntersectionObserverEntry]: ...

    def unobserve(self, target: Element) -> None: ...


@js.native
class IntersectionObserverEntry:
    """WebIDL source: @webref/idl/intersection-observer.idl

    MDN: https://developer.mozilla.org/docs/Web/API/IntersectionObserverEntry

    Browser support: Chrome 51, Safari 12.1"""

    def __init__(self, intersectionObserverEntryInit: IntersectionObserverEntryInit):
        self.boundingClientRect: DOMRectReadOnly = None
        self.intersectionRatio: float = 0.0
        self.intersectionRect: DOMRectReadOnly = None
        self.isIntersecting: bool = False
        self.isVisible: bool = False
        self.rootBounds: DOMRectReadOnly | None = None
        self.target: Element = None
        self.time: float = 0.0


@js.dictionary
class IntersectionObserverEntryInit:
    """WebIDL source: @webref/idl/intersection-observer.idl"""

    def __init__(
        self,
        boundingClientRect: DOMRectInit,
        intersectionRatio: float,
        intersectionRect: DOMRectInit,
        isIntersecting: bool,
        isVisible: bool,
        rootBounds: DOMRectInit | None,
        target: Element,
        time: float,
    ):
        self.boundingClientRect = boundingClientRect
        self.intersectionRatio = intersectionRatio
        self.intersectionRect = intersectionRect
        self.isIntersecting = isIntersecting
        self.isVisible = isVisible
        self.rootBounds = rootBounds
        self.target = target
        self.time = time


@js.dictionary
class IntersectionObserverInit:
    """WebIDL source: @webref/idl/intersection-observer.idl"""

    def __init__(
        self,
        delay: int = 0,
        root: Element | Document | None = None,
        rootMargin: str = "0px",
        scrollMargin: str = "0px",
        threshold: float | list[float] = 0,
        trackVisibility: bool = False,
    ):
        self.delay = delay
        self.root = root
        self.rootMargin = rootMargin
        self.scrollMargin = scrollMargin
        self.threshold = threshold
        self.trackVisibility = trackVisibility


@js.native
class Location:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Location

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.host: str = ""
        self.ancestorOrigins: DOMStringList = None
        self.hash: str = ""
        self.hostname: str = ""
        self.href: str = ""
        self.origin: str = ""
        self.pathname: str = ""
        self.port: str = ""
        self.protocol: str = ""
        self.search: str = ""

    def assign(self, url: str) -> None: ...

    def reload(self) -> None: ...

    def replace(self, url: str) -> None: ...


location = Location()
js.native(location)


@js.dictionary
class ScrollIntoViewOptions:
    """WebIDL source: @webref/idl/cssom-view.idl"""

    def __init__(
        self,
        behavior: str = "auto",
        block: str = "start",
        container: str = "all",
        inline: str = "nearest",
    ):
        self.behavior = behavior
        self.block = block
        self.container = container
        self.inline = inline


@js.dictionary
class ScrollToOptions:
    """WebIDL source: @webref/idl/cssom-view.idl"""

    def __init__(
        self, behavior: str = "auto", left: float | None = None, top: float | None = None
    ):
        self.behavior = behavior
        if left is not None:
            self.left = left
        if top is not None:
            self.top = top


@js.native
class DOMPoint(DOMPointReadOnly):
    """WebIDL source: @webref/idl/geometry.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMPoint

    Browser support: Chrome 61, Safari 10.1"""

    pass


@js.native
class DOMRect(DOMRectReadOnly):
    """WebIDL source: @webref/idl/geometry.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMRect

    Browser support: Chrome 61, Safari 10.1"""

    def __init__(self, x: float = 0, y: float = 0, width: float = 0, height: float = 0):
        super().__init__(x, y, width, height)
        self.x: float = x
        self.y: float = y
        self.left = x
        self.top = y
        self.right = x + width
        self.bottom = y + height
        self.width: float = width
        self.height: float = height

    @staticmethod
    def fromRect(
        *, x: float = 0, y: float = 0, width: float = 0, height: float = 0
    ) -> DOMRect: ...


@js.native
class DocumentType(Node):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DocumentType

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.name: str = ""
        self.publicId: str = ""
        self.systemId: str = ""

    def after(self, *nodes: Node | str) -> None: ...

    def before(self, *nodes: Node | str) -> None: ...

    def remove(self) -> None: ...

    def replaceWith(self, *nodes: Node | str) -> None: ...


@js.native
class DocumentFragment(Node):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DocumentFragment

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.childElementCount: int = 0
        self.children: HTMLCollection[Element] = None
        self.firstElementChild: Element | None = None
        self.lastElementChild: Element | None = None

    def append(self, *nodes: Node | str) -> None: ...

    def getElementById(self, elementId: str) -> Element | None: ...

    def moveBefore(self, node: Node, child: Node | None) -> None: ...

    def prepend(self, *nodes: Node | str) -> None: ...

    def querySelector(self, selectors: str) -> Element | None: ...

    def querySelectorAll(self, selectors: str) -> NodeList[Element]: ...

    def replaceChildren(self, *nodes: Node | str) -> None: ...


_ELEMENT_DEFAULTS = None


def _element_attribute(instance, name):
    global _ELEMENT_DEFAULTS
    if _ELEMENT_DEFAULTS is None:
        properties = {
            name
            for base in Element.__mro__
            for name, value in vars(base).items()
            if isinstance(value, property)
        }
        prototype = Element.__new__(Element)
        object.__setattr__(prototype, "__dict__", _DefaultCollector(Element, properties))
        Element.__init__(prototype)
        _ELEMENT_DEFAULTS = dict(vars(prototype))
    try:
        value = _ELEMENT_DEFAULTS[name]
    except KeyError:
        return _node_attribute(instance, name)
    if value is not None and (not isinstance(value, (bool, int, float, str, bytes))):
        value = type(value)()
        object.__setattr__(instance, name, value)
    return value


@js.native
class Element(Node):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Element

    Browser support: Chrome 1, Safari 1"""

    tagName = "UNDEFINED"
    observedAttributes = []
    __pyjs_ssr_tag_name__ = None
    __slots__ = ("_pyjs_parts", "_pyjs_style")

    def __init__(self):
        data = object.__getattribute__(self, "__dict__")
        if not isinstance(data, _DefaultCollector) or data.owner is not Element:
            return
        super().__init__()
        self.children: HTMLCollection[Element] = HTMLCollection[Element]()
        self.childElementCount: int = 0
        self.assignedSlot: HTMLSlotElement | None = None
        self.attributes: NamedNodeMap[Attr] = NamedNodeMap[Attr]()
        self.classList: DOMTokenList = DOMTokenList()
        self.style = CSSStyleDeclaration()
        self.className: str = ""
        self.clientHeight: int = 0
        self.clientLeft: int = 0
        self.clientTop: int = 0
        self.clientWidth: int = 0
        self.currentCSSZoom: float = 0.0
        self.customElementRegistry: CustomElementRegistry | None = None
        self.firstElementChild: Element | None = None
        self.id: str = ""
        self.lastElementChild: Element | None = None
        self.localName: str = ""
        self.namespaceURI: str | None = None
        self.nextElementSibling: Element | None = None
        self.prefix: str | None = None
        self.previousElementSibling: Element | None = None
        self.scrollHeight: int = 0
        self.scrollLeft: float = 0.0
        self.scrollTop: float = 0.0
        self.scrollWidth: int = 0
        self.shadowRoot: ShadowRoot | None = None
        self.slot: str = ""

    @property
    @nojs
    def _dom(self):
        return object.__getattribute__(self, "__dict__")

    @property
    def textContent(self) -> str:
        return _element_text_content(self, Text)

    @textContent.setter
    def textContent(self, value: str | None):
        _set_element_text_content(self, value)

    @property
    def attributes(self) -> NamedNodeMap[Attr]:
        return NamedNodeMap(_AttributeItems(_parts(self), self), self)

    @attributes.setter
    def attributes(self, value: NamedNodeMap[Attr]):
        """Discard the eager WebIDL default while retaining the sparse view.

        Generated initializers assign this read-only view when an application
        subclass calls ``super().__init__()``.
        """
        pass

    @property
    def childNodes(self) -> NodeList[Node]:
        return NodeList(_ChildNodeItems(_parts(self), self, Text))

    @childNodes.setter
    def childNodes(self, value: NodeList[Node]):
        pass

    @property
    def children(self) -> HTMLCollection[Element]:
        return HTMLCollection(_ElementItems(_parts(self), Element))

    @children.setter
    def children(self, value: HTMLCollection[Element]):
        pass

    @property
    def childElementCount(self) -> int:
        parts = _get_parts(self)
        if parts is None:
            return 0
        return sum(
            isinstance(parts[index], Element)
            for index in range(_child_offset(parts), len(parts))
        )

    @childElementCount.setter
    def childElementCount(self, value: int):
        pass

    @property
    def classList(self) -> DOMTokenList:
        return DOMTokenList(element=self, attribute="class")

    @classList.setter
    def classList(self, value: DOMTokenList):
        """Discard the eager WebIDL default while retaining the sparse view."""
        pass

    @property
    def parentElement(self) -> Element | None:
        parent = self.parentNode
        return parent if isinstance(parent, Element) else None

    @parentElement.setter
    def parentElement(self, value: Element | None):
        self.parentNode = value

    @property
    def style(self) -> CSSStyleProperties:
        try:
            properties = object.__getattribute__(self, "_pyjs_style")
        except AttributeError:
            view = CSSStyleProperties()
            object.__setattr__(self, "_pyjs_style", vars(view))
            return view
        view = CSSStyleProperties.__new__(CSSStyleProperties)
        view.__dict__ = properties
        return view

    @style.setter
    def style(self, value: CSSStyleProperties):
        """Discard the eager WebIDL default while retaining the sparse view."""
        pass

    @nojs
    def __getattr__(self, name):
        return _element_attribute(self, name)

    @nojs
    def __setattr__(self, name, value):
        data = object.__getattribute__(self, "__dict__")
        if isinstance(data, _DefaultCollector):
            if name not in data.properties:
                data[name] = value
            return
        object.__setattr__(self, name, value)

    def getBoundingClientRect(self) -> DOMRect:
        return DOMRect()

    def replaceWith(self, *nodes: Node | str) -> None: ...

    async def scroll(
        self,
        *,
        behavior: str = "auto",
        left: float | None = None,
        top: float | None = None,
    ) -> None: ...

    async def scrollBy(
        self,
        *,
        behavior: str = "auto",
        left: float | None = None,
        top: float | None = None,
    ) -> None: ...

    async def scrollIntoView(
        self,
        *,
        behavior: str = "auto",
        block: str = "start",
        inline: str = "nearest",
        container: str = "all",
    ) -> None:
        """Scroll this element into view using ScrollIntoViewOptions fields.

        The browser boolean ``alignToTop`` overload is not supported, so
        ``element.scrollIntoView(False)`` and ``element.scrollIntoView(True)``
        are not accepted. Pass ``block="end"`` to reproduce
        ``scrollIntoView(false)``, or ``block="start"`` to reproduce
        ``scrollIntoView(true)``.
        """
        ...

    async def scrollTo(
        self,
        *,
        behavior: str = "auto",
        left: float | None = None,
        top: float | None = None,
    ) -> None: ...

    @js
    def setAttribute(self, name: str, value: object | str) -> None:
        attributes = _AttributeItems(_parts(self), self)
        attribute = attributes.get(name)
        old_value = None
        if attribute is not None:
            old_value = attribute if isinstance(attribute, str) else attribute.value
        value = str(value)
        if isinstance(attribute, Attr):
            attribute.value = value
        else:
            attributes[name] = value
        if self._is_observed_attribute(name):
            self.attributeChangedCallback(name, old_value, value)

    def convertPointFromNode(
        self,
        point: DOMPointInit,
        from_: Text | Element | CSSPseudoElement | Document,
        *,
        fromBox: str = "border",
        toBox: str = "border",
    ) -> DOMPoint: ...

    def convertQuadFromNode(
        self,
        quad: DOMQuadInit,
        from_: Text | Element | CSSPseudoElement | Document,
        *,
        fromBox: str = "border",
        toBox: str = "border",
    ) -> DOMQuad: ...

    def convertRectFromNode(
        self,
        rect: DOMRectReadOnly,
        from_: Text | Element | CSSPseudoElement | Document,
        *,
        fromBox: str = "border",
        toBox: str = "border",
    ) -> DOMQuad: ...

    def getAttribute(self, name: str) -> str | None:
        parts = _get_parts(self)
        if parts is None:
            return None
        attribute = _AttributeItems(parts, self).get(name)
        if isinstance(attribute, str) or attribute is None:
            return attribute
        return attribute.value

    @js
    def removeAttribute(self, name: str) -> None:
        parts = _get_parts(self)
        if parts is None:
            return
        attributes = _AttributeItems(parts, self)
        attribute = attributes.pop(name, None)
        if attribute is None:
            return
        if isinstance(attribute, str):
            old_value = attribute
        else:
            old_value = attribute.value
            attribute.ownerElement = None
        if self._is_observed_attribute(name):
            self.attributeChangedCallback(name, old_value, None)

    def getAttributeNames(self) -> list[str]:
        parts = _get_parts(self)
        return [] if parts is None else list(_AttributeItems(parts, self))

    def getAttributeNode(self, qualifiedName: str) -> Attr | None: ...

    def getAttributeNodeNS(
        self, namespace: str | None, localName: str
    ) -> Attr | None: ...

    def getAttributeNS(self, namespace: str | None, localName: str) -> str | None: ...

    def getClientRects(self) -> DOMRectList: ...

    def getElementsByClassName(self, classNames: str) -> HTMLCollection[Element]: ...

    def getElementsByTagName(self, qualifiedName: str) -> HTMLCollection[Element]: ...

    def getElementsByTagNameNS(
        self, namespace: str | None, localName: str
    ) -> HTMLCollection[Element]: ...

    @js
    def hasAttribute(self, name: str) -> bool:
        parts = _get_parts(self)
        return parts is not None and name in _AttributeItems(parts, self)

    @js
    def _is_observed_attribute(self, name: str) -> bool:
        return name in getattr(type(self), "observedAttributes", [])

    def attributeChangedCallback(
        self, name: str, old_value: str | None, new_value: str | None
    ):
        pass

    def after(self, *nodes: Node | str) -> None: ...

    @js
    def append(self, *nodes: Node | str) -> None:
        parts = _parts(self)
        for node in nodes:
            if isinstance(node, str):
                parts.append(node)
            elif isinstance(node, Node):
                node.parentNode = self
                parts.append(node)

    def releasePointerCapture(self, pointerId: int) -> None: ...

    @js
    def remove(self) -> None:
        if self.parentElement is None:
            return
        parent = self.parentElement
        parts = _get_parts(parent)
        if parts is not None:
            _ChildNodeItems(parts, parent, Text).remove(self)
        self.parentNode = None

    def removeAttributeNode(self, attr: Attr) -> Attr: ...

    def removeAttributeNS(self, namespace: str | None, localName: str) -> None: ...

    def insertBefore(self, node: Node, child: Node | None) -> Node:
        if child is not None:
            parts = _get_parts(self)
            offset = 0 if parts is None else _child_offset(parts)
            if parts is None or child not in parts[offset:]:
                error = DOMException(
                    "The node before which the new node is to be inserted is not a child of this node.",
                    "NotFoundError",
                )
                error.code = DOMException.NOT_FOUND_ERR
                raise error
            if node is child:
                return node
        else:
            parts = _parts(self)
        if child is None:
            parent = node.parentNode
            if parent is not None:
                node.remove()
            self.append(node)
            return node
        offset = _child_offset(parts)
        index = parts.index(child, offset)
        parent = node.parentNode
        if parent is not None:
            node.remove()
            if parent is self:
                index = parts.index(child, offset)
        node.parentNode = self
        parts.insert(index, node)
        return node

    def replaceChildren(self, *nodes: Node | str) -> None:
        parts = _get_parts(self)
        if parts is not None:
            del parts[_child_offset(parts) :]
        for node in nodes:
            self.append(node)

    def contains(self, node: Node) -> bool:
        return False

    def attachShadow(self, init: ShadowRootInit) -> ShadowRoot: ...

    def before(self, *nodes: Node | str) -> None: ...

    def checkVisibility(
        self,
        *,
        checkOpacity: bool = False,
        checkVisibilityCSS: bool = False,
        contentVisibilityAuto: bool = False,
        opacityProperty: bool = False,
        visibilityProperty: bool = False,
    ) -> bool: ...

    def closest(self, selectors: str) -> Element | None:
        return self

    def hasAttributeNS(self, namespace: str | None, localName: str) -> bool: ...

    def hasAttributes(self) -> bool: ...

    def hasPointerCapture(self, pointerId: int) -> bool: ...

    def insertAdjacentElement(self, where: str, element: Element) -> Element | None: ...

    def insertAdjacentText(self, where: str, data: str) -> None: ...

    def matches(self, selectors: str) -> bool: ...

    def moveBefore(self, node: Node, child: Node | None) -> None: ...

    def prepend(self, *nodes: Node | str) -> None: ...

    def querySelector(self, selector: str) -> Element | None:
        return self

    def querySelectorAll(self, selector: str) -> NodeList[Element]:
        result: NodeList[Element] = NodeList[Element]()
        result._append(self)
        return result

    def setAttributeNode(self, attr: Attr) -> Attr | None: ...

    def setAttributeNodeNS(self, attr: Attr) -> Attr | None: ...

    def setAttributeNS(
        self, namespace: str | None, qualifiedName: str, value: object | str
    ) -> None: ...

    def setPointerCapture(self, pointerId: int) -> None: ...

    def toggleAttribute(self, qualifiedName: str, force: bool | None = None) -> bool: ...

    def webkitMatchesSelector(self, selectors: str) -> bool: ...


@js.native
class Attr(Node):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Attr

    Browser support: Chrome 1, Safari 1"""

    __slots__ = (
        "localName",
        "name",
        "namespaceURI",
        "ownerElement",
        "prefix",
        "specified",
        "value",
    )

    def __init__(self):
        super().__init__()
        self.localName: str = ""
        self.name: str = ""
        self.namespaceURI: str | None = None
        self.ownerElement: Element | None = None
        self.prefix: str | None = None
        self.specified: bool = False
        self.value: str = ""


@js.native
class CharacterData(Node):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CharacterData

    Browser support: Chrome 1, Safari 1"""

    __slots__ = (
        "data",
        "length",
        "nextElementSibling",
        "previousElementSibling",
        "textContent",
    )

    def __init__(self):
        super().__init__()
        self.data: str = ""
        self.length: int = 0
        self.nextElementSibling: Element | None = None
        self.parentNode: Node | None = None
        self.previousElementSibling: Element | None = None
        self.textContent: str = ""

    def after(self, *nodes: Node | str) -> None: ...

    def appendData(self, data: str) -> None: ...

    def before(self, *nodes: Node | str) -> None: ...

    def deleteData(self, offset: int, count: int) -> None: ...

    def insertData(self, offset: int, data: str) -> None: ...

    def remove(self) -> None: ...

    def replaceData(self, offset: int, count: int, data: str) -> None: ...

    def replaceWith(self, *nodes: Node | str) -> None: ...

    def substringData(self, offset: int, count: int) -> str: ...


@js.native
class CSSGroupingRule(CSSRule):
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CSSGroupingRule

    Browser support: Chrome 45, Safari 14.1"""

    def __init__(self):
        super().__init__()
        self.cssRules: CSSRuleList = None

    def deleteRule(self, index: int) -> None: ...

    def insertRule(self, rule: str, index: int = 0) -> int: ...


@js.native
class CSSImportRule(CSSRule):
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CSSImportRule

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.href: str = ""
        self.layerName: str | None = None
        self.media: MediaList = None
        self.styleSheet: CSSStyleSheet | None = None
        self.supportsText: str | None = None


@js.native
class CSSMarginRule(CSSRule):
    """WebIDL source: @webref/idl/cssom.idl

    Browser support: Chrome 131"""

    def __init__(self):
        super().__init__()
        self.name: str = ""
        self.style: CSSStyleDeclaration = None


@js.native
class CSSNamespaceRule(CSSRule):
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CSSNamespaceRule

    Browser support: Chrome 47, Safari 10.1"""

    def __init__(self):
        super().__init__()
        self.namespaceURI: str = ""
        self.prefix: str = ""


@js.native
class CSSPageDescriptors(CSSStyleDeclaration):
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CSSPageDescriptors

    Browser support: Safari 26"""

    def __init__(self):
        super().__init__()
        self.bleed: str = ""
        self.margin: str = ""
        self.marginBottom: str = ""
        self.marginLeft: str = ""
        self.marginRight: str = ""
        self.marginTop: str = ""
        self.marks: str = ""
        self.size: str = ""


@js.native
class CSSStyleProperties(CSSStyleDeclaration):
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CSSStyleProperties

    Browser support: Safari 26"""

    def __init__(self):
        super().__init__()
        self.cssFloat: str = ""


@js.native
class CSSStyleSheet(StyleSheet):
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CSSStyleSheet

    Browser support: Chrome 1, Safari 1"""

    def __init__(
        self,
        *,
        baseURL: str | None = None,
        media: MediaList | str = "",
        disabled: bool = False,
    ):
        super().__init__()
        self.cssRules: CSSRuleList = None
        self.ownerRule: CSSRule | None = None
        self.rules: CSSRuleList = None

    def addRule(
        self,
        selector: str = "undefined",
        style: str = "undefined",
        index: int | None = None,
    ) -> int: ...

    def deleteRule(self, index: int) -> None: ...

    def insertRule(self, rule: str, index: int = 0) -> int: ...

    def removeRule(self, index: int = 0) -> None: ...

    async def replace(self, text: str) -> CSSStyleSheet: ...

    def replaceSync(self, text: str) -> None: ...


@js.native
class Document(Node):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Document

    Browser support: Chrome 1, Safari 1"""

    nodeName = "#document"

    def __init__(self):
        super().__init__()
        self.adoptedStyleSheets: list[CSSStyleSheet] = []
        self.characterSet: str = ""
        self.charset: str = ""
        self.childElementCount: int = 0
        self.children: HTMLCollection[Element] = None
        self.compatMode: str = ""
        self.contentType: str = ""
        self.customElementRegistry: CustomElementRegistry | None = None
        self.doctype: DocumentType | None = None
        self.documentElement: Element | None = Element()
        self.head = Element()
        self.body = Element()
        self.activeElement: Element | None = None
        self.documentURI: str = ""
        self.firstElementChild: Element | None = None
        self.hidden: bool = False
        self.implementation: DOMImplementation = None
        self.inputEncoding: str = ""
        self.lastElementChild: Element | None = None
        self.ongotpointercapture: callable = None
        self.onlostpointercapture: callable = None
        self.onpointercancel: callable = None
        self.onpointerdown: callable = None
        self.onpointerenter: callable = None
        self.onpointerleave: callable = None
        self.onpointermove: callable = None
        self.onpointerout: callable = None
        self.onpointerover: callable = None
        self.onpointerrawupdate: callable = None
        self.onpointerup: callable = None
        self.scrollingElement: Element | None = None
        self.styleSheets: StyleSheetList = None
        self.URL: str = ""
        self.visibilityState: str = ""

    def adoptNode(self, node: Node) -> Node: ...

    def append(self, *nodes: Node | str) -> None: ...

    def caretPositionFromPoint(
        self, x: float, y: float, *, shadowRoots: list[ShadowRoot] | None = None
    ) -> CaretPosition | None: ...

    def convertPointFromNode(
        self,
        point: DOMPointInit,
        from_: Text | Element | CSSPseudoElement | Document,
        *,
        fromBox: str = "border",
        toBox: str = "border",
    ) -> DOMPoint: ...

    def convertQuadFromNode(
        self,
        quad: DOMQuadInit,
        from_: Text | Element | CSSPseudoElement | Document,
        *,
        fromBox: str = "border",
        toBox: str = "border",
    ) -> DOMQuad: ...

    def convertRectFromNode(
        self,
        rect: DOMRectReadOnly,
        from_: Text | Element | CSSPseudoElement | Document,
        *,
        fromBox: str = "border",
        toBox: str = "border",
    ) -> DOMQuad: ...

    def execCommand(self, commandId: str, showUI: bool = False, value: str = "") -> bool:
        """Invoke a legacy editing command, preserving native editing history.

        Availability is browser-dependent; false means the command was rejected.
        """
        ...

    def createAttribute(self, localName: str) -> Attr: ...

    def createAttributeNS(self, namespace: str | None, qualifiedName: str) -> Attr: ...

    def createCDATASection(self, data: str) -> CDATASection: ...

    def createComment(self, data: str) -> Comment: ...

    def createDocumentFragment(self) -> DocumentFragment: ...

    def createElement(
        self,
        name: str,
        *,
        customElementRegistry: CustomElementRegistry | None = None,
        is_: str | None = None,
    ) -> Element:
        global _html_element_factory
        element_factory = _html_element_factory
        if element_factory is None:
            from pyjs.web.html import _create_html_element

            element_factory = _html_element_factory = _create_html_element
        return element_factory(name)

    def createElementNS(
        self,
        namespace: str | None,
        qualifiedName: str,
        *,
        customElementRegistry: CustomElementRegistry | None = None,
        is_: str | None = None,
    ) -> Element:
        if namespace == "http://www.w3.org/2000/svg":
            from pyjs.web.svg import (
                SVGCircleElement,
                SVGElement,
                SVGGElement,
                SVGLineElement,
                SVGPathElement,
                SVGRectElement,
                SVGSVGElement,
                SVGTextElement,
            )

            element_types = {
                "circle": SVGCircleElement,
                "g": SVGGElement,
                "line": SVGLineElement,
                "path": SVGPathElement,
                "rect": SVGRectElement,
                "svg": SVGSVGElement,
                "text": SVGTextElement,
            }
            element = element_types.get(qualifiedName, SVGElement)()
        else:
            element = Element()
        element.localName = qualifiedName
        element.namespaceURI = namespace
        element.nodeName = element.tagName = qualifiedName
        return element

    def createEvent(self, interface: str) -> Event: ...

    def createExpression(
        self, expression: str, resolver: XPathNSResolver | None = None
    ) -> XPathExpression: ...

    def createNodeIterator(
        self, root: Node, whatToShow: int = 4294967295, filter: NodeFilter | None = None
    ) -> NodeIterator: ...

    def createNSResolver(self, nodeResolver: Node) -> Node: ...

    def createProcessingInstruction(
        self, target: str, data: str
    ) -> ProcessingInstruction: ...

    def createRange(self) -> Range: ...

    def createTextNode(self, data: str) -> Text: ...

    def createTreeWalker(
        self, root: Node, whatToShow: int = 4294967295, filter: NodeFilter | None = None
    ) -> TreeWalker: ...

    def elementFromPoint(self, x: float, y: float) -> Element | None: ...

    def elementsFromPoint(self, x: float, y: float) -> list[Element]: ...

    def evaluate(
        self,
        expression: str,
        contextNode: Node,
        resolver: XPathNSResolver | None = None,
        type: int = 0,
        result: XPathResult | None = None,
    ) -> XPathResult: ...

    def getElementById(self, elementId: str) -> Element | None: ...

    def getElementsByClassName(self, classNames: str) -> HTMLCollection[Element]: ...

    def getElementsByTagName(self, qualifiedName: str) -> HTMLCollection[Element]: ...

    def getElementsByTagNameNS(
        self, namespace: str | None, localName: str
    ) -> HTMLCollection[Element]: ...

    def importNode(
        self,
        node: Node,
        *,
        customElementRegistry: CustomElementRegistry | None = None,
        selfOnly: bool = False,
    ) -> Node: ...

    def moveBefore(self, node: Node, child: Node | None) -> None: ...

    def prepend(self, *nodes: Node | str) -> None: ...

    def querySelector(self, selectors: str) -> Element | None: ...

    def querySelectorAll(self, selectors: str) -> NodeList[Element]: ...

    def replaceChildren(self, *nodes: Node | str) -> None: ...


document = Document()
js.native(document)


@js.native
class QuotaExceededError(DOMException):
    """WebIDL source: @webref/idl/webidl.idl

    MDN: https://developer.mozilla.org/docs/Web/API/QuotaExceededError

    Browser support: Chrome 138"""

    def __init__(
        self,
        message: str = "",
        *,
        quota: float | None = None,
        requested: float | None = None,
    ):
        super().__init__()
        self.quota: float | None = quota
        self.requested: float | None = requested


@js.native
class Range(AbstractRange):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Range

    Browser support: Chrome 1, Safari 1"""

    END_TO_END = 2
    END_TO_START = 3
    START_TO_END = 1
    START_TO_START = 0

    def __init__(self):
        super().__init__()
        self.commonAncestorContainer: Node = None

    def cloneContents(self) -> DocumentFragment: ...

    def cloneRange(self) -> Range: ...

    def collapse(self, toStart: bool = False) -> None: ...

    def compareBoundaryPoints(self, how: int, sourceRange: Range) -> int: ...

    def comparePoint(self, node: Node, offset: int) -> int: ...

    def deleteContents(self) -> None: ...

    def detach(self) -> None: ...

    def extractContents(self) -> DocumentFragment: ...

    def getBoundingClientRect(self) -> DOMRect: ...

    def getClientRects(self) -> DOMRectList: ...

    def insertNode(self, node: Node) -> None: ...

    def intersectsNode(self, node: Node) -> bool: ...

    def isPointInRange(self, node: Node, offset: int) -> bool: ...

    def selectNode(self, node: Node) -> None: ...

    def selectNodeContents(self, node: Node) -> None: ...

    def setEnd(self, node: Node, offset: int) -> None: ...

    def setEndAfter(self, node: Node) -> None: ...

    def setEndBefore(self, node: Node) -> None: ...

    def setStart(self, node: Node, offset: int) -> None: ...

    def setStartAfter(self, node: Node) -> None: ...

    def setStartBefore(self, node: Node) -> None: ...

    def surroundContents(self, newParent: Node) -> None: ...


@js.native
class StaticRange(AbstractRange):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/StaticRange

    Browser support: Chrome 60, Safari 10.1"""

    def __init__(self, init: StaticRangeInit):
        super().__init__()


@js.native
class Comment(CharacterData):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Comment

    Browser support: Chrome 1, Safari 3"""

    def __init__(self, data: str = ""):
        super().__init__()
        self.data = data
        self.length = len(data)
        self.textContent = data


@js.native
class CSSPageRule(CSSGroupingRule):
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CSSPageRule

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.selectorText: str = ""
        self.style: CSSPageDescriptors = None


@js.native
class CSSStyleRule(CSSGroupingRule):
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CSSStyleRule

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.selectorText: str = ""
        self.style: CSSStyleProperties = None


@js.native
class HTMLElement(Element):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLElement

    Browser support: Chrome 1, Safari 1"""

    pass


@js.native
class ProcessingInstruction(CharacterData):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ProcessingInstruction

    Browser support: Chrome 1, Safari 1"""

    def __init__(self, target: str, data: str = ""):
        super().__init__()
        self.data = data
        self.length = len(data)
        self.textContent = data
        self.sheet: CSSStyleSheet | None = None
        self.target: str = target

    def getAttribute(self, name: str) -> str | None: ...

    def getAttributeNames(self) -> list[str]: ...

    def hasAttribute(self, name: str) -> bool: ...

    def hasAttributes(self) -> bool: ...

    def removeAttribute(self, name: str) -> None: ...

    def setAttribute(self, name: str, value: str) -> None: ...

    def toggleAttribute(self, name: str, force: bool | None = None) -> bool: ...


@js.native
class ShadowRoot(DocumentFragment):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/ShadowRoot

    Browser support: Chrome 53, Safari 10"""

    def __init__(self):
        super().__init__()
        self.adoptedStyleSheets: list[CSSStyleSheet] = []
        self.clonable: bool = False
        self.customElementRegistry: CustomElementRegistry | None = None
        self.delegatesFocus: bool = False
        self.host: Element = None
        self.mode: str = ""
        self.onslotchange: callable = None
        self.serializable: bool = False
        self.slotAssignment: str = ""
        self.styleSheets: StyleSheetList = None


@js.native
class SVGElement(Element):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGElement

    Browser support: Chrome 1, Safari 3"""

    pass


@js.native
class Text(CharacterData):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Text

    Browser support: Chrome 1, Safari 1"""

    __slots__ = ("assignedSlot", "wholeText")

    def __init__(self, data: str = ""):
        super().__init__()
        self.data = data
        self.length = len(data)
        self.textContent = data
        self.assignedSlot: HTMLSlotElement | None = None
        self.wholeText: str = ""

    def convertPointFromNode(
        self,
        point: DOMPointInit,
        from_: Text | Element | CSSPseudoElement | Document,
        *,
        fromBox: str = "border",
        toBox: str = "border",
    ) -> DOMPoint: ...

    def convertQuadFromNode(
        self,
        quad: DOMQuadInit,
        from_: Text | Element | CSSPseudoElement | Document,
        *,
        fromBox: str = "border",
        toBox: str = "border",
    ) -> DOMQuad: ...

    def convertRectFromNode(
        self,
        rect: DOMRectReadOnly,
        from_: Text | Element | CSSPseudoElement | Document,
        *,
        fromBox: str = "border",
        toBox: str = "border",
    ) -> DOMQuad: ...

    def splitText(self, offset: int) -> Text: ...


@js.native
class XMLDocument(Document):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/XMLDocument

    Browser support: Chrome 34, Safari 10"""

    pass


@js.native
class HTMLSlotElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLSlotElement

    Browser support: Chrome 53, Safari 10"""

    pass


@js.native
class HTMLMediaElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLMediaElement

    Browser support: Chrome 3, Safari 3.1"""

    pass


@js.native
class HTMLImageElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLImageElement

    Browser support: Chrome 1, Safari 1"""

    pass


@js.native
class HTMLCanvasElement(HTMLElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLCanvasElement

    Browser support: Chrome 1, Safari 2"""

    pass


@js.native
class CDATASection(Text):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CDATASection

    Browser support: Chrome 1, Safari 3"""

    pass


@js.native
class SVGGraphicsElement(SVGElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGGraphicsElement

    Browser support: Chrome 30, Safari 7"""

    pass


@js.native
class HTMLVideoElement(HTMLMediaElement):
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLVideoElement

    Browser support: Chrome 3, Safari 3.1"""

    pass


@js.native
class SVGImageElement(SVGGraphicsElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGImageElement

    Browser support: Chrome 1, Safari 3"""

    pass
