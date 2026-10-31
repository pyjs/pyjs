from collections.abc import Iterable
from typing import Final

from pyjs import JS, js, wgsl
from pyjs.decorators import integer_index_parameters
from pyjs.python import dynamic_iterable_source

pi: Final[JS] = 3.141592653589793
tau: Final[JS] = 6.283185307179586
inf: Final[JS] = float("inf")


@wgsl.native
@js.inline("Math.pow({base}, {exponent})")
def pow(base: float, exponent: float) -> float: ...


@wgsl.native
@js.inline("Math.sqrt({value})")
def sqrt(value: float) -> float: ...


@wgsl.native
@js.inline("Math.sin({value})")
def sin(value: float) -> float: ...


sin.value.source("return Math.sin(value);")


@wgsl.native
@js.inline("Math.cos({value})")
def cos(value: float) -> float: ...


cos.value.source("return Math.cos(value);")


@wgsl.native
@js.inline("Math.tan({value})")
def tan(value: float) -> float: ...


@wgsl.native
@js.inline("Math.asin({value})")
def asin(value: float) -> float: ...


@wgsl.native
@js.inline("Math.acos({value})")
def acos(value: float) -> float: ...


@wgsl.native
@js.inline("Math.atan({value})")
def atan(value: float) -> float: ...


@wgsl.native
@js.inline("Math.atan2({y}, {x})")
def atan2(y: float, x: float) -> float: ...


@js.inline("(({value}) * (Math.PI / 180))")
def radians(value: float) -> float: ...


@integer_index_parameters("value")
@wgsl.native
@js.inline("Math.ceil({value})")
def ceil(value: float) -> int: ...


@integer_index_parameters("value")
@wgsl.native
@js.inline("Math.floor({value})")
def floor(value: float) -> int: ...


@wgsl.native
@js.inline("Math.exp({value})")
def exp(value: float) -> float: ...


@wgsl.native
@js.inline("Math.log({value})")
def log(value: float) -> float: ...


@wgsl.inline("({x} % {y})")
@js.inline("(({x}) % ({y}))")
def fmod(x: float, y: float) -> float: ...


@js.inline("Number.isFinite({value})")
def isfinite(value: float) -> bool: ...


@js.inline("Math.hypot({_args_joined})")
def hypot(*coordinates: float) -> float: ...


@js
def dist(left: Iterable[float], right: Iterable[float]) -> float: ...


dist.source(
    f"const leftValues = [...{dynamic_iterable_source('left')}];\n"
    f"const rightValues = [...{dynamic_iterable_source('right')}];\n"
    """\
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
