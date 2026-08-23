from pyjs import js
from pyjs.web.dom import (
    DOMRect,
    DOMTokenList,
    Element,
    Node,
    NodeList,
    ShadowRoot,
)
from pyjs.web.events import EventTarget
from pyjs.web.geometry import DOMMatrix, DOMMatrix2DInit, DOMPoint, DOMPointInit


@js.native
class CSSPseudoElement:
    """WebIDL source: @webref/idl/css-pseudo.idl

    MDN: https://developer.mozilla.org/docs/Web/API/CSSPseudoElement

    Browser support: Chrome 149"""

    pass


@js.native
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


@js.native
class SVGAnimatedAngle:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedAngle

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.animVal: SVGAngle = None
        self.baseVal: SVGAngle = None


@js.native
class SVGAnimatedBoolean:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedBoolean

    Browser support: Chrome 6, Safari 5"""

    def __init__(self):
        self.animVal: bool = False
        self.baseVal: bool = False


@js.native
class SVGAnimatedEnumeration:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedEnumeration

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.animVal: int = 0
        self.baseVal: int = 0


@js.native
class SVGAnimatedInteger:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedInteger

    Browser support: Chrome 6, Safari 5"""

    def __init__(self):
        self.animVal: int = 0
        self.baseVal: int = 0


@js.native
class SVGAnimatedLength:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedLength

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.animVal: SVGLength = None
        self.baseVal: SVGLength = None


@js.native
class SVGAnimatedLengthList:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedLengthList

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.animVal: SVGLengthList = None
        self.baseVal: SVGLengthList = None


@js.native
class SVGAnimatedNumber:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedNumber

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.animVal: float = 0.0
        self.baseVal: float = 0.0


@js.native
class SVGAnimatedNumberList:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedNumberList

    Browser support: Chrome 6, Safari 5"""

    def __init__(self):
        self.animVal: SVGNumberList = None
        self.baseVal: SVGNumberList = None


@js.native
class SVGAnimatedPreserveAspectRatio:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedPreserveAspectRatio

    Browser support: Chrome 5, Safari 5"""

    def __init__(self):
        self.animVal: SVGPreserveAspectRatio = None
        self.baseVal: SVGPreserveAspectRatio = None


@js.native
class SVGAnimatedRect:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedRect

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.animVal: DOMRect = None
        self.baseVal: DOMRect = None


@js.native
class SVGAnimatedString:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedString

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.animVal: str = ""
        self.baseVal: str | TrustedScriptURL = None


@js.native
class SVGAnimatedTransformList:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAnimatedTransformList

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.animVal: SVGTransformList = None
        self.baseVal: SVGTransformList = None


@js.dictionary
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


@js.native
class SVGElement(Element):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.className: SVGAnimatedString = None
        self.ownerSVGElement: SVGSVGElement | None = None
        self.viewportElement: SVGElement | None = None


@js.native
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


@js.native
class SVGLengthList:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGLengthList

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.length: int = 0
        self.numberOfItems: int = 0

    @js.inline("{self}[{index}] = {newItem}")
    def __setitem__(self, index: int, newItem: SVGLength) -> None: ...

    def appendItem(self, newItem: SVGLength) -> SVGLength: ...

    def clear(self) -> None: ...

    def getItem(self, index: int) -> SVGLength: ...

    def initialize(self, newItem: SVGLength) -> SVGLength: ...

    def insertItemBefore(self, newItem: SVGLength, index: int) -> SVGLength: ...

    def removeItem(self, index: int) -> SVGLength: ...

    def replaceItem(self, newItem: SVGLength, index: int) -> SVGLength: ...


@js.native
class SVGNumber:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGNumber

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.value: float = 0.0


