"""Native-compatible declarations for Python date and time values."""

from typing import Literal, overload

from .runtime import wide
from .runtime.float_math import bits
from .runtime.integer_math import _wide_bit_length, wide_true_divide
from .runtime.wide import WideInt

_MICROSECONDS_PER_SECOND = 1_000_000
_SECONDS_PER_DAY = 86_400
_MICROSECONDS_PER_DAY = _SECONDS_PER_DAY * _MICROSECONDS_PER_SECOND


def _duration_total(days: int, seconds: int, microseconds: int,
                    milliseconds: int, minutes: int, hours: int, weeks: int) -> WideInt:
    # Each argument fits i64, but a valid duration's microsecond total need not.
    # i128 also allows large opposite-signed arguments to cancel before bounds
    # checking, rather than rejecting them individually or wrapping silently.
    whole_days = wide.add(wide.multiply(wide.widen(weeks), wide.widen(7)), wide.widen(days))
    whole_seconds = wide.add(wide.multiply(whole_days, wide.widen(_SECONDS_PER_DAY)), wide.widen(seconds))
    whole_seconds = wide.add(whole_seconds, wide.multiply(wide.widen(hours), wide.widen(3600)))
    whole_seconds = wide.add(whole_seconds, wide.multiply(wide.widen(minutes), wide.widen(60)))
    total = wide.multiply(whole_seconds, wide.widen(_MICROSECONDS_PER_SECOND))
    total = wide.add(total, wide.multiply(wide.widen(milliseconds), wide.widen(1000)))
    return wide.add(total, wide.widen(microseconds))


def _duration_parts(total: WideInt) -> tuple[int, int, int]:
    negative = wide.less(total, wide.widen(0))
    magnitude = wide.subtract(wide.widen(0), total) if negative else total
    divisor = wide.widen(_MICROSECONDS_PER_DAY)
    days = wide.quotient(magnitude, divisor)
    rest = wide.narrow(wide.remainder(magnitude, divisor))
    if negative:
        days = wide.subtract(wide.widen(0), days)
        if rest:
            days = wide.subtract(days, wide.widen(1))
            rest = _MICROSECONDS_PER_DAY - rest
    if wide.less(days, wide.widen(-999999999)) or wide.less(wide.widen(999999999), days):
        raise OverflowError("timedelta days must have magnitude <= 999999999")
    return wide.narrow(days), rest // _MICROSECONDS_PER_SECOND, rest % _MICROSECONDS_PER_SECOND

# A literal sentinel keeps omitted replace fields distinct from None without
# requiring a module-owned native object.
def _replacement(
    value: int | Literal["__pyjs_datetime_unspecified"],
    current: int,
) -> int:
    if isinstance(value, str):
        return current
    return int(value)


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _days_before_month(year: int, month: int) -> int:
    result = 0
    if month > 1:
        result += 31
    if month > 2:
        result += 28 + int(_is_leap(year))
    if month > 3:
        result += 31
    if month > 4:
        result += 30
    if month > 5:
        result += 31
    if month > 6:
        result += 30
    if month > 7:
        result += 31
    if month > 8:
        result += 31
    if month > 9:
        result += 30
    if month > 10:
        result += 31
    if month > 11:
        result += 30
    return result


def _days_in_month(year: int, month: int) -> int:
    if month == 2:
        return 29 if _is_leap(year) else 28
    if month in {4, 6, 9, 11}:
        return 30
    return 31


def _validate_date(year: int, month: int, day: int) -> None:
    if year < 1 or year > 9999:
        raise ValueError(f"year must be in 1..9999, not {year}")
    if month < 1 or month > 12:
        raise ValueError(f"month must be in 1..12, not {month}")
    maximum_day = _days_in_month(year, month)
    if day < 1 or day > maximum_day:
        raise ValueError(
            f"day {day} must be in range 1..{maximum_day} for month "
            f"{month} in year {year}"
        )


def _ordinal(year: int, month: int, day: int) -> int:
    previous_year = year - 1
    return (
        previous_year * 365
        + previous_year // 4
        - previous_year // 100
        + previous_year // 400
        + _days_before_month(year, month)
        + day
    )


