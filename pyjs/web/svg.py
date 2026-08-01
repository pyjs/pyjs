from pyjs import js
from pyjs.web.dom import (
    DOMRect,
    Element,
    Node,
    NodeList,
)
from pyjs.web.geometry import DOMMatrix, DOMMatrix2DInit, DOMPoint, DOMPointInit


@js(builtin=True)
class SVGAngle:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAngle

    Browser support: Chrome 1, Safari 3"""

    SVG_ANGLETYPE_DEG = 2
    SVG_ANGLETYPE_GRAD = 4
    SVG_ANGLETYPE_RAD = 3
    SVG_ANGLETYPE_UNKNOWN = 0
    SVG_ANGLETYPE_UNSPECIFIED = 1

    def __init__(self):
        self.unitType: int = 0
        self.value: float = 0.0
        self.valueAsString: str = ""
        self.valueInSpecifiedUnits: float = 0.0

    def convertToSpecifiedUnits(self, unitType: int) -> None: ...

    def newValueSpecifiedUnits(
        self, unitType: int, valueInSpecifiedUnits: float
    ) -> None: ...


@js(builtin=True)
class SVGAnimatedEnumeration:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedEnumeration

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.animVal: int = 0
        self.baseVal: int = 0


@js(builtin=True)
class SVGAnimatedLength:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedLength

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.animVal: SVGLength = None
        self.baseVal: SVGLength = None


@js(builtin=True)
class SVGAnimatedLengthList:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedLengthList

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.animVal: SVGLengthList = None
        self.baseVal: SVGLengthList = None


@js(builtin=True)
class SVGAnimatedNumber:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedNumber

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.animVal: float = 0.0
        self.baseVal: float = 0.0


@js(builtin=True)
class SVGAnimatedNumberList:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedNumberList

    Browser support: Chrome 6, Safari 5"""

    def __init__(self):
        self.animVal: SVGNumberList = None
        self.baseVal: SVGNumberList = None


@js(builtin=True)
class SVGAnimatedPreserveAspectRatio:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedPreserveAspectRatio

    Browser support: Chrome 5, Safari 5"""

    def __init__(self):
        self.animVal: SVGPreserveAspectRatio = None
        self.baseVal: SVGPreserveAspectRatio = None


@js(builtin=True)
class SVGAnimatedRect:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedRect

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.animVal: DOMRect = None
        self.baseVal: DOMRect = None


@js(builtin=True)
class SVGAnimatedString:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedString

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.animVal: str = ""
        self.baseVal: str | TrustedScriptURL = None


@js(builtin=True)
class SVGAnimatedTransformList:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedTransformList

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.animVal: SVGTransformList = None
        self.baseVal: SVGTransformList = None


@js
class SVGBoundingBoxOptions:
    """WebIDL source: @webref/idl/SVG.idl"""

    def __init__(
        self,
        clipped: bool = False,
        fill: bool = True,
        markers: bool = False,
        stroke: bool = False,
    ):
        self.clipped = clipped
        self.fill = fill
        self.markers = markers
        self.stroke = stroke


@js(builtin=True)
class SVGElement(Element):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.className: SVGAnimatedString = None
        self.ownerSVGElement: SVGSVGElement | None = None
        self.viewportElement: SVGElement | None = None


@js(builtin=True)
class SVGLength:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGLength

    Browser support: Chrome 1, Safari 3"""

    SVG_LENGTHTYPE_CM = 6
    SVG_LENGTHTYPE_EMS = 3
    SVG_LENGTHTYPE_EXS = 4
    SVG_LENGTHTYPE_IN = 8
    SVG_LENGTHTYPE_MM = 7
    SVG_LENGTHTYPE_NUMBER = 1
    SVG_LENGTHTYPE_PC = 10
    SVG_LENGTHTYPE_PERCENTAGE = 2
    SVG_LENGTHTYPE_PT = 9
    SVG_LENGTHTYPE_PX = 5
    SVG_LENGTHTYPE_UNKNOWN = 0

    def __init__(self):
        self.unitType: int = 0
        self.value: float = 0.0
        self.valueAsString: str = ""
        self.valueInSpecifiedUnits: float = 0.0

    def convertToSpecifiedUnits(self, unitType: int) -> None: ...

    def newValueSpecifiedUnits(
        self, unitType: int, valueInSpecifiedUnits: float
    ) -> None: ...


