"""Standard-library numeric predicates backed by Java's primitive helpers."""

from pyjs import jvm


@jvm.native("java/lang/Double", name="isFinite")
def isfinite(value: float, /) -> bool: ...