def _date_from_ordinal(value: int) -> tuple[int, int, int]:
    if value < 1 or value > 3652059:
        raise OverflowError("date value out of range")
    low = 1
    high = 10000
    while low + 1 < high:
        middle = (low + high) // 2
        if _ordinal(middle, 1, 1) <= value:
            low = middle
        else:
            high = middle
    year = low
    day_of_year = value - _ordinal(year, 1, 1) + 1
    month = 1
    while day_of_year > _days_in_month(year, month):
        day_of_year -= _days_in_month(year, month)
        month += 1
    return year, month, day_of_year


def _decimal(value: str) -> int:
    if not value:
        raise ValueError("invalid ISO date or time")
    result = 0
    for character in value:
        codepoint = ord(character)
        if codepoint < 48 or codepoint > 57:
            raise ValueError("invalid ISO date or time")
        result = result * 10 + codepoint - 48
    return result


def _calendar_date(value: str) -> tuple[int, int, int]:
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        return (
            _decimal(value[:4]),
            _decimal(value[5:7]),
            _decimal(value[8:]),
        )
    if len(value) == 8:
        return (
            _decimal(value[:4]),
            _decimal(value[4:6]),
            _decimal(value[6:]),
        )
    raise ValueError("invalid ISO date or time")


def _clock_time(value: str) -> tuple[int, int, int, int]:
    fraction = ""
    has_fraction = False
    separator = value.find(".")
    comma = value.find(",")
    if separator < 0 or comma >= 0 and comma < separator:
        separator = comma
    if separator >= 0:
        has_fraction = True
        fraction = value[separator + 1 :]
        value = value[:separator]
    if has_fraction and not fraction:
        raise ValueError("invalid ISO date or time")
    if ":" in value:
        if not (
            len(value) == 5
            and value[2] == ":"
            or len(value) == 8
            and value[2] == ":"
            and value[5] == ":"
        ):
            raise ValueError("invalid ISO date or time")
    elif len(value) not in {2, 4, 6}:
        raise ValueError("invalid ISO date or time")
    compact = value.replace(":", "")
    if has_fraction and len(compact) != 6:
        raise ValueError("invalid ISO date or time")
    hour = _decimal(compact[:2])
    minute = _decimal(compact[2:4]) if len(compact) >= 4 else 0
    second = _decimal(compact[4:6]) if len(compact) == 6 else 0
    microsecond = 0
    if fraction:
        # Sub-microsecond digits are truncated, not ignored by validation.
        # Do not parse the entire fraction as an integer: its length is unbounded.
        for character in fraction:
            if ord(character) < 48 or ord(character) > 57:
                raise ValueError("invalid ISO date or time")
        digits = fraction[:6]
        microsecond = _decimal(digits) * 10 ** (6 - len(digits))
    return hour, minute, second, microsecond


def _datetime_from_microseconds(
    value: int,
) -> tuple[int, int, int, int, int, int, int]:
    ordinal = value // _MICROSECONDS_PER_DAY
    remainder = value % _MICROSECONDS_PER_DAY
    year, month, day = _date_from_ordinal(ordinal)
    hour = remainder // (3600 * _MICROSECONDS_PER_SECOND)
    remainder %= 3600 * _MICROSECONDS_PER_SECOND
    minute = remainder // (60 * _MICROSECONDS_PER_SECOND)
    remainder %= 60 * _MICROSECONDS_PER_SECOND
    second = remainder // _MICROSECONDS_PER_SECOND
    microsecond = remainder % _MICROSECONDS_PER_SECOND
    return year, month, day, hour, minute, second, microsecond


