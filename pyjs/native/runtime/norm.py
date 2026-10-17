"""Scaled, compensated Euclidean norm over call-local double buffers.

Uses error-free products/sums and a corrected square root, as in Ogita,
Rump and Oishi's accurate dot products and Borges' corrected hypot. Scaling
by powers of two prevents the squaring stage overflowing or underflowing.
No fast-math: reassociating the residual expressions destroys compensation.

Adapted from CPython 3.14 Modules/mathmodule.c (vector_norm), with Python
syntax, explicit pointer storage, bit-derived scaling, and in-place difference
formation. See ../PYTHON-LICENSE.txt for the PSF license and copyright notice.
"""

from functools import cache

from .algorithms import _positive_quotient, _runtime
from .float_math import INFINITY, absolute, bits, ieee_divide
from .integer_math import _float_bits, _shift_left
from .math_calls import fma, sqrt
from .pointers import Pointer, byte_offset, load_float, store_float


@_runtime
def norm(data: Pointer, length: int) -> float:
    maximum = 0.0
    found_nan = False
    index = 0
    while index < length:
        value = absolute(load_float(byte_offset(data, index * 8)))
        if value > maximum:
            maximum = value
        if value != value:
            found_nan = True
        index += 1
    # An infinite coordinate dominates NaN, including for empty/single inputs.
    if maximum == INFINITY:
        return maximum
    if found_nan:
        return INFINITY - INFINITY
    if maximum == 0.0 or length <= 1:
        return maximum

    factor = 1.0
    minimum_normal = 2.2250738585072014e-308
    if maximum < minimum_normal:
        # First bring subnormals into the normal range. The buffer is a private
        # snapshot, never an application's collection or borrowed host input.
        index = 0
        while index < length:
            slot = byte_offset(data, index * 8)
            store_float(slot, ieee_divide(load_float(slot), minimum_normal))
            index += 1
        maximum = ieee_divide(maximum, minimum_normal)
        factor = minimum_normal
    exponent = _positive_quotient(bits(maximum), 4503599627370496) - 1022
    scale = (_float_bits(_shift_left(1023 - exponent, 52)) if exponent <= 1022
             else _float_bits(_shift_left(1, 1074 - exponent)))
    total = 1.0
    products = 0.0
    additions = 0.0
    index = 0
    while index < length:
        value = load_float(byte_offset(data, index * 8)) * scale
        square = value * value
        products += fma(value, value, -square)
        combined = total + square
        additions += (total - combined) + square
        total = combined
        index += 1
    result = sqrt((total - 1.0) + (products + additions))
    # Correct the rounded square root using its residual against the accurate
    # square sum. total >= result**2, so the fast compensated sum is valid.
    square = -result * result
    products += fma(-result, result, -square)
    combined = total + square
    additions += (total - combined) + square
    residual = (combined - 1.0) + (products + additions)
    result += ieee_divide(residual, 2.0 * result)
    return ieee_divide(result, scale) * factor


@_runtime
def distance(left: Pointer, right: Pointer, length: int) -> float:
    index = 0
    while index < length:
        slot = byte_offset(left, index * 8)
        store_float(slot, load_float(slot) - load_float(byte_offset(right, index * 8)))
        index += 1
    return norm(left, length)


@cache
def compiled_runtime():
    from .compiler import compile_runtime

    return compile_runtime({"pyjs.math.norm": norm, "pyjs.math.distance": distance})
