from pyjs import js
from pyjs.javascript import Float32Array, Float64Array
from pyjs.web.dom import DOMRect, DOMRectInit


@js.dictionary
class DOMMatrix2DInit:
    """WebIDL source: @webref/idl/geometry.idl"""

    def __init__(
        self,
        a: float | None = None,
        b: float | None = None,
        c: float | None = None,
        d: float | None = None,
        e: float | None = None,
        f: float | None = None,
        m11: float | None = None,
        m12: float | None = None,
        m21: float | None = None,
        m22: float | None = None,
        m41: float | None = None,
        m42: float | None = None,
    ):
        self.a = a
        self.b = b
        self.c = c
        self.d = d
        self.e = e
        self.f = f
        self.m11 = m11
        self.m12 = m12
        self.m21 = m21
        self.m22 = m22
        self.m41 = m41
        self.m42 = m42


@js.native
class DOMMatrixReadOnly:
    """WebIDL source: @webref/idl/geometry.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMMatrixReadOnly

    Browser support: Chrome 61, Safari 11"""

    def __init__(self, init: str | list[float] | None = None):
        self.a: float = 0.0
        self.b: float = 0.0
        self.c: float = 0.0
        self.d: float = 0.0
        self.e: float = 0.0
        self.f: float = 0.0
        self.is2D: bool = False
        self.isIdentity: bool = False
        self.m11: float = 0.0
        self.m12: float = 0.0
        self.m13: float = 0.0
        self.m14: float = 0.0
        self.m21: float = 0.0
        self.m22: float = 0.0
        self.m23: float = 0.0
        self.m24: float = 0.0
        self.m31: float = 0.0
        self.m32: float = 0.0
        self.m33: float = 0.0
        self.m34: float = 0.0
        self.m41: float = 0.0
        self.m42: float = 0.0
        self.m43: float = 0.0
        self.m44: float = 0.0

    def flipX(self) -> DOMMatrix: ...

    def flipY(self) -> DOMMatrix: ...

    @staticmethod
    def fromFloat32Array(array32: Float32Array) -> DOMMatrixReadOnly: ...

    @staticmethod
    def fromFloat64Array(array64: Float64Array) -> DOMMatrixReadOnly: ...

    @staticmethod
    def fromMatrix(
        *,
        a: float | None = None,
        b: float | None = None,
        c: float | None = None,
        d: float | None = None,
        e: float | None = None,
        f: float | None = None,
        m11: float | None = None,
        m12: float | None = None,
        m21: float | None = None,
        m22: float | None = None,
        m41: float | None = None,
        m42: float | None = None,
        m13: float = 0,
        m14: float = 0,
        m23: float = 0,
        m24: float = 0,
        m31: float = 0,
        m32: float = 0,
        m33: float = 1,
        m34: float = 0,
        m43: float = 0,
        m44: float = 1,
        is2D: bool | None = None,
    ) -> DOMMatrixReadOnly: ...

    def inverse(self) -> DOMMatrix: ...

    def multiply(
        self,
        *,
        a: float | None = None,
        b: float | None = None,
        c: float | None = None,
        d: float | None = None,
        e: float | None = None,
        f: float | None = None,
        m11: float | None = None,
        m12: float | None = None,
        m21: float | None = None,
        m22: float | None = None,
        m41: float | None = None,
        m42: float | None = None,
        m13: float = 0,
        m14: float = 0,
        m23: float = 0,
        m24: float = 0,
        m31: float = 0,
        m32: float = 0,
        m33: float = 1,
        m34: float = 0,
        m43: float = 0,
        m44: float = 1,
        is2D: bool | None = None,
    ) -> DOMMatrix: ...

    def rotate(
        self, rotX: float = 0, rotY: float | None = None, rotZ: float | None = None
    ) -> DOMMatrix: ...

    def rotateAxisAngle(
        self, x: float = 0, y: float = 0, z: float = 0, angle: float = 0
    ) -> DOMMatrix: ...

    def rotateFromVector(self, x: float = 0, y: float = 0) -> DOMMatrix: ...

    def scale(
        self,
        scaleX: float = 1,
        scaleY: float | None = None,
        scaleZ: float = 1,
        originX: float = 0,
        originY: float = 0,
        originZ: float = 0,
    ) -> DOMMatrix: ...

    def scale3d(
        self, scale: float = 1, originX: float = 0, originY: float = 0, originZ: float = 0
    ) -> DOMMatrix: ...

    def scaleNonUniform(self, scaleX: float = 1, scaleY: float = 1) -> DOMMatrix: ...

    def skewX(self, sx: float = 0) -> DOMMatrix: ...

    def skewY(self, sy: float = 0) -> DOMMatrix: ...

    def toFloat32Array(self) -> Float32Array: ...

    def toFloat64Array(self) -> Float64Array: ...

    def toJSON(self) -> object: ...

    def transformPoint(
        self, *, x: float = 0, y: float = 0, z: float = 0, w: float = 1
    ) -> DOMPoint: ...

    def translate(self, tx: float = 0, ty: float = 0, tz: float = 0) -> DOMMatrix: ...


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

    def __init__(self, x: float = 0, y: float = 0, z: float = 0, w: float = 1):
        self.w: float = w
        self.x: float = x
        self.y: float = y
        self.z: float = z

    @staticmethod
    def fromPoint(
        *, x: float = 0, y: float = 0, z: float = 0, w: float = 1
    ) -> DOMPointReadOnly: ...

    def matrixTransform(
        self,
        *,
        a: float | None = None,
        b: float | None = None,
        c: float | None = None,
        d: float | None = None,
        e: float | None = None,
        f: float | None = None,
        m11: float | None = None,
        m12: float | None = None,
        m21: float | None = None,
        m22: float | None = None,
        m41: float | None = None,
        m42: float | None = None,
        m13: float = 0,
        m14: float = 0,
        m23: float = 0,
        m24: float = 0,
        m31: float = 0,
        m32: float = 0,
        m33: float = 1,
        m34: float = 0,
        m43: float = 0,
        m44: float = 1,
        is2D: bool | None = None,
    ) -> DOMPoint: ...

    def toJSON(self) -> object: ...


