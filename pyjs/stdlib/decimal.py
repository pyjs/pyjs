"""Exact decimal values for Python and JavaScript application code."""

from decimal import Decimal as _PythonDecimal
from decimal import InvalidOperation
from typing import Self

from pyjs import js, nojs


@js
def _decimal_add(left: Decimal, right: Decimal) -> Decimal: ...


_decimal_add.source(
    """
    const exponent = Math.min(left._exponent, right._exponent);
    const leftValue = left._coefficient
        * 10n ** BigInt(left._exponent - exponent);
    const rightValue = right._coefficient
        * 10n ** BigInt(right._exponent - exponent);
    const result = Object.create(left.constructor.prototype);
    result._coefficient = leftValue + rightValue;
    result._exponent = exponent;
    return result;
    """
)


@js
def _decimal_subtract(left: Decimal, right: Decimal) -> Decimal: ...


_decimal_subtract.source(
    """
    const exponent = Math.min(left._exponent, right._exponent);
    const leftValue = left._coefficient
        * 10n ** BigInt(left._exponent - exponent);
    const rightValue = right._coefficient
        * 10n ** BigInt(right._exponent - exponent);
    const result = Object.create(left.constructor.prototype);
    result._coefficient = leftValue - rightValue;
    result._exponent = exponent;
    return result;
    """
)


@js
def _decimal_multiply(left: Decimal, right: Decimal) -> Decimal: ...


_decimal_multiply.source(
    """
    const result = Object.create(left.constructor.prototype);
    result._coefficient = left._coefficient * right._coefficient;
    result._exponent = left._exponent + right._exponent;
    return result;
    """
)


@js
def _decimal_negate(value: Decimal) -> Decimal: ...


_decimal_negate.source(
    """
    const result = Object.create(value.constructor.prototype);
    result._coefficient = -value._coefficient;
    result._exponent = value._exponent;
    return result;
    """
)


@js
def _decimal_string(value: Decimal) -> str: ...


_decimal_string.source(
    """
    const negative = value._coefficient < 0n;
    let digits = (negative ? -value._coefficient : value._coefficient).toString();
    if (value._exponent >= 0) {
        digits += '0'.repeat(value._exponent);
    } else {
        const point = digits.length + value._exponent;
        digits = point > 0
            ? `${digits.slice(0, point)}.${digits.slice(point)}`
            : `0.${'0'.repeat(-point)}${digits}`;
    }
    return `${negative ? '-' : ''}${digits}`;
    """
)


@js
def _decimal_compare(left: Decimal, right: Decimal) -> int: ...


_decimal_compare.source(
    """
    const exponent = Math.min(left._exponent, right._exponent);
    const leftValue = left._coefficient
        * 10n ** BigInt(left._exponent - exponent);
    const rightValue = right._coefficient
        * 10n ** BigInt(right._exponent - exponent);
    return leftValue < rightValue ? -1 : leftValue > rightValue ? 1 : 0;
    """
)


@js
def _is_decimal(value: object) -> bool:
    return isinstance(value, Decimal)


_is_decimal.source("return value instanceof Decimal;")