@js.native
class SVGNumberList:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGNumberList

    Browser support: Chrome 6, Safari 5"""

    def __init__(self):
        self.length: int = 0
        self.numberOfItems: int = 0

    @js.inline("{self}[{index}] = {newItem}")
    def __setitem__(self, index: int, newItem: SVGNumber) -> None: ...

    def appendItem(self, newItem: SVGNumber) -> SVGNumber: ...

    def clear(self) -> None: ...

    def getItem(self, index: int) -> SVGNumber: ...

    def initialize(self, newItem: SVGNumber) -> SVGNumber: ...

    def insertItemBefore(self, newItem: SVGNumber, index: int) -> SVGNumber: ...

    def removeItem(self, index: int) -> SVGNumber: ...

    def replaceItem(self, newItem: SVGNumber, index: int) -> SVGNumber: ...


@js.dictionary
class SVGPathDataSettings:
    """WebIDL source: @webref/idl/svg-paths.idl"""

    def __init__(self, normalize: bool = False):
        self.normalize = normalize


@js.native
class SVGPathSegment:
    """WebIDL source: @webref/idl/svg-paths.idl"""

    def __init__(self):
        self.type: str = ""
        self.values: list[float] = []


@js.native
class SVGPointList:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGPointList

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.length: int = 0
        self.numberOfItems: int = 0

    @js.inline("{self}[{index}] = {newItem}")
    def __setitem__(self, index: int, newItem: DOMPoint) -> None: ...

    def appendItem(self, newItem: DOMPoint) -> DOMPoint: ...

    def clear(self) -> None: ...

    def getItem(self, index: int) -> DOMPoint: ...

    def initialize(self, newItem: DOMPoint) -> DOMPoint: ...

    def insertItemBefore(self, newItem: DOMPoint, index: int) -> DOMPoint: ...

    def removeItem(self, index: int) -> DOMPoint: ...

    def replaceItem(self, newItem: DOMPoint, index: int) -> DOMPoint: ...


@js.native
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


@js.native
class SVGStringList:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGStringList

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.length: int = 0
        self.numberOfItems: int = 0

    @js.inline("{self}[{index}] = {newItem}")
    def __setitem__(self, index: int, newItem: str) -> None: ...

    def appendItem(self, newItem: str) -> str: ...

    def clear(self) -> None: ...

    def getItem(self, index: int) -> str: ...

    def initialize(self, newItem: str) -> str: ...

    def insertItemBefore(self, newItem: str, index: int) -> str: ...

    def removeItem(self, index: int) -> str: ...

    def replaceItem(self, newItem: str, index: int) -> str: ...


@js.native
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


@js.native
class SVGTransformList:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGTransformList

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        self.length: int = 0
        self.numberOfItems: int = 0

    @js.inline("{self}[{index}] = {newItem}")
    def __setitem__(self, index: int, newItem: SVGTransform) -> None: ...

    def appendItem(self, newItem: SVGTransform) -> SVGTransform: ...

    def clear(self) -> None: ...

    def consolidate(self) -> SVGTransform | None: ...

    def createSVGTransformFromMatrix(
        self, matrix: DOMMatrix2DInit | None = None
    ) -> SVGTransform: ...

    def getItem(self, index: int) -> SVGTransform: ...

    def initialize(self, newItem: SVGTransform) -> SVGTransform: ...

    def insertItemBefore(self, newItem: SVGTransform, index: int) -> SVGTransform: ...

    def removeItem(self, index: int) -> SVGTransform: ...

    def replaceItem(self, newItem: SVGTransform, index: int) -> SVGTransform: ...


@js.native
class SVGUnitTypes:
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGUnitTypes

    Browser support: Chrome 1, Safari 3.1"""

    SVG_UNIT_TYPE_OBJECTBOUNDINGBOX = 2
    SVG_UNIT_TYPE_UNKNOWN = 0
    SVG_UNIT_TYPE_USERSPACEONUSE = 1


@js.native
class SVGUseElementShadowRoot(ShadowRoot):
    """WebIDL source: @webref/idl/SVG.idl"""

    pass


@js.native
class TrustedScriptURL:
    """WebIDL source: @webref/idl/trusted-types.idl

    MDN: https://developer.mozilla.org/docs/Web/API/TrustedScriptURL

    Browser support: Chrome 83, Safari 26"""

    pass


@js.native
class Animation(EventTarget):
    """WebIDL source: @webref/idl/web-animations.idl

    MDN: https://developer.mozilla.org/docs/Web/API/Animation

    Browser support: Chrome 75, Safari 13.1"""

    pass