def _wide_divmod(numerator: WideInt, denominator: WideInt) -> tuple[WideInt, WideInt]:
    zero = wide.widen(0)
    if wide.equal(denominator, zero):
        raise ZeroDivisionError("integer division or modulo by zero")
    negative = wide.less(numerator, zero) != wide.less(denominator, zero)
    left = wide.subtract(zero, numerator) if wide.less(numerator, zero) else numerator
    right = wide.subtract(zero, denominator) if wide.less(denominator, zero) else denominator
    quotient = wide.quotient(left, right)
    remainder = wide.remainder(left, right)
    if negative:
        quotient = wide.subtract(zero, quotient)
        if not wide.equal(remainder, zero):
            quotient = wide.subtract(quotient, wide.widen(1))
            remainder = wide.subtract(right, remainder)
    if wide.less(denominator, zero):
        remainder = wide.subtract(zero, remainder)
    return quotient, remainder


def _divide_and_round(numerator: WideInt, denominator: WideInt) -> WideInt:
    quotient, remainder = _wide_divmod(numerator, denominator)
    zero = wide.widen(0)
    if wide.less(denominator, zero):
        denominator = wide.subtract(zero, denominator)
        remainder = wide.subtract(zero, remainder)
    doubled = wide.multiply(remainder, wide.widen(2))
    if wide.less(denominator, doubled) or (wide.equal(doubled, denominator) and wide.narrow(quotient) & 1):
        quotient = wide.add(quotient, wide.widen(1))
    return quotient


def _duration_from_wide(total: WideInt) -> timedelta:
    days, seconds, microseconds = _duration_parts(total)
    return timedelta(days=days, seconds=seconds, microseconds=microseconds)


def _checked_integer(value: WideInt) -> int:
    if wide.less(value, wide.widen(-9223372036854775808)) or wide.less(wide.widen(9223372036854775807), value):
        raise OverflowError("duration result exceeds native signed i64 range")
    return wide.narrow(value)


def _duration_ratio(numerator: WideInt, denominator: WideInt) -> float:
    if wide.equal(denominator, wide.widen(0)):
        raise ZeroDivisionError("division by zero")
    return wide_true_divide(numerator, denominator)


def _duration_float(total: WideInt, factor: float, divide: bool) -> timedelta:
    encoded = bits(factor)
    exponent = (encoded >> 52) & 2047
    mantissa = encoded & 4503599627370495
    if exponent == 2047:
        if mantissa:
            raise ValueError("cannot convert NaN to integer ratio")
        raise OverflowError("cannot convert Infinity to integer ratio")
    shift = exponent - 1075 if exponent else -1074
    if exponent:
        mantissa |= 4503599627370496
    if divide and mantissa == 0:
        raise ZeroDivisionError("integer division or modulo by zero")
    zero = wide.widen(0)
    negative = wide.less(total, zero) != (encoded < 0)
    numerator = wide.subtract(zero, total) if wide.less(total, zero) else total
    denominator = wide.widen(mantissa) if divide else wide.widen(1)
    if divide:
        shift = -shift
    else:
        numerator = wide.multiply(numerator, wide.widen(mantissa))
    if wide.equal(numerator, zero):
        return timedelta()
    # A finite binary64 is an exact mantissa times a power of two. Bound
    # shifts before applying them: the only possible out-of-range outcomes
    # are a duration overflow or rounding to zero, not wrapped i128 arithmetic.
    if shift >= 0:
        if _wide_bit_length(numerator) + shift > _wide_bit_length(denominator) + 68:
            raise OverflowError("timedelta days must have magnitude <= 999999999")
        numerator = wide.shift_left(numerator, wide.widen(shift))
    else:
        if _wide_bit_length(denominator) - shift > _wide_bit_length(numerator) + 1:
            return timedelta()
        denominator = wide.shift_left(denominator, wide.widen(-shift))
    result = _divide_and_round(numerator, denominator)
    return _duration_from_wide(wide.subtract(zero, result) if negative else result)