@js(builtin=True)
class SVGLengthList:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGLengthList

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.length: int = 0
        self.numberOfItems: int = 0

    @js(inline="{self}[{index}] = {newItem}")
    def __setitem__(self, index: int, newItem: SVGLength) -> None: ...

    def appendItem(self, newItem: SVGLength) -> SVGLength: ...

    def clear(self) -> None: ...

    @js(inline="{self}[{index}]")
    def getItem(self, index: int) -> SVGLength: ...

    def initialize(self, newItem: SVGLength) -> SVGLength: ...

    def insertItemBefore(self, newItem: SVGLength, index: int) -> SVGLength: ...

    def removeItem(self, index: int) -> SVGLength: ...

    def replaceItem(self, newItem: SVGLength, index: int) -> SVGLength: ...


@js(builtin=True)
class SVGNumber:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGNumber

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.value: float = 0.0


@js(builtin=True)
class SVGNumberList:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGNumberList

    Browser support: Chrome 6, Safari 5"""

    def __init__(self):
        self.length: int = 0
        self.numberOfItems: int = 0

    @js(inline="{self}[{index}] = {newItem}")
    def __setitem__(self, index: int, newItem: SVGNumber) -> None: ...

    def appendItem(self, newItem: SVGNumber) -> SVGNumber: ...

    def clear(self) -> None: ...

    @js(inline="{self}[{index}]")
    def getItem(self, index: int) -> SVGNumber: ...

    def initialize(self, newItem: SVGNumber) -> SVGNumber: ...

    def insertItemBefore(self, newItem: SVGNumber, index: int) -> SVGNumber: ...

    def removeItem(self, index: int) -> SVGNumber: ...

    def replaceItem(self, newItem: SVGNumber, index: int) -> SVGNumber: ...


@js(builtin=True)
class SVGPreserveAspectRatio:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGPreserveAspectRatio

    Browser support: Chrome 1, Safari 3"""

    SVG_MEETORSLICE_MEET = 1
    SVG_MEETORSLICE_SLICE = 2
    SVG_MEETORSLICE_UNKNOWN = 0
    SVG_PRESERVEASPECTRATIO_NONE = 1
    SVG_PRESERVEASPECTRATIO_UNKNOWN = 0
    SVG_PRESERVEASPECTRATIO_XMAXYMAX = 10
    SVG_PRESERVEASPECTRATIO_XMAXYMID = 7
    SVG_PRESERVEASPECTRATIO_XMAXYMIN = 4
    SVG_PRESERVEASPECTRATIO_XMIDYMAX = 9
    SVG_PRESERVEASPECTRATIO_XMIDYMID = 6
    SVG_PRESERVEASPECTRATIO_XMIDYMIN = 3
    SVG_PRESERVEASPECTRATIO_XMINYMAX = 8
    SVG_PRESERVEASPECTRATIO_XMINYMID = 5
    SVG_PRESERVEASPECTRATIO_XMINYMIN = 2

    def __init__(self):
        self.align: int = 0
        self.meetOrSlice: int = 0


@js(builtin=True)
class SVGStringList:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGStringList

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.length: int = 0
        self.numberOfItems: int = 0

    @js(inline="{self}[{index}] = {newItem}")
    def __setitem__(self, index: int, newItem: str) -> None: ...

    def appendItem(self, newItem: str) -> str: ...

    def clear(self) -> None: ...

    @js(inline="{self}[{index}]")
    def getItem(self, index: int) -> str: ...

    def initialize(self, newItem: str) -> str: ...

    def insertItemBefore(self, newItem: str, index: int) -> str: ...

    def removeItem(self, index: int) -> str: ...

    def replaceItem(self, newItem: str, index: int) -> str: ...


