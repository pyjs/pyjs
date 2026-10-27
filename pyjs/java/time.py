"""Native ISO calendar dates and injectable clocks (Android API 26+)."""
from pyjs import jvm
from pyjs.java import i32


@jvm.native("java/time/DateTimeException")
class DateTimeException(Exception):
    pass


@jvm.native("java/time/LocalDate")
class LocalDate:
    def toString(self) -> str: ...
    def getYear(self) -> i32: ...
    def getMonthValue(self) -> i32: ...
    def getDayOfMonth(self) -> i32: ...
    def plusDays(self, days: int) -> LocalDate: ...


@jvm.native("java/time/Instant")
class Instant:
    pass


@jvm.native("java/time/ZoneId")
class ZoneId:
    pass


@jvm.native("java/time/Clock")
class Clock:
    pass


@jvm.native("java/time/LocalDate", name="now")
def local_today() -> LocalDate:
    """Use the device's current clock and default time zone, not UTC."""
    ...


@jvm.native("java/time/LocalDate", name="now")
def local_date_at(clock: Clock) -> LocalDate: ...


@jvm.native("java/time/LocalDate", name="of")
def local_date(year: i32, month: i32, day: i32) -> LocalDate: ...


@jvm.native("java/time/Instant", name="ofEpochMilli")
def instant_from_epoch_millis(milliseconds: int) -> Instant: ...


@jvm.native("java/time/ZoneId", name="of")
def zone_id(name: str) -> ZoneId: ...


@jvm.native("java/time/Clock", name="fixed")
def fixed_clock(instant: Instant, zone: ZoneId) -> Clock: ...