@js.native
class DOMQuad:
    """WebIDL source: @webref/idl/geometry.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMQuad

    Browser support: Chrome 61, Safari 11"""

    def __init__(
        self,
        p1: DOMPointInit | None = None,
        p2: DOMPointInit | None = None,
        p3: DOMPointInit | None = None,
        *,
        x: float = 0,
        y: float = 0,
        z: float = 0,
        w: float = 1,
    ):
        self.p1: DOMPoint = p1
        self.p2: DOMPoint = p2
        self.p3: DOMPoint = p3
        self.p4: DOMPoint = None

    @staticmethod
    def fromQuad(
        *,
        p1: DOMPointInit | None = None,
        p2: DOMPointInit | None = None,
        p3: DOMPointInit | None = None,
        p4: DOMPointInit | None = None,
    ) -> DOMQuad: ...

    @staticmethod
    def fromRect(other: DOMRectInit | None = None) -> DOMQuad: ...

    def getBounds(self) -> DOMRect: ...

    def toJSON(self) -> object: ...


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


@js.native
class DOMRectList:
    """WebIDL source: @webref/idl/geometry.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMRectList

    Browser support: Chrome 61, Safari 10.1"""

    def __init__(self):
        self.length: int = 0

    def item(self, index: int) -> DOMRect | None: ...


@js.dictionary
class DOMMatrixInit:
    """WebIDL source: @webref/idl/geometry.idl"""

    def __init__(
        self,
        a: float | None = None,
        b: float | None = None,
        c: float | None = None,
        d: float | None = None,
        e: float | None = None,
        f: float | None = None,
        is2D: bool | None = None,
        m11: float | None = None,
        m12: float | None = None,
        m13: float = 0,
        m14: float = 0,
        m21: float | None = None,
        m22: float | None = None,
        m23: float = 0,
        m24: float = 0,
        m31: float = 0,
        m32: float = 0,
        m33: float = 1,
        m34: float = 0,
        m41: float | None = None,
        m42: float | None = None,
        m43: float = 0,
        m44: float = 1,
    ):
        self.a = a
        self.b = b
        self.c = c
        self.d = d
        self.e = e
        self.f = f
        self.is2D = is2D
        self.m11 = m11
        self.m12 = m12
        self.m13 = m13
        self.m14 = m14
        self.m21 = m21
        self.m22 = m22
        self.m23 = m23
        self.m24 = m24
        self.m31 = m31
        self.m32 = m32
        self.m33 = m33
        self.m34 = m34
        self.m41 = m41
        self.m42 = m42
        self.m43 = m43
        self.m44 = m44