@js.native
class SVGDescElement(SVGElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGDescElement

    Browser support: Chrome 1, Safari 3"""

    pass


@js.native
class SVGGradientElement(SVGElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGGradientElement

    Browser support: Chrome 1, Safari 3"""

    SVG_SPREADMETHOD_PAD = 1
    SVG_SPREADMETHOD_REFLECT = 2
    SVG_SPREADMETHOD_REPEAT = 3
    SVG_SPREADMETHOD_UNKNOWN = 0

    def __init__(self):
        super().__init__()
        self.gradientTransform: SVGAnimatedTransformList = None
        self.gradientUnits: SVGAnimatedEnumeration = None
        self.href: SVGAnimatedString = None
        self.spreadMethod: SVGAnimatedEnumeration = None


@js.native
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


@js.native
class SVGMarkerElement(SVGElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGMarkerElement

    Browser support: Chrome 1, Safari 3"""

    SVG_MARKER_ORIENT_ANGLE = 2
    SVG_MARKER_ORIENT_AUTO = 1
    SVG_MARKER_ORIENT_AUTO_START_REVERSE = 3
    SVG_MARKER_ORIENT_UNKNOWN = 0
    SVG_MARKERUNITS_STROKEWIDTH = 2
    SVG_MARKERUNITS_UNKNOWN = 0
    SVG_MARKERUNITS_USERSPACEONUSE = 1

    def __init__(self):
        super().__init__()
        self.markerHeight: SVGAnimatedLength = None
        self.markerUnits: SVGAnimatedEnumeration = None
        self.markerWidth: SVGAnimatedLength = None
        self.orient: str = ""
        self.orientAngle: SVGAnimatedAngle = None
        self.orientType: SVGAnimatedEnumeration = None
        self.preserveAspectRatio: SVGAnimatedPreserveAspectRatio = None
        self.refX: SVGAnimatedLength = None
        self.refY: SVGAnimatedLength = None
        self.viewBox: SVGAnimatedRect = None

    def setOrientToAngle(self, angle: SVGAngle) -> None: ...

    def setOrientToAuto(self) -> None: ...


@js.native
class SVGMetadataElement(SVGElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGMetadataElement

    Browser support: Chrome 1, Safari 3"""

    pass


@js.native
class SVGPatternElement(SVGElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGPatternElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.height: SVGAnimatedLength = None
        self.href: SVGAnimatedString = None
        self.patternContentUnits: SVGAnimatedEnumeration = None
        self.patternTransform: SVGAnimatedTransformList = None
        self.patternUnits: SVGAnimatedEnumeration = None
        self.preserveAspectRatio: SVGAnimatedPreserveAspectRatio = None
        self.viewBox: SVGAnimatedRect = None
        self.width: SVGAnimatedLength = None
        self.x: SVGAnimatedLength = None
        self.y: SVGAnimatedLength = None


@js.native
class SVGScriptElement(SVGElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGScriptElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.href: SVGAnimatedString = None
        self.type: str = ""


@js.native
class SVGStopElement(SVGElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGStopElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.offset: SVGAnimatedNumber = None


@js.native
class SVGStyleElement(SVGElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGStyleElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.disabled: bool = False
        self.media: str = ""
        self.title: str = ""
        self.type: str = ""


@js.native
class SVGTitleElement(SVGElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGTitleElement

    Browser support: Chrome 1, Safari 3"""

    pass


@js.native
class SVGViewElement(SVGElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGViewElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.preserveAspectRatio: SVGAnimatedPreserveAspectRatio = None
        self.viewBox: SVGAnimatedRect = None


@js.native
class ShadowAnimation(Animation):
    """WebIDL source: @webref/idl/SVG.idl"""

    def __init__(self, source: Animation, newTarget: Element | CSSPseudoElement):
        super().__init__()
        self.sourceAnimation: Animation = None


@js.native
class SVGAElement(SVGGraphicsElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGAElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.download: str = ""
        self.hash: str = ""
        self.host: str = ""
        self.hostname: str = ""
        self.href: SVGAnimatedString = None
        self.hreflang: str = ""
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
        self.target: SVGAnimatedString = None
        self.type: str = ""
        self.username: str = ""


@js.native
class SVGDefsElement(SVGGraphicsElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGDefsElement

    Browser support: Chrome 1, Safari 3"""

    pass


@js.native
class SVGForeignObjectElement(SVGGraphicsElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGForeignObjectElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.height: SVGAnimatedLength = None
        self.width: SVGAnimatedLength = None
        self.x: SVGAnimatedLength = None
        self.y: SVGAnimatedLength = None


@js.native
class SVGGElement(SVGGraphicsElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGGElement

    Browser support: Chrome 1, Safari 3"""

    pass


@js.native
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


@js.native
class SVGImageElement(SVGGraphicsElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGImageElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.crossOrigin: str | None = None
        self.height: SVGAnimatedLength = None
        self.href: SVGAnimatedString = None
        self.preserveAspectRatio: SVGAnimatedPreserveAspectRatio = None
        self.width: SVGAnimatedLength = None
        self.x: SVGAnimatedLength = None
        self.y: SVGAnimatedLength = None


@js.native
class SVGLinearGradientElement(SVGGradientElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGLinearGradientElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.x1: SVGAnimatedLength = None
        self.x2: SVGAnimatedLength = None
        self.y1: SVGAnimatedLength = None
        self.y2: SVGAnimatedLength = None


@js.native
class SVGRadialGradientElement(SVGGradientElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGRadialGradientElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.cx: SVGAnimatedLength = None
        self.cy: SVGAnimatedLength = None
        self.fr: SVGAnimatedLength = None
        self.fx: SVGAnimatedLength = None
        self.fy: SVGAnimatedLength = None
        self.r: SVGAnimatedLength = None


@js.native
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


@js.native
class SVGSwitchElement(SVGGraphicsElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGSwitchElement

    Browser support: Chrome 1, Safari 3"""

    pass


@js.native
class SVGSymbolElement(SVGGraphicsElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGSymbolElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.preserveAspectRatio: SVGAnimatedPreserveAspectRatio = None
        self.viewBox: SVGAnimatedRect = None


@js.native
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


@js.native
class SVGUseElement(SVGGraphicsElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGUseElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.height: SVGAnimatedLength = None
        self.href: SVGAnimatedString = None
        self.width: SVGAnimatedLength = None
        self.x: SVGAnimatedLength = None
        self.y: SVGAnimatedLength = None


@js.native
class SVGCircleElement(SVGGeometryElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGCircleElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.cx: SVGAnimatedLength = None
        self.cy: SVGAnimatedLength = None
        self.r: SVGAnimatedLength = None


@js.native
class SVGEllipseElement(SVGGeometryElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGEllipseElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.cx: SVGAnimatedLength = None
        self.cy: SVGAnimatedLength = None
        self.rx: SVGAnimatedLength = None
        self.ry: SVGAnimatedLength = None


@js.native
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


@js.native
class SVGPathElement(SVGGeometryElement):
    """WebIDL source: @webref/idl/svg-paths.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGPathElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.pathLength: SVGAnimatedNumber = None

    def getPointAtLength(self, distance: float) -> DOMPoint: ...

    def getTotalLength(self) -> float: ...


@js.native
class SVGPolygonElement(SVGGeometryElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGPolygonElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.animatedPoints: SVGPointList = None
        self.points: SVGPointList = None


@js.native
class SVGPolylineElement(SVGGeometryElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGPolylineElement

    Browser support: Chrome 1, Safari 3"""

    def __init__(self):
        super().__init__()
        self.animatedPoints: SVGPointList = None
        self.points: SVGPointList = None


@js.native
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


@js.native
class SVGTextPathElement(SVGTextContentElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGTextPathElement

    Browser support: Chrome 1, Safari 3.1"""

    TEXTPATH_METHODTYPE_ALIGN = 1
    TEXTPATH_METHODTYPE_STRETCH = 2
    TEXTPATH_METHODTYPE_UNKNOWN = 0
    TEXTPATH_SPACINGTYPE_AUTO = 1
    TEXTPATH_SPACINGTYPE_EXACT = 2
    TEXTPATH_SPACINGTYPE_UNKNOWN = 0

    def __init__(self):
        super().__init__()
        self.href: SVGAnimatedString = None
        self.method: SVGAnimatedEnumeration = None
        self.spacing: SVGAnimatedEnumeration = None
        self.startOffset: SVGAnimatedLength = None


@js.native
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


@js.native
class SVGTextElement(SVGTextPositioningElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGTextElement

    Browser support: Chrome 1, Safari 3"""

    pass


@js.native
class SVGTSpanElement(SVGTextPositioningElement):
    """WebIDL source: @webref/idl/SVG.idl

    MDN: https://developer.mozilla.org/docs/Web/API/SVGTSpanElement

    Browser support: Chrome 1, Safari 3"""

    pass
