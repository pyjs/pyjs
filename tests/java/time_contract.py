from pyjs.java import i32
from pyjs.java.time import (
    DateTimeException,
    instant_from_epoch_millis,
    local_date_time,
    system_zone,
    zone_id,
)


def zoned_time_contract() -> None:
    assert len(system_zone().getId()) > 0
    utc = zone_id("UTC")
    for milliseconds in [-1, 0, 1, 1_900_000_000_123]:
        value = instant_from_epoch_millis(milliseconds)
        assert value.atZone(utc).toInstant().toEpochMilli() == milliseconds
    new_york = zone_id("America/New_York")
    gap = local_date_time(i32(2026), i32(3), i32(8), i32(2), i32(30))
    assert gap.toString() == "2026-03-08T02:30"
    assert gap.atZone(new_york).toLocalDateTime().toString() == "2026-03-08T03:30"
    overlap = local_date_time(i32(2026), i32(11), i32(1), i32(1), i32(30)).atZone(new_york)
    early = overlap.withEarlierOffsetAtOverlap()
    late = overlap.withLaterOffsetAtOverlap()
    assert early.toLocalDateTime().toString() == late.toLocalDateTime().toString()
    assert late.toInstant().toEpochMilli() - early.toInstant().toEpochMilli() == 3_600_000
    assert overlap.toInstant().toEpochMilli() == early.toInstant().toEpochMilli()
    half_hour = local_date_time(i32(2026), i32(10), i32(4), i32(2), i32(15))
    assert half_hour.atZone(zone_id("Australia/Lord_Howe")).toLocalDateTime().toString() == "2026-10-04T02:45"
    skipped_day = local_date_time(i32(2011), i32(12), i32(30), i32(12), i32(0))
    adjusted = skipped_day.atZone(zone_id("Pacific/Apia")).toLocalDateTime()
    assert adjusted.getYear() == 2011 and adjusted.getMonthValue() == 12
    assert adjusted.getDayOfMonth() == 31 and adjusted.getHour() == 12 and adjusted.getMinute() == 0
    rejected = False
    try:
        local_date_time(i32(2026), i32(2), i32(29), i32(12), i32(0))
    except DateTimeException:
        rejected = True
    assert rejected
    rejected = False
    try:
        local_date_time(i32(2026), i32(1), i32(1), i32(24), i32(0))
    except DateTimeException:
        rejected = True
    assert rejected