@js
class Decimal:
    """A finite exact decimal with the familiar ``decimal.Decimal`` subset.

    Construction from strings and integers, exact addition, subtraction,
    multiplication, comparison, and string conversion are supported by the
    JavaScript backend. Division and context-dependent decimal operations are
    intentionally deferred until PyJS can preserve their Python semantics.
    """

    _value: object
    _coefficient: object
    _exponent: int

    @classmethod
    @nojs
    def _result(cls, value: object) -> Self:
        if value.is_zero():
            value = value.copy_abs()
        return cls(value)

    @js
    def __init__(self, value: str | int | Self = "0") -> None:
        if isinstance(value, Decimal):
            value = value._value
        if isinstance(value, bool) or not isinstance(
            value,
            (str, int, _PythonDecimal),
        ):
            raise TypeError("Decimal construction requires a string or int")
        if isinstance(value, str) and "_" in value:
            raise TypeError(f"invalid Decimal value: {value}")
        if isinstance(value, str) and "e" in value.lower():
            raise ValueError("Decimal exponent notation is not supported")
        try:
            self._value = _PythonDecimal(value)
        except InvalidOperation as error:
            raise TypeError(f"invalid Decimal value: {value}") from error
        if not self._value.is_finite():
            raise ValueError("non-finite Decimal values are not supported")
        if self._value.is_zero() and self._value.is_signed():
            raise ValueError("negative zero Decimal values are not supported")

    @js.inline(call=_decimal_add)
    def __add__(self, other: Self) -> Self:
        return type(self)._result(self._value + other._value)

    @js.inline(call=_decimal_subtract)
    def __sub__(self, other: Self) -> Self:
        return type(self)._result(self._value - other._value)

    @js.inline(call=_decimal_multiply)
    def __mul__(self, other: Self) -> Self:
        return type(self)._result(self._value * other._value)

    @js.inline(call=_decimal_negate)
    def __neg__(self) -> Self:
        return type(self)._result(-self._value)

    @js.inline("({self}._coefficient !== 0n)")
    def __bool__(self) -> bool:
        return bool(self._value)

    @js.inline(
        "((left,right)=>{is_decimal}(right) && "
        "{compare}(left,right)===0)({self},{other})",
        is_decimal=_is_decimal,
        compare=_decimal_compare,
    )
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Decimal):
            return False
        return self._value == other._value

    @js.inline(
        "((left,right)=>!{is_decimal}(right) || "
        "{compare}(left,right)!==0)({self},{other})",
        is_decimal=_is_decimal,
        compare=_decimal_compare,
    )
    def __ne__(self, other: object) -> bool:
        if not isinstance(other, Decimal):
            return True
        return self._value != other._value

    @js.inline("{compare}({self},{other})<0", compare=_decimal_compare)
    def __lt__(self, other: Self) -> bool:
        return self._value < other._value

    @js.inline("{compare}({self},{other})<=0", compare=_decimal_compare)
    def __le__(self, other: Self) -> bool:
        return self._value <= other._value

    @js.inline("{compare}({self},{other})>0", compare=_decimal_compare)
    def __gt__(self, other: Self) -> bool:
        return self._value > other._value

    @js.inline("{compare}({self},{other})>=0", compare=_decimal_compare)
    def __ge__(self, other: Self) -> bool:
        return self._value >= other._value

    @js
    def __str__(self) -> str:
        return str(self._value)

    @__str__.client
    def __str__(self) -> str:
        return _decimal_string(self)


Decimal.__init__.source(
    """
    if (value instanceof Decimal) {
        this._coefficient = value._coefficient;
        this._exponent = value._exponent;
        return;
    }
    if (typeof value === 'number') {
        if (!Number.isInteger(value)) {
            throw new TypeError('Decimal construction requires a string or int');
        }
        value = String(value);
    } else if (typeof value === 'bigint') {
        value = value.toString();
    }
    if (typeof value !== 'string') {
        throw new TypeError('Decimal construction requires a string or int');
    }
    const text = value.trim();
    if (/[eE]/.test(text)) {
        throw new RangeError('Decimal exponent notation is not supported');
    }
    if (/^[+-]?(?:s?NaN\\d*|Infinity)$/i.test(text)) {
        throw new RangeError('non-finite Decimal values are not supported');
    }
    const match = /^([+-]?)(?:(\\d+)(?:\\.(\\d*))?|\\.(\\d+))$/.exec(text);
    if (match === null) {
        throw new TypeError(`invalid Decimal value: ${value}`);
    }
    const whole = match[2] || '0';
    const fraction = match[3] || match[4] || '';
    this._coefficient = BigInt(`${match[1]}${whole}${fraction}`);
    if (this._coefficient === 0n && match[1] === '-') {
        throw new RangeError('negative zero Decimal values are not supported');
    }
    this._exponent = -fraction.length;
    """
)


__all__ = ["Decimal"]
