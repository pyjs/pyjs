from pyjs import js, js_object, js_str, nojs
from pyjs.web.console import Console
from pyjs.web.events import Event, EventTarget


@js
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


@js(builtin=True)
class CustomElementRegistry:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CustomElementRegistry

    Browser support: Chrome 54, Safari 10.1"""

    pass


@js(builtin=True)
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


@js
class DOMRectInit:
    """WebIDL source: @webref/idl/geometry.idl"""

    def __init__(self, height: float = 0, width: float = 0, x: float = 0, y: float = 0):
        self.height = height
        self.width = width
        self.x = x
        self.y = y


@js(builtin=True)
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


@js(builtin=True)
class DOMTokenList:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMTokenList

    Browser support: Chrome 8, Safari 5.1"""

    def __init__(self):
        self.tokens: list[str] = []
        self.length: int = 0
        self.value: str = ""

    def add(self, *tokens: str) -> None:
        self.tokens.extend(tokens)

    @js(inline="{self}[{index}]")
    def item(self, index: int) -> str | None: ...

    def remove(self, *tokens: str) -> None:
        for token in tokens:
            self.tokens.remove(token)

    def replace(self, token: str, newToken: str) -> bool: ...

    def supports(self, token: str) -> bool: ...

    def toggle(self, token: str, force: bool | None = None) -> bool:
        return False

    def contains(self, token: str) -> bool:
        return False


@js(builtin=True)
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


@js(builtin=True)
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


@js(builtin=True)
class CSSRuleList:
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CSSRuleList

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.length: int = 0

    @js(inline="{self}[{index}]")
    def item(self, index: int) -> CSSRule | None: ...


@js(builtin=True)
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

    @js(inline="{self}[{index}]")
    def item(self, index: int) -> str: ...

    def removeProperty(self, property: str) -> str: ...

    def setProperty(self, property: str, value: str, priority: str = "") -> None: ...


@js(builtin=True)
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


@js
class ElementCreationOptions:
    """WebIDL source: @webref/idl/dom.idl"""

    def __init__(
        self,
        customElementRegistry: CustomElementRegistry | None = None,
        is_: str | None = None,
    ):
        self.customElementRegistry = customElementRegistry
        self.is_ = is_


@js
class GetRootNodeOptions:
    """WebIDL source: @webref/idl/dom.idl"""

    def __init__(self, composed: bool = False):
        self.composed = composed


@js(builtin=True)
class HTMLCollection[T]:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLCollection

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self._items: list[T] = []
        self.length: int = 0

    @js(inline="{self}[{index}]")
    def __getitem__(self, index: int) -> T:
        return self._items[index]

    @nojs
    def __iter__(self):
        return iter(self._items)

    @js(inline="{self}.length")
    def __len__(self) -> int:
        return len(self._items)

    @js(inline="{self}[{index}]")
    def item(self, index: int) -> Element | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    @js(inline="{self}[{name}]")
    def namedItem(self, name: str) -> Element | None:
        for item in self._items:
            if item.id == name or item.getAttribute("name") == name:
                return item
        return None

    def _append(self, item: T) -> None:
        self._items.append(item)
        self.length = len(self._items)

    def _clear(self) -> None:
        while self._items:
            self._items.pop()
        self.length = 0

    def _remove(self, item: T) -> None:
        self._items.remove(item)
        self.length = len(self._items)


@js(builtin=True)
class HTMLSlotElement:
    """WebIDL source: @webref/idl/html.idl

    MDN: https://developer.mozilla.org/docs/Web/API/HTMLSlotElement

    Browser support: Chrome 53, Safari 10"""

    pass


@js
class ImportNodeOptions:
    """WebIDL source: @webref/idl/dom.idl"""

    def __init__(
        self,
        customElementRegistry: CustomElementRegistry | None = None,
        selfOnly: bool = False,
    ):
        self.customElementRegistry = customElementRegistry
        self.selfOnly = selfOnly


@js(builtin=True)
class MediaList:
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/MediaList

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.length: int = 0
        self.mediaText: str = ""

    def appendMedium(self, medium: str) -> None: ...

    def deleteMedium(self, medium: str) -> None: ...

    @js(inline="{self}[{index}]")
    def item(self, index: int) -> str | None: ...