class timedelta:
    def __init__(
        self,
        days: int = 0,
        seconds: int = 0,
        microseconds: int = 0,
        milliseconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        weeks: int = 0,
    ) -> None:
        days, seconds, microseconds = _duration_parts(
            _duration_total(days, seconds, microseconds, milliseconds, minutes, hours, weeks))
        self._days = days
        self._seconds = seconds
        self._microseconds = microseconds

    @property
    def days(self) -> int:
        return self._days

    @property
    def seconds(self) -> int:
        return self._seconds

    @property
    def microseconds(self) -> int:
        return self._microseconds

    def total_seconds(self) -> float:
        return _duration_ratio(self._wide_microseconds(), wide.widen(_MICROSECONDS_PER_SECOND))

    def _wide_microseconds(self) -> WideInt:
        return _duration_total(self.days, self.seconds, self.microseconds, 0, 0, 0, 0)

    def __bool__(self) -> bool:
        return self.days != 0 or self.seconds != 0 or self.microseconds != 0

    def __eq__(self, other: timedelta) -> bool:
        return (
            self.days == other.days
            and self.seconds == other.seconds
            and self.microseconds == other.microseconds
        )

    def __hash__(self) -> int:
        return hash((self.days, self.seconds, self.microseconds))

    def __lt__(self, other: timedelta) -> bool:
        if self.days != other.days:
            return self.days < other.days
        if self.seconds != other.seconds:
            return self.seconds < other.seconds
        return self.microseconds < other.microseconds

    def __le__(self, other: timedelta) -> bool:
        return self == other or self < other

    def __gt__(self, other: timedelta) -> bool:
        return not self <= other

    def __ge__(self, other: timedelta) -> bool:
        return not self < other

    def __add__(self, other: timedelta) -> timedelta:
        return timedelta(
            days=self.days + other.days,
            seconds=self.seconds + other.seconds,
            microseconds=self.microseconds + other.microseconds,
        )

    def __sub__(self, other: timedelta) -> timedelta:
        return timedelta(
            days=self.days - other.days,
            seconds=self.seconds - other.seconds,
            microseconds=self.microseconds - other.microseconds,
        )

    def __pos__(self) -> timedelta:
        return timedelta(
            days=self.days,
            seconds=self.seconds,
            microseconds=self.microseconds,
        )

    def __neg__(self) -> timedelta:
        return timedelta(
            days=-self.days,
            seconds=-self.seconds,
            microseconds=-self.microseconds,
        )

    def __abs__(self) -> timedelta:
        return -self if self.days < 0 else +self

    def __mul__(self, other: int | float) -> timedelta:
        if isinstance(other, int):
            total = self._wide_microseconds()
            factor = wide.widen(int(other))
            zero = wide.widen(0)
            absolute = wide.subtract(zero, total) if wide.less(total, zero) else total
            magnitude = wide.subtract(zero, factor) if wide.less(factor, zero) else factor
            limit = wide.multiply(wide.widen(1000000000), wide.widen(_MICROSECONDS_PER_DAY))
            # A product of a valid duration and i64 can exceed even i128.
            # Prove a duration-sized bound before performing multiplication.
            if not wide.equal(magnitude, zero) and wide.less(wide.quotient(limit, magnitude), absolute):
                raise OverflowError("timedelta days must have magnitude <= 999999999")
            return _duration_from_wide(wide.multiply(total, factor))
        return _duration_float(self._wide_microseconds(), other, False)

    def __rmul__(self, other: int | float) -> timedelta:
        return self * other

    @overload
    def __truediv__(self, other: int | float) -> timedelta: ...

    @overload
    def __truediv__(self, other: timedelta) -> float: ...

    def __truediv__(
        self,
        other: int | float | timedelta,
    ) -> timedelta | float:
        if isinstance(other, timedelta):
            return _duration_ratio(self._wide_microseconds(), other._wide_microseconds())
        if isinstance(other, float):
            return _duration_float(self._wide_microseconds(), other, True)
        return _duration_from_wide(_divide_and_round(self._wide_microseconds(), wide.widen(int(other))))

    @overload
    def __floordiv__(self, other: int) -> timedelta: ...

    @overload
    def __floordiv__(self, other: timedelta) -> int: ...

    def __floordiv__(self, other: int | timedelta) -> timedelta | int:
        if isinstance(other, timedelta):
            quotient, remainder = _wide_divmod(self._wide_microseconds(), other._wide_microseconds())
            return _checked_integer(quotient)
        quotient, remainder = _wide_divmod(self._wide_microseconds(), wide.widen(int(other)))
        return _duration_from_wide(quotient)

    def __mod__(self, other: timedelta) -> timedelta:
        quotient, remainder = _wide_divmod(self._wide_microseconds(), other._wide_microseconds())
        return _duration_from_wide(remainder)

    def __divmod__(self, other: timedelta) -> tuple[int, timedelta]:
        quotient = self // other
        return int(quotient), self % other

    def __str__(self) -> str:
        hours = self.seconds // 3600
        minutes = self.seconds // 60 % 60
        seconds = self.seconds % 60
        result = (
            str(hours)
            + ":"
            + str(minutes).zfill(2)
            + ":"
            + str(seconds).zfill(2)
        )
        if self.microseconds:
            result += "." + str(self.microseconds).zfill(6)
        if self.days:
            unit = " day, " if self.days == 1 or self.days == -1 else " days, "
            result = str(self.days) + unit + result
        return result


