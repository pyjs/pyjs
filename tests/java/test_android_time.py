import pytest

from pyjs.java import i32
from pyjs.java.time import (
    DateTimeException,
    fixed_clock,
    instant_from_epoch_millis,
    local_date,
    local_date_at,
    local_today,
    zone_id,
)

pytestmark = pytest.mark.pyjs_android_jvm


def test_android_calendar_dates_respect_clock_zone_and_native_errors() -> None:
    instant = instant_from_epoch_millis(0)
    utc = local_date_at(fixed_clock(instant, zone_id("UTC")))
    west = local_date_at(fixed_clock(instant, zone_id("America/New_York")))
    assert utc.toString() == "1970-01-01"
    assert west.toString() == "1969-12-31"
    assert utc.getYear() == 1970 and utc.getMonthValue() == 1 and utc.getDayOfMonth() == 1
    assert local_date(i32(2024), i32(2), i32(28)).plusDays(1).toString() == "2024-02-29"
    assert len(local_today().toString()) == 10
    rejected = False
    try:
        local_date(i32(2026), i32(2), i32(29))
    except DateTimeException:
        rejected = True
    assert rejected