@js(builtin=True)
class NamedNodeMap[T]:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NamedNodeMap

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self._attributes: dict[str, T] = {}
        self.length: int = 0

    @js(inline="{self}[{key}]")
    def __getitem__(self, key: int | str) -> T:
        if isinstance(key, int):
            return list(self._attributes.values())[key]
        return self._attributes[key]

    @nojs
    def __iter__(self):
        return iter(self._attributes.values())

    @js(inline="{name} in {self}")
    def __contains__(self, name: str) -> bool:
        return name in self._attributes

    @js(inline="{self}.length")
    def __len__(self) -> int:
        return len(self._attributes)

    @js(inline="{self}[{qualifiedName}]")
    def getNamedItem(self, qualifiedName: str) -> Attr | None:
        return self._attributes.get(qualifiedName)

    def getNamedItemNS(self, namespace: str | None, localName: str) -> Attr | None:
        for attribute in self._attributes.values():
            if attribute.namespaceURI == namespace and attribute.localName == localName:
                return attribute
        return None

    @js(inline="{self}[{index}]")
    def item(self, index: int) -> Attr | None:
        if 0 <= index < len(self._attributes):
            return list(self._attributes.values())[index]
        return None

    def removeNamedItem(self, qualifiedName: str) -> Attr:
        attribute = self._attributes.pop(qualifiedName)
        attribute.ownerElement = None
        self.length = len(self._attributes)
        return attribute

    def removeNamedItemNS(self, namespace: str | None, localName: str) -> Attr:
        attribute = self.getNamedItemNS(namespace, localName)
        if attribute is None:
            raise ValueError(f"Attribute {localName!r} does not exist")
        return self.removeNamedItem(attribute.name)

    def setNamedItem(self, attr: Attr) -> Attr | None:
        previous = self._attributes.get(attr.name)
        self._attributes[attr.name] = attr
        self.length = len(self._attributes)
        return previous

    def setNamedItemNS(self, attr: Attr) -> Attr | None:
        previous = self.getNamedItemNS(attr.namespaceURI, attr.localName)
        if previous is not None:
            if previous.name != attr.name:
                self.removeNamedItem(previous.name)
        self.setNamedItem(attr)
        return previous


@js(builtin=True)
class Node(EventTarget):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Node

    Browser support: Chrome 1, Safari 1"""

    nodeName = "undefined"

    def __init__(self):
        super().__init__()
        self.parentNode: Node | None = None
        self.previousSibling: Node | None = None
        self.textContent: str | None = ""
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


@js(builtin=True)
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


@js(builtin=True)
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


@js(builtin=True)
class Element(Node):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Element

    Browser support: Chrome 1, Safari 1"""

    tagName = js_str("UNDEFINED")
    observedAttributes = []

    def __init__(self):
        super().__init__()
        self.children: HTMLCollection[Element] = HTMLCollection[Element]()
        self.childElementCount: int = 0
        self.assignedSlot: HTMLSlotElement | None = None
        self.attributes: NamedNodeMap[Attr] = NamedNodeMap[Attr]()
        self.classList: DOMTokenList = DOMTokenList()
        self.style = CSSStyleDeclaration()
        self.className: str = ""
        self.customElementRegistry: CustomElementRegistry | None = None
        self.firstElementChild: Element | None = None
        self.id: str = ""
        self.lastElementChild: Element | None = None
        self.localName: str = ""
        self.namespaceURI: str | None = None
        self.nextElementSibling: Element | None = None
        self.prefix: str | None = None
        self.previousElementSibling: Element | None = None
        self.shadowRoot: ShadowRoot | None = None
        self.slot: str = ""
        self.textContent: str = ""

    def getBoundingClientRect(self) -> DOMRect:
        return DOMRect()

    def replaceWith(self, *nodes: Node | str) -> None: ...

    @js
    def setAttribute(self, name: str, value: object | str) -> None:
        attribute = self.attributes.getNamedItem(name)
        old_value: str | None = None
        if attribute is not None:
            old_value = attribute.value
        if attribute is None:
            attribute = Attr()
            attribute.localName = name
            attribute.name = name
        attribute.value = str(value)
        attribute.ownerElement = self
        self.attributes.setNamedItem(attribute)
        if self._is_observed_attribute(name):
            self.attributeChangedCallback(name, old_value, str(value))

    @setAttribute.client
    def setAttribute(self, name: str, value: object | str) -> None:
        pass

    def getAttribute(self, name: str) -> str | None:
        attribute = self.attributes.getNamedItem(name)
        if attribute is None:
            return None
        return attribute.value

    @js
    def removeAttribute(self, name: str) -> None:
        attribute = self.attributes.getNamedItem(name)
        if attribute is not None:
            self.attributes.removeNamedItem(name)
            if self._is_observed_attribute(name):
                self.attributeChangedCallback(name, attribute.value, None)

    @removeAttribute.client
    def removeAttribute(self, name: str) -> None:
        pass

    def getAttributeNames(self) -> list[str]:
        names: list[str] = []
        for attribute in self.attributes:
            names.append(attribute.name)
        return names

    def getAttributeNode(self, qualifiedName: str) -> Attr | None: ...

    def getAttributeNodeNS(
        self, namespace: str | None, localName: str
    ) -> Attr | None: ...

    def getAttributeNS(self, namespace: str | None, localName: str) -> str | None: ...

    def getElementsByClassName(self, classNames: str) -> HTMLCollection[Element]: ...

    def getElementsByTagName(self, qualifiedName: str) -> HTMLCollection[Element]: ...

    def getElementsByTagNameNS(
        self, namespace: str | None, localName: str
    ) -> HTMLCollection[Element]: ...

    @js
    def hasAttribute(self, name: str) -> bool:
        return name in self.attributes

    @hasAttribute.client
    def hasAttribute(self, name: str) -> bool:
        return False

    @js
    def _is_observed_attribute(self, name: str) -> bool:
        return name in getattr(type(self), "observedAttributes", [])

    @_is_observed_attribute.client
    def _is_observed_attribute(self, name: str) -> bool:
        return False

    def attributeChangedCallback(
        self, name: str, old_value: str | None, new_value: str | None
    ):
        pass

    def after(self, *nodes: Node | str) -> None: ...

    def append(self, *nodes: Node | str) -> None:
        for node in nodes:
            if isinstance(node, str):
                text = Text(node)
                self.childNodes._append(text)
            elif isinstance(node, Node):
                self.childNodes._append(node)
                if isinstance(node, Element):
                    self.children._append(node)
        self.childElementCount = len(self.children)

    def remove(self) -> None:
        if self.parentElement is None:
            return
        self.parentElement.childNodes._remove(self)
        self.parentElement.children._remove(self)
        self.parentElement.childElementCount = len(self.parentElement.children)

    def removeAttributeNode(self, attr: Attr) -> Attr: ...

    def removeAttributeNS(self, namespace: str | None, localName: str) -> None: ...

    def replaceChildren(self, *nodes: Node | str) -> None:
        self.childNodes._clear()
        self.children._clear()
        for node in nodes:
            self.append(node)

    def contains(self, node: Node) -> bool:
        return False

    def attachShadow(
        self,
        *,
        mode: str,
        delegatesFocus: bool = False,
        slotAssignment: str = "named",
        clonable: bool = False,
        serializable: bool = False,
        customElementRegistry: CustomElementRegistry | None = None,
    ) -> ShadowRoot: ...

    def before(self, *nodes: Node | str) -> None: ...

    def closest(self, selectors: str) -> Element | None:
        return self

    def hasAttributeNS(self, namespace: str | None, localName: str) -> bool: ...

    def hasAttributes(self) -> bool: ...

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

    def toggleAttribute(self, qualifiedName: str, force: bool | None = None) -> bool: ...

    def webkitMatchesSelector(self, selectors: str) -> bool: ...