@js.native
class DOMMatrix(DOMMatrixReadOnly):
    """WebIDL source: @webref/idl/geometry.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMMatrix

    Browser support: Chrome 61, Safari 11"""

    def __init__(self, init: str | list[float] | None = None):
        super().__init__()
        self.a: float = 0.0
        self.b: float = 0.0
        self.c: float = 0.0
        self.d: float = 0.0
        self.e: float = 0.0
        self.f: float = 0.0
        self.m11: float = 0.0
        self.m12: float = 0.0
        self.m13: float = 0.0
        self.m14: float = 0.0
        self.m21: float = 0.0
        self.m22: float = 0.0
        self.m23: float = 0.0
        self.m24: float = 0.0
        self.m31: float = 0.0
        self.m32: float = 0.0
        self.m33: float = 0.0
        self.m34: float = 0.0
        self.m41: float = 0.0
        self.m42: float = 0.0
        self.m43: float = 0.0
        self.m44: float = 0.0

    @staticmethod
    def fromFloat32Array(array32: Float32Array) -> DOMMatrix: ...

    @staticmethod
    def fromFloat64Array(array64: Float64Array) -> DOMMatrix: ...

    @staticmethod
    def fromMatrix(
        *,
        a: float | None = None,
        b: float | None = None,
        c: float | None = None,
        d: float | None = None,
        e: float | None = None,
        f: float | None = None,
        m11: float | None = None,
        m12: float | None = None,
        m21: float | None = None,
        m22: float | None = None,
        m41: float | None = None,
        m42: float | None = None,
        m13: float = 0,
        m14: float = 0,
        m23: float = 0,
        m24: float = 0,
        m31: float = 0,
        m32: float = 0,
        m33: float = 1,
        m34: float = 0,
        m43: float = 0,
        m44: float = 1,
        is2D: bool | None = None,
    ) -> DOMMatrix: ...

    def invertSelf(self) -> DOMMatrix: ...

    def multiplySelf(
        self,
        *,
        a: float | None = None,
        b: float | None = None,
        c: float | None = None,
        d: float | None = None,
        e: float | None = None,
        f: float | None = None,
        m11: float | None = None,
        m12: float | None = None,
        m21: float | None = None,
        m22: float | None = None,
        m41: float | None = None,
        m42: float | None = None,
        m13: float = 0,
        m14: float = 0,
        m23: float = 0,
        m24: float = 0,
        m31: float = 0,
        m32: float = 0,
        m33: float = 1,
        m34: float = 0,
        m43: float = 0,
        m44: float = 1,
        is2D: bool | None = None,
    ) -> DOMMatrix: ...

    def preMultiplySelf(
        self,
        *,
        a: float | None = None,
        b: float | None = None,
        c: float | None = None,
        d: float | None = None,
        e: float | None = None,
        f: float | None = None,
        m11: float | None = None,
        m12: float | None = None,
        m21: float | None = None,
        m22: float | None = None,
        m41: float | None = None,
        m42: float | None = None,
        m13: float = 0,
        m14: float = 0,
        m23: float = 0,
        m24: float = 0,
        m31: float = 0,
        m32: float = 0,
        m33: float = 1,
        m34: float = 0,
        m43: float = 0,
        m44: float = 1,
        is2D: bool | None = None,
    ) -> DOMMatrix: ...

    def rotateAxisAngleSelf(
        self, x: float = 0, y: float = 0, z: float = 0, angle: float = 0
    ) -> DOMMatrix: ...

    def rotateFromVectorSelf(self, x: float = 0, y: float = 0) -> DOMMatrix: ...

    def rotateSelf(
        self, rotX: float = 0, rotY: float | None = None, rotZ: float | None = None
    ) -> DOMMatrix: ...

    def scale3dSelf(
        self, scale: float = 1, originX: float = 0, originY: float = 0, originZ: float = 0
    ) -> DOMMatrix: ...

    def scaleSelf(
        self,
        scaleX: float = 1,
        scaleY: float | None = None,
        scaleZ: float = 1,
        originX: float = 0,
        originY: float = 0,
        originZ: float = 0,
    ) -> DOMMatrix: ...

    def setMatrixValue(self, transformList: str) -> DOMMatrix: ...

    def skewXSelf(self, sx: float = 0) -> DOMMatrix: ...

    def skewYSelf(self, sy: float = 0) -> DOMMatrix: ...

    def translateSelf(self, tx: float = 0, ty: float = 0, tz: float = 0) -> DOMMatrix: ...


@js.native
class DOMPoint(DOMPointReadOnly):
    """WebIDL source: @webref/idl/geometry.idl

    MDN: https://developer.mozilla.org/docs/Web/API/DOMPoint

    Browser support: Chrome 61, Safari 10.1"""

    def __init__(self, x: float = 0, y: float = 0, z: float = 0, w: float = 1):
        super().__init__()
        self.w: float = w
        self.x: float = x
        self.y: float = y
        self.z: float = z

    @staticmethod
    def fromPoint(
        *, x: float = 0, y: float = 0, z: float = 0, w: float = 1
    ) -> DOMPoint: ...