@js(builtin=True)
class SVGTransform:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGTransform

    Browser support: Chrome 1, Safari 4"""

    SVG_TRANSFORM_MATRIX = 1
    SVG_TRANSFORM_ROTATE = 4
    SVG_TRANSFORM_SCALE = 3
    SVG_TRANSFORM_SKEWX = 5
    SVG_TRANSFORM_SKEWY = 6
    SVG_TRANSFORM_TRANSLATE = 2
    SVG_TRANSFORM_UNKNOWN = 0

    def __init__(self):
        self.angle: float = 0.0
        self.matrix: DOMMatrix = None
        self.type: int = 0

    def setMatrix(self, matrix: DOMMatrix2DInit | None = None) -> None: ...

    def setRotate(self, angle: float, cx: float, cy: float) -> None: ...

    def setScale(self, sx: float, sy: float) -> None: ...

    def setSkewX(self, angle: float) -> None: ...

    def setSkewY(self, angle: float) -> None: ...

    def setTranslate(self, tx: float, ty: float) -> None: ...


@js(builtin=True)
class SVGTransformList:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGTransformList

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.length: int = 0
        self.numberOfItems: int = 0

    @js(inline="{self}[{index}] = {newItem}")
    def __setitem__(self, index: int, newItem: SVGTransform) -> None: ...

    def appendItem(self, newItem: SVGTransform) -> SVGTransform: ...

    def clear(self) -> None: ...

    def consolidate(self) -> SVGTransform | None: ...

    def createSVGTransformFromMatrix(
        self, matrix: DOMMatrix2DInit | None = None
    ) -> SVGTransform: ...

    @js(inline="{self}[{index}]")
    def getItem(self, index: int) -> SVGTransform: ...

    def initialize(self, newItem: SVGTransform) -> SVGTransform: ...

    def insertItemBefore(self, newItem: SVGTransform, index: int) -> SVGTransform: ...

    def removeItem(self, index: int) -> SVGTransform: ...

    def replaceItem(self, newItem: SVGTransform, index: int) -> SVGTransform: ...


@js(builtin=True)
class TrustedScriptURL:
    """WebIDL source: @webref/idl/trusted-types.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TrustedScriptURL

    Browser support: Chrome 83, Safari 26"""

    pass


@js(builtin=True)
class SVGGraphicsElement(SVGElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGGraphicsElement

    Browser support: Chrome 30, Safari 7"""

    def __init__(self):
        super().__init__()
        self.requiredExtensions: SVGStringList = None
        self.systemLanguage: SVGStringList = None
        self.transform: SVGAnimatedTransformList = None

    def getBBox(
        self,
        *,
        fill: bool = True,
        stroke: bool = False,
        markers: bool = False,
        clipped: bool = False,
    ) -> DOMRect: ...

    def getCTM(self) -> DOMMatrix | None: ...

    def getScreenCTM(self) -> DOMMatrix | None: ...