@js(builtin=True)
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


@js(builtin=True)
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


@js(builtin=True)
class NodeList[T]:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/NodeList

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self._items: list[T] = []
        self.length: int = 0

    @js(inline="{self}[{index}]")
    def __getitem__(self, index: int) -> T:
        return self._items[index]

    @nojs
    def __iter__(self):
        return iter(self._items)

    @js(inline="{self}.length")
    def __len__(self) -> int:
        return len(self._items)

    @js(inline="{self}[{index}]")
    def item(self, index: int) -> Node | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def _append(self, item: T) -> None:
        self._items.append(item)
        self.length = len(self._items)

    def _clear(self) -> None:
        while self._items:
            self._items.pop()
        self.length = 0

    def _remove(self, item: T) -> None:
        self._items.remove(item)
        self.length = len(self._items)


@js
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


@js(builtin=True)
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


@js(builtin=True)
class StyleSheetList:
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/StyleSheetList

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        self.length: int = 0

    @js(inline="{self}[{index}]")
    def item(self, index: int) -> CSSStyleSheet | None: ...


@js(builtin=True)
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


@js(builtin=True)
class XPathExpression:
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/XPathExpression

    Browser support: Chrome 1, Safari 3"""

    def evaluate(
        self, contextNode: Node, type: int = 0, result: XPathResult | None = None
    ) -> XPathResult: ...


@js(builtin=True)
class XPathNSResolver:
    """WebIDL source: @webref/idl/dom.idl"""

    def lookupNamespaceURI(self, prefix: str | None) -> str | None: ...


@js(builtin=True)
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


@js(builtin=True)
class Attr(Node):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Attr

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.localName: str = ""
        self.name: str = ""
        self.namespaceURI: str | None = None
        self.ownerElement: Element | None = None
        self.prefix: str | None = None
        self.specified: bool = False
        self.value: str = ""


@js(builtin=True)
class CharacterData(Node):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CharacterData

    Browser support: Chrome 1, Safari 1"""

    def __init__(self):
        super().__init__()
        self.data: str = ""
        self.length: int = 0
        self.nextElementSibling: Element | None = None
        self.previousElementSibling: Element | None = None

    def after(self, *nodes: Node | str) -> None: ...

    def appendData(self, data: str) -> None: ...

    def before(self, *nodes: Node | str) -> None: ...

    def deleteData(self, offset: int, count: int) -> None: ...

    def insertData(self, offset: int, data: str) -> None: ...

    def remove(self) -> None: ...

    def replaceData(self, offset: int, count: int, data: str) -> None: ...

    def replaceWith(self, *nodes: Node | str) -> None: ...

    def substringData(self, offset: int, count: int) -> str: ...


