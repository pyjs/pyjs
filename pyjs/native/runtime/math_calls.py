"""Scalar LLVM/libm leaves; public validation lives in native.math."""

import math

from pyjs import llvm
from pyjs.decorators import native_operation

from . import math_algorithms


@llvm.inline("call i64 @pyjs.math.gcd(i64 {left}, i64 {right})")
def gcd(left: int, right: int) -> int:
    return math_algorithms.gcd(left, right)


@llvm.inline("call i64 @pyjs.math.lcm(i64 {left}, i64 {right})")
def lcm(left: int, right: int) -> int:
    return math_algorithms.lcm(left, right)


@llvm.inline("call i64 @pyjs.math.combination(i64 {n}, i64 {k}, i1 {permutation})")
def combination(n: int, k: int, permutation: bool) -> int:
    return math_algorithms.combination(n, k, permutation)


@llvm.inline("call i64 @pyjs.math.isqrt(i64 {value})")
def isqrt(value: int) -> int:
    return math_algorithms.isqrt(value)


@llvm.inline("call double @pyjs.math.nextafter(double {x}, double {y}, i64 {steps})")
def nextafter_steps(x: float, y: float, steps: int) -> float:
    return math_algorithms.nextafter(x, y, steps)


@llvm.inline("call double @llvm.sqrt.f64(double {value})")
def sqrt(value: float) -> float:
    return math.sqrt(value)


@llvm.inline("call double @llvm.sin.f64(double {value})")
def sin(value: float) -> float:
    return math.sin(value)


@llvm.inline("call double @llvm.cos.f64(double {value})")
def cos(value: float) -> float:
    return math.cos(value)


@llvm.inline("call double @tan(double {value})")
def tan(value: float) -> float:
    return math.tan(value)


@llvm.inline("call double @asin(double {value})")
def asin(value: float) -> float:
    return math.asin(value)


@llvm.inline("call double @acos(double {value})")
def acos(value: float) -> float:
    return math.acos(value)


@llvm.inline("call double @acosh(double {value})")
def acosh(value: float) -> float:
    return math.acosh(value)


@llvm.inline("call double @atanh(double {value})")
def atanh(value: float) -> float:
    return math.atanh(value)


@llvm.inline("call double @llvm.log.f64(double {value})")
def log(value: float) -> float:
    return math.log(value)


@llvm.inline("call double @llvm.log2.f64(double {value})")
def log2(value: float) -> float:
    return math.log2(value)


@llvm.inline("call double @llvm.log10.f64(double {value})")
def log10(value: float) -> float:
    return math.log10(value)


@llvm.inline("call double @log1p(double {value})")
def log1p(value: float) -> float:
    return math.log1p(value)


@llvm.inline("call double @asinh(double {value})")
def asinh(value: float) -> float:
    return math.asinh(value)


@llvm.inline("call double @atan(double {value})")
def atan(value: float) -> float:
    return math.atan(value)


@llvm.inline("call double @cbrt(double {value})")
def cbrt(value: float) -> float:
    return math.cbrt(value)


@llvm.inline("call double @erf(double {value})")
def erf(value: float) -> float:
    return math.erf(value)


@llvm.inline("call double @erfc(double {value})")
def erfc(value: float) -> float:
    return math.erfc(value)


@llvm.inline("call double @tanh(double {value})")
def tanh(value: float) -> float:
    return math.tanh(value)


@llvm.inline("call double @llvm.exp.f64(double {value})")
def exp(value: float) -> float:
    return math.exp(value)


@llvm.inline("call double @llvm.exp2.f64(double {value})")
def exp2(value: float) -> float:
    return math.exp2(value)


@llvm.inline("call double @expm1(double {value})")
def expm1(value: float) -> float:
    return math.expm1(value)


@llvm.inline("call double @cosh(double {value})")
def cosh(value: float) -> float:
    return math.cosh(value)


@llvm.inline("call double @sinh(double {value})")
def sinh(value: float) -> float:
    return math.sinh(value)


@llvm.inline("call double @llvm.floor.f64(double {value})")
def floor(value: float) -> float:
    return float(math.floor(value)) if math.isfinite(value) else value


@llvm.inline("call double @llvm.ceil.f64(double {value})")
def ceil(value: float) -> float:
    return float(math.ceil(value)) if math.isfinite(value) else value


@llvm.inline("call double @llvm.trunc.f64(double {value})")
def trunc(value: float) -> float:
    return float(math.trunc(value)) if math.isfinite(value) else value


@llvm.inline("call double @tgamma(double {value})")
def gamma(value: float) -> float:
    return math.gamma(value)


@llvm.inline("call double @lgamma(double {value})")
def lgamma(value: float) -> float:
    return math.lgamma(value)


@llvm.inline("call double @atan2(double {y}, double {x})")
def atan2(y: float, x: float) -> float:
    return math.atan2(y, x)


@llvm.inline("call double @fmod(double {left}, double {right})")
def fmod(left: float, right: float) -> float:
    return math.fmod(left, right)


@llvm.inline("call double @remainder(double {left}, double {right})")
def remainder(left: float, right: float) -> float:
    return math.remainder(left, right)


@llvm.inline("call double @pow(double {left}, double {right})")
def pow(left: float, right: float) -> float:
    return math.pow(left, right)


@llvm.inline("call double @nextafter(double {left}, double {right})")
def nextafter(left: float, right: float) -> float:
    return math.nextafter(left, right)


@llvm.inline("call double @fma(double {x}, double {y}, double {z})")
def fma(x: float, y: float, z: float) -> float:
    return math.fma(x, y, z)


@native_operation("math.ldexp")
def ldexp(value: float, exponent: int) -> float:
    # libm takes a C int; public validation clamps the wide inline operand.
    return math.ldexp(value, exponent)


@native_operation("math.frexp")
def frexp(value: float) -> tuple[float, int]:
    return math.frexp(value)


@native_operation("math.modf")
def modf(value: float) -> tuple[float, float]:
    return math.modf(value)