class date:
    def __init__(self, year: int, month: int, day: int) -> None:
        _validate_date(year, month, day)
        self._year = year
        self._month = month
        self._day = day

    @property
    def year(self) -> int:
        return self._year

    @property
    def month(self) -> int:
        return self._month

    @property
    def day(self) -> int:
        return self._day

    def isoformat(self) -> str:
        return (
            str(self.year).zfill(4)
            + "-"
            + str(self.month).zfill(2)
            + "-"
            + str(self.day).zfill(2)
        )

    def __str__(self) -> str:
        return self.isoformat()

    def toordinal(self) -> int:
        return _ordinal(self.year, self.month, self.day)

    @classmethod
    def fromordinal(cls, ordinal: int) -> date:
        if ordinal < 1 or ordinal > 3652059:
            raise ValueError("ordinal must be >= 1")
        year, month, day = _date_from_ordinal(ordinal)
        return cls(year, month, day)

    @classmethod
    def fromisoformat(cls, value: str) -> date:
        try:
            year, month, day = _calendar_date(value)
        except ValueError:
            raise ValueError(  # noqa: B904
                f"Invalid isoformat string: {value!r}"
            )
        return cls(year, month, day)

    def weekday(self) -> int:
        return (self.toordinal() + 6) % 7

    def isoweekday(self) -> int:
        return self.weekday() + 1

    def isocalendar(self) -> tuple[int, int, int]:
        iso_weekday = self.isoweekday()
        thursday = self.toordinal() + 4 - iso_weekday
        iso_year, _month, _day = _date_from_ordinal(thursday)
        first_thursday = _ordinal(iso_year, 1, 4)
        first_thursday += 4 - ((first_thursday + 6) % 7 + 1)
        return iso_year, (thursday - first_thursday) // 7 + 1, iso_weekday

    def __eq__(self, other: date) -> bool:
        return (
            self.year == other.year
            and self.month == other.month
            and self.day == other.day
        )

    def __hash__(self) -> int:
        return hash(self.toordinal())

    def __lt__(self, other: date) -> bool:
        return self.toordinal() < other.toordinal()

    def __le__(self, other: date) -> bool:
        return self.toordinal() <= other.toordinal()

    def __gt__(self, other: date) -> bool:
        return self.toordinal() > other.toordinal()

    def __ge__(self, other: date) -> bool:
        return self.toordinal() >= other.toordinal()

    def __add__(self, other: timedelta) -> date:
        year, month, day = _date_from_ordinal(
            self.toordinal() + other.days
        )
        return date(year, month, day)

    def __radd__(self, other: timedelta) -> date:
        return self + other

    @overload
    def __sub__(self, other: date) -> timedelta: ...

    @overload
    def __sub__(self, other: timedelta) -> date: ...

    def __sub__(self, other: date | timedelta) -> timedelta | date:
        if isinstance(other, timedelta):
            year, month, day = _date_from_ordinal(
                self.toordinal() - other.days
            )
            return date(year, month, day)
        return timedelta(days=self.toordinal() - other.toordinal())

    def replace(
        self,
        year: int | Literal["__pyjs_datetime_unspecified"] = (
            "__pyjs_datetime_unspecified"
        ),
        month: int | Literal["__pyjs_datetime_unspecified"] = (
            "__pyjs_datetime_unspecified"
        ),
        day: int | Literal["__pyjs_datetime_unspecified"] = (
            "__pyjs_datetime_unspecified"
        ),
    ) -> date:
        return date(
            _replacement(year, self.year),
            _replacement(month, self.month),
            _replacement(day, self.day),
        )