@js(builtin=True)
class CSSStyleProperties(CSSStyleDeclaration):
    """WebIDL source: @webref/idl/cssom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CSSStyleProperties

    Browser support: Safari 26"""

    def __init__(self):
        super().__init__()
        self.cssFloat: str = ""


@js(builtin=True)
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


@js(builtin=True)
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
        self.implementation: DOMImplementation = None
        self.inputEncoding: str = ""
        self.lastElementChild: Element | None = None
        self.styleSheets: StyleSheetList = None
        self.URL: str = ""

    def adoptNode(self, node: Node) -> Node: ...

    def append(self, *nodes: Node | str) -> None: ...

    def createAttribute(self, localName: str) -> Attr: ...

    def createAttributeNS(self, namespace: str | None, qualifiedName: str) -> Attr: ...

    def createCDATASection(self, data: str) -> CDATASection: ...

    def createComment(self, data: str) -> Comment: ...

    def createDocumentFragment(self) -> DocumentFragment: ...

    @js(analyze=False)
    def createElement(
        self,
        name: str,
        *,
        customElementRegistry: CustomElementRegistry | None = None,
        is_: str | None = None,
    ) -> Element:
        from pyjs.web.html import HTMLElement

        e = HTMLElement()
        e.nodeName = e.tagName = name.upper()
        return e

    def createElementNS(
        self,
        namespace: str | None,
        qualifiedName: str,
        *,
        customElementRegistry: CustomElementRegistry | None = None,
        is_: str | None = None,
    ) -> Element: ...

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
js_object(document, builtin=True)


@js(builtin=True)
class Storage:
    def getItem(self, key: str) -> str | None: ...

    def setItem(self, key: str, value: str): ...

    def removeItem(self, key: str): ...


sessionStorage = Storage()
js_object(sessionStorage, builtin=True)
localStorage = Storage()
js_object(localStorage, builtin=True)


@js(builtin=True)
class Clipboard:
    async def writeText(self, value: str): ...


@js(builtin=True)
class Navigator:
    def __init__(self):
        self.clipboard = Clipboard()


navigator = Navigator()
js_object(navigator, builtin=True)


@js(builtin=True)
class MediaQueryList(EventTarget):
    def __init__(self):
        super().__init__()
        self.matches = False


@js(builtin=True)
class Crypto:
    def randomUUID(self) -> str: ...


crypto = Crypto()
js_object(crypto, builtin=True)


@js(builtin=True)
class Window(EventTarget):
    def __init__(self):
        super().__init__()
        self.console = Console()

    @js(inline="new {self}.Function({source})")
    def Function(self, source: str) -> callable: ...

    def matchMedia(self, query: str) -> MediaQueryList: ...


window = Window()
js_object(window, builtin=True)


@js(builtin=True)
class Location:
    def __init__(self):
        self.host = ""
        self.hash = ""


location = Location()
js_object(location, builtin=True)


@js(builtin=True)
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


@js(builtin=True)
class Comment(CharacterData):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Comment

    Browser support: Chrome 1, Safari 3"""

    def __init__(self, data: str = ""):
        super().__init__()
        self.data = data
        self.length = len(data)
        self.textContent = data


@js(builtin=True)
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


@js(builtin=True)
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


@js(builtin=True)
class Text(CharacterData):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Text

    Browser support: Chrome 1, Safari 1"""

    def __init__(self, data: str = ""):
        super().__init__()
        self.data = data
        self.length = len(data)
        self.textContent = data
        self.assignedSlot: HTMLSlotElement | None = None
        self.wholeText: str = ""

    def splitText(self, offset: int) -> Text: ...


@js(builtin=True)
class XMLDocument(Document):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/XMLDocument

    Browser support: Chrome 34, Safari 10"""

    pass


@js(builtin=True)
class CDATASection(Text):
    """WebIDL source: @webref/idl/dom.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CDATASection

    Browser support: Chrome 1, Safari 3"""

    pass
