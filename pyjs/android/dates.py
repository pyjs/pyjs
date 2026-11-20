"""Localized Android date/time display; timestamps are epoch milliseconds."""

from typing import Annotated, ClassVar

from pyjs import jvm
from pyjs.android import Context
from pyjs.java import i32


@jvm.native("android/text/format/DateUtils")
class DateFormatFlags:
    SHOW_TIME: ClassVar[Annotated[i32, jvm.field(name="FORMAT_SHOW_TIME", writable=False)]] = 1
    SHOW_WEEKDAY: ClassVar[Annotated[i32, jvm.field(name="FORMAT_SHOW_WEEKDAY", writable=False)]] = 2
    SHOW_YEAR: ClassVar[Annotated[i32, jvm.field(name="FORMAT_SHOW_YEAR", writable=False)]] = 4
    SHOW_DATE: ClassVar[Annotated[i32, jvm.field(name="FORMAT_SHOW_DATE", writable=False)]] = 16
    HOUR_12: ClassVar[Annotated[i32, jvm.field(name="FORMAT_12HOUR", writable=False)]] = 64
    HOUR_24: ClassVar[Annotated[i32, jvm.field(name="FORMAT_24HOUR", writable=False)]] = 128
    ABBREV_MONTH: ClassVar[Annotated[i32, jvm.field(name="FORMAT_ABBREV_MONTH", writable=False)]] = 65536
    NUMERIC_DATE: ClassVar[Annotated[i32, jvm.field(name="FORMAT_NUMERIC_DATE", writable=False)]] = 131072


@jvm.native("android/text/format/DateUtils", name="formatDateTime")
def format_date_time(context: Context, milliseconds: int, flags: i32) -> str:
    """Use the default locale/zone and device clock preference unless overridden."""
    ...