class datetime:
    def __init__(
        self,
        year: int,
        month: int,
        day: int,
        hour: int = 0,
        minute: int = 0,
        second: int = 0,
        microsecond: int = 0,
        *,
        fold: int = 0,
    ) -> None:
        _validate_date(year, month, day)
        if hour < 0 or hour > 23:
            raise ValueError(f"hour must be in 0..23, not {hour}")
        if minute < 0 or minute > 59:
            raise ValueError(f"minute must be in 0..59, not {minute}")
        if second < 0 or second > 59:
            raise ValueError(f"second must be in 0..59, not {second}")
        if microsecond < 0 or microsecond > 999999:
            raise ValueError(
                f"microsecond must be in 0..999999, not {microsecond}"
            )
        if fold < 0 or fold > 1:
            raise ValueError(f"fold must be either 0 or 1, not {fold}")
        self._year = year
        self._month = month
        self._day = day
        self._hour = hour
        self._minute = minute
        self._second = second
        self._microsecond = microsecond
        self._fold = fold

    @property
    def year(self) -> int:
        return self._year

    @property
    def month(self) -> int:
        return self._month

    @property
    def day(self) -> int:
        return self._day

    @property
    def hour(self) -> int:
        return self._hour

    @property
    def minute(self) -> int:
        return self._minute

    @property
    def second(self) -> int:
        return self._second

    @property
    def microsecond(self) -> int:
        return self._microsecond

    @property
    def fold(self) -> int:
        return self._fold

    def isoformat(self, sep: str = "T", timespec: str = "auto") -> str:
        if len(sep) != 1:
            raise TypeError("isoformat() argument 1 must be a unicode character")
        if timespec not in {
            "auto",
            "hours",
            "minutes",
            "seconds",
            "milliseconds",
            "microseconds",
        }:
            raise ValueError("Unknown timespec value")
        result = (
            str(self.year).zfill(4)
            + "-"
            + str(self.month).zfill(2)
            + "-"
            + str(self.day).zfill(2)
            + sep
        )
        result += str(self.hour).zfill(2) + ":" + str(self.minute).zfill(2)
        if timespec == "hours":
            return result[:13]
        if timespec != "minutes":
            result += ":" + str(self.second).zfill(2)
        if timespec == "milliseconds":
            result += "." + str(self.microsecond // 1000).zfill(3)
        elif timespec == "microseconds" or (
            timespec == "auto" and self.microsecond != 0
        ):
            result += "." + str(self.microsecond).zfill(6)
        return result

    def __str__(self) -> str:
        return self.isoformat(" ")

    def toordinal(self) -> int:
        return _ordinal(self.year, self.month, self.day)

    @classmethod
    def fromordinal(cls, ordinal: int) -> datetime:
        if ordinal < 1 or ordinal > 3652059:
            raise ValueError("ordinal must be >= 1")
        year, month, day = _date_from_ordinal(ordinal)
        return cls(year, month, day)

    @classmethod
    def fromisoformat(cls, value: str) -> datetime:
        try:
            date_length = 10 if len(value) >= 10 and value[4] == "-" else 8
            year, month, day = _calendar_date(value[:date_length])
            if len(value) == date_length:
                return cls(year, month, day)
            clock = value[date_length + 1 :]
            if not clock or "Z" in clock or "+" in clock or "-" in clock:
                raise ValueError("invalid ISO date or time")
            hour, minute, second, microsecond = _clock_time(clock)
        except ValueError:
            raise ValueError(  # noqa: B904
                f"Invalid isoformat string: {value!r}"
            )
        return cls(
            year,
            month,
            day,
            hour,
            minute,
            second,
            microsecond,
        )

    def date(self) -> date:
        return date(self.year, self.month, self.day)

    def weekday(self) -> int:
        return (self.toordinal() + 6) % 7

    def isoweekday(self) -> int:
        return self.weekday() + 1

    def isocalendar(self) -> tuple[int, int, int]:
        return self.date().isocalendar()

    def _timestamp_microseconds(self) -> int:
        return (
            (self.toordinal() * _SECONDS_PER_DAY + self.hour * 3600)
            * _MICROSECONDS_PER_SECOND
            + self.minute * 60 * _MICROSECONDS_PER_SECOND
            + self.second * _MICROSECONDS_PER_SECOND
            + self.microsecond
        )

    def __eq__(self, other: datetime) -> bool:
        return self._timestamp_microseconds() == other._timestamp_microseconds()

    def __hash__(self) -> int:
        return hash(self._timestamp_microseconds())

    def __lt__(self, other: datetime) -> bool:
        return self._timestamp_microseconds() < other._timestamp_microseconds()

    def __le__(self, other: datetime) -> bool:
        return self._timestamp_microseconds() <= other._timestamp_microseconds()

    def __gt__(self, other: datetime) -> bool:
        return self._timestamp_microseconds() > other._timestamp_microseconds()

    def __ge__(self, other: datetime) -> bool:
        return self._timestamp_microseconds() >= other._timestamp_microseconds()

    def __add__(self, other: timedelta) -> datetime:
        total = wide.add(wide.widen(self._timestamp_microseconds()), other._wide_microseconds())
        if (wide.less(total, wide.widen(_MICROSECONDS_PER_DAY))
                or not wide.less(total, wide.widen(3652060 * _MICROSECONDS_PER_DAY))):
            raise OverflowError("date value out of range")
        values = _datetime_from_microseconds(wide.narrow(total))
        return datetime(
            values[0],
            values[1],
            values[2],
            values[3],
            values[4],
            values[5],
            values[6],
        )

    def __radd__(self, other: timedelta) -> datetime:
        return self + other

    @overload
    def __sub__(self, other: datetime) -> timedelta: ...

    @overload
    def __sub__(self, other: timedelta) -> datetime: ...

    def __sub__(self, other: datetime | timedelta) -> timedelta | datetime:
        if isinstance(other, timedelta):
            return self + -other
        return timedelta(
            microseconds=(
                self._timestamp_microseconds()
                - other._timestamp_microseconds()
            )
        )

    def replace(
        self,
        year: int | Literal["__pyjs_datetime_unspecified"] = (
            "__pyjs_datetime_unspecified"
        ),
        month: int | Literal["__pyjs_datetime_unspecified"] = (
            "__pyjs_datetime_unspecified"
        ),
        day: int | Literal["__pyjs_datetime_unspecified"] = (
            "__pyjs_datetime_unspecified"
        ),
        hour: int | Literal["__pyjs_datetime_unspecified"] = (
            "__pyjs_datetime_unspecified"
        ),
        minute: int | Literal["__pyjs_datetime_unspecified"] = (
            "__pyjs_datetime_unspecified"
        ),
        second: int | Literal["__pyjs_datetime_unspecified"] = (
            "__pyjs_datetime_unspecified"
        ),
        microsecond: int | Literal[
            "__pyjs_datetime_unspecified"
        ] = "__pyjs_datetime_unspecified",
        *,
        fold: int | Literal["__pyjs_datetime_unspecified"] = (
            "__pyjs_datetime_unspecified"
        ),
    ) -> datetime:
        return datetime(
            _replacement(year, self.year),
            _replacement(month, self.month),
            _replacement(day, self.day),
            _replacement(hour, self.hour),
            _replacement(minute, self.minute),
            _replacement(second, self.second),
            _replacement(microsecond, self.microsecond),
            fold=_replacement(fold, self.fold),
        )


__all__ = ["date", "datetime", "timedelta"]
