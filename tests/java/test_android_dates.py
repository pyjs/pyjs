import pytest

from pyjs import jvm
from pyjs.android.dates import DateFormatFlags, format_date_time
from pyjs.android.pickers import is_24_hour_format
from pyjs.android.testing import application_context
from pyjs.java.time import local_date_time, zone_id

pytestmark = pytest.mark.pyjs_android_jvm


@jvm.native("java/util/Locale")
class TestLocale:
    pass


@jvm.native("java/util/Locale", name="getDefault")
def default_locale() -> TestLocale: ...


@jvm.native("java/util/Locale", name="forLanguageTag")
def locale_for_tag(tag: str) -> TestLocale: ...


@jvm.native("java/util/Locale", name="setDefault")
def set_locale(locale: TestLocale) -> None: ...


@jvm.native("java/util/TimeZone")
class TestZone:
    pass


@jvm.native("java/util/TimeZone", name="getDefault")
def default_zone() -> TestZone: ...


@jvm.native("java/util/TimeZone", name="getTimeZone")
def time_zone(name: str) -> TestZone: ...


@jvm.native("java/util/TimeZone", name="setDefault")
def set_zone(zone: TestZone) -> None: ...


def test_native_date_time_uses_locale_zone_and_preserves_long_timestamps() -> None:
    old_locale = default_locale()
    old_zone = default_zone()
    context = application_context()
    at = local_date_time(2044, 2, 29, 0, 15).atZone(zone_id("UTC")).toInstant().toEpochMilli()
    date_flags = DateFormatFlags.SHOW_DATE | DateFormatFlags.SHOW_YEAR
    try:
        set_locale(locale_for_tag("en-US"))
        set_zone(time_zone("UTC"))
        assert format_date_time(context, at, date_flags) == "February 29, 2044"
        assert format_date_time(context, at, date_flags | DateFormatFlags.ABBREV_MONTH) == "Feb 29, 2044"
        assert format_date_time(context, at, date_flags | DateFormatFlags.NUMERIC_DATE) == "2/29/2044"
        set_zone(time_zone("America/New_York"))
        assert format_date_time(context, at, date_flags) == "February 28, 2044"
        set_locale(locale_for_tag("fr-FR"))
        assert format_date_time(context, at, date_flags) == "28 février 2044"
    finally:
        set_zone(old_zone)
        set_locale(old_locale)


def test_native_time_defaults_to_device_clock_preference() -> None:
    old_locale = default_locale()
    old_zone = default_zone()
    context = application_context()
    at = local_date_time(2044, 2, 29, 17, 5).atZone(zone_id("UTC")).toInstant().toEpochMilli()
    try:
        set_locale(locale_for_tag("en-US"))
        set_zone(time_zone("UTC"))
        twelve = format_date_time(context, at, DateFormatFlags.SHOW_TIME | DateFormatFlags.HOUR_12)
        twenty_four = format_date_time(context, at, DateFormatFlags.SHOW_TIME | DateFormatFlags.HOUR_24)
        assert twelve.replace("\u202f", " ") == "5:05 PM"
        assert twenty_four == "17:05"
        expected = twenty_four if is_24_hour_format(context) else twelve
        assert format_date_time(context, at, DateFormatFlags.SHOW_TIME) == expected
    finally:
        set_zone(old_zone)
        set_locale(old_locale)
