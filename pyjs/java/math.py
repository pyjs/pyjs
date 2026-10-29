"""Standard-library math operations backed by Java's primitive helpers."""

from pyjs import jvm


@jvm.native("java/lang/Double", name="isFinite")
def isfinite(value: float, /) -> bool: ...


@jvm.native("java/lang/Math", name="sqrt")
def _sqrt(value: float, /) -> float: ...


def sqrt(value: float, /) -> float:
    if value < 0.0:
        raise ValueError("math domain error")
    return _sqrt(value)
