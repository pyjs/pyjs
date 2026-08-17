from collections.abc import Iterable
from typing import Final

from pyjs import JS, js

pi: Final[JS] = 3.141592653589793
tau: Final[JS] = 6.283185307179586
inf: Final[JS] = float("inf")


@js.inline("Math.sqrt({value})")
def sqrt(value: float) -> float: ...


@js.inline("Math.sin({value})")
def sin(value: float) -> float: ...


@js.inline("Math.cos({value})")
def cos(value: float) -> float: ...


@js.inline("Math.tan({value})")
def tan(value: float) -> float: ...


@js.inline("Math.asin({value})")
def asin(value: float) -> float: ...


@js.inline("Math.atan({value})")
def atan(value: float) -> float: ...


@js.inline("Math.atan2({y}, {x})")
def atan2(y: float, x: float) -> float: ...


@js.inline("({value} * Math.PI / 180)")
def radians(value: float) -> float: ...


@js.inline("Math.ceil({value})")
def ceil(value: float) -> int: ...


@js.inline("Number.isFinite({value})")
def isfinite(value: float) -> bool: ...


@js.inline("Math.hypot({_args_joined})")
def hypot(*coordinates: float) -> float: ...


@js
def dist(left: Iterable[float], right: Iterable[float]) -> float: ...


dist.source(
    """\
const leftValues = [...left];
const rightValues = [...right];
if (leftValues.length !== rightValues.length) {
    throw new Error('both points must have the same number of dimensions');
}
let total = 0;
for (let index = 0; index < leftValues.length; index++) {
    const difference = leftValues[index] - rightValues[index];
    total += difference * difference;
}
return Math.sqrt(total);
"""
)


@js
def isclose(
    left: float,
    right: float,
    *,
    rel_tol: float = 1e-09,
    abs_tol: float = 0.0,
) -> bool:
    if rel_tol < 0.0 or abs_tol < 0.0:
        raise ValueError("tolerances must be non-negative")
    if left == right:
        return True
    difference = abs(left - right)
    return difference <= max(
        rel_tol * max(abs(left), abs(right)),
        abs_tol,
    )