@js(builtin=True)
class SVGGElement(SVGGraphicsElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGGElement

    Browser support: Chrome 1, Safari 3"""

    pass


@js(builtin=True)
class SVGGeometryElement(SVGGraphicsElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGGeometryElement

    Browser support: Chrome 56, Safari 12"""

    def __init__(self):
        super().__init__()
        self.pathLength: SVGAnimatedNumber = None

    def getPointAtLength(self, distance: float) -> DOMPoint: ...

    def getTotalLength(self) -> float: ...

    def isPointInFill(self, point: DOMPointInit | None = None) -> bool: ...

    def isPointInStroke(self, point: DOMPointInit | None = None) -> bool: ...


@js(builtin=True)
class SVGSVGElement(SVGGraphicsElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGSVGElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.currentScale: float = 0.0
        self.currentTranslate: DOMPoint = None
        self.height: SVGAnimatedLength = None
        self.preserveAspectRatio: SVGAnimatedPreserveAspectRatio = None
        self.viewBox: SVGAnimatedRect = None
        self.width: SVGAnimatedLength = None
        self.x: SVGAnimatedLength = None
        self.y: SVGAnimatedLength = None

    def checkEnclosure(self, element: SVGElement, rect: DOMRect) -> bool: ...

    def checkIntersection(self, element: SVGElement, rect: DOMRect) -> bool: ...

    def createSVGAngle(self) -> SVGAngle: ...

    def createSVGLength(self) -> SVGLength: ...

    def createSVGMatrix(self) -> DOMMatrix: ...

    def createSVGNumber(self) -> SVGNumber: ...

    def createSVGPoint(self) -> DOMPoint: ...

    def createSVGRect(self) -> DOMRect: ...

    def createSVGTransform(self) -> SVGTransform: ...

    def createSVGTransformFromMatrix(
        self, matrix: DOMMatrix2DInit | None = None
    ) -> SVGTransform: ...

    def deselectAll(self) -> None: ...

    def forceRedraw(self) -> None: ...

    def getElementById(self, elementId: str) -> Element | None: ...

    def getEnclosureList(
        self, rect: DOMRect, referenceElement: SVGElement | None
    ) -> NodeList[Node]: ...

    def getIntersectionList(
        self, rect: DOMRect, referenceElement: SVGElement | None
    ) -> NodeList[Node]: ...

    def suspendRedraw(self, maxWaitMilliseconds: int) -> int: ...

    def unsuspendRedraw(self, suspendHandleID: int) -> None: ...

    def unsuspendRedrawAll(self) -> None: ...


@js(builtin=True)
class SVGTextContentElement(SVGGraphicsElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGTextContentElement

    Browser support: Chrome 1, Safari 3"""

    LENGTHADJUST_SPACING = 1
    LENGTHADJUST_SPACINGANDGLYPHS = 2
    LENGTHADJUST_UNKNOWN = 0

    def __init__(self):
        super().__init__()
        self.lengthAdjust: SVGAnimatedEnumeration = None
        self.textLength: SVGAnimatedLength = None

    def getCharNumAtPosition(self, point: DOMPointInit | None = None) -> int: ...

    def getComputedTextLength(self) -> float: ...

    def getEndPositionOfChar(self, charnum: int) -> DOMPoint: ...

    def getExtentOfChar(self, charnum: int) -> DOMRect: ...

    def getNumberOfChars(self) -> int: ...

    def getRotationOfChar(self, charnum: int) -> float: ...

    def getStartPositionOfChar(self, charnum: int) -> DOMPoint: ...

    def getSubStringLength(self, charnum: int, nchars: int) -> float: ...

    def selectSubString(self, charnum: int, nchars: int) -> None: ...


@js(builtin=True)
class SVGCircleElement(SVGGeometryElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGCircleElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.cx: SVGAnimatedLength = None
        self.cy: SVGAnimatedLength = None
        self.r: SVGAnimatedLength = None


@js(builtin=True)
class SVGLineElement(SVGGeometryElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGLineElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.x1: SVGAnimatedLength = None
        self.x2: SVGAnimatedLength = None
        self.y1: SVGAnimatedLength = None
        self.y2: SVGAnimatedLength = None


@js(builtin=True)
class SVGPathElement(SVGGeometryElement):
    """WebIDL source: @webref/idl/svg-paths.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGPathElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.pathLength: SVGAnimatedNumber = None

    def getPointAtLength(self, distance: float) -> DOMPoint: ...

    def getTotalLength(self) -> float: ...


@js(builtin=True)
class SVGRectElement(SVGGeometryElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGRectElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.height: SVGAnimatedLength = None
        self.rx: SVGAnimatedLength = None
        self.ry: SVGAnimatedLength = None
        self.width: SVGAnimatedLength = None
        self.x: SVGAnimatedLength = None
        self.y: SVGAnimatedLength = None


@js(builtin=True)
class SVGTextPositioningElement(SVGTextContentElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGTextPositioningElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.dx: SVGAnimatedLengthList = None
        self.dy: SVGAnimatedLengthList = None
        self.rotate: SVGAnimatedNumberList = None
        self.x: SVGAnimatedLengthList = None
        self.y: SVGAnimatedLengthList = None


@js(builtin=True)
class SVGTextElement(SVGTextPositioningElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGTextElement

    Browser support: Chrome 1, Safari 3"""

    pass
