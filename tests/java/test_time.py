from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from tests.java.test_exceptions import assert_compiles_to_android_dex, run_jvm


@pytest.mark.parametrize("milliseconds", [0, -1, 1772956800000, 1793518200000])
@pytest.mark.parametrize("zone,hours", [("UTC", 0), ("-08:00", -8), ("+14:00", 14)])
def test_injected_clock_uses_the_selected_calendar_day(tmp_path, milliseconds, zone, hours):
    expected = datetime.fromtimestamp(milliseconds / 1000, UTC).astimezone(
        timezone(timedelta(hours=hours)),
    ).date()
    source = f'''
from pyjs.java.time import fixed_clock, instant_from_epoch_millis, local_date_at, zone_id
def main() -> str:
    clock = fixed_clock(instant_from_epoch_millis({milliseconds}), zone_id({zone!r}))
    value = local_date_at(clock)
    assert value.getYear() == {expected.year}
    assert value.getMonthValue() == {expected.month}
    assert value.getDayOfMonth() == {expected.day}
    return value.toString()
'''
    result = run_jvm(source, tmp_path)
    assert result.returncode == 0 and result.stderr == "", result.stderr
    assert result.stdout == expected.isoformat()


CALENDAR_SOURCE = '''
from pyjs.java import i32
from pyjs.java.time import DateTimeException, local_date, local_today
def main() -> str:
    day = local_date(i32(2024), i32(2), i32(28))
    assert day.plusDays(1).toString() == "2024-02-29"
    assert day.plusDays(2).toString() == "2024-03-01"
    assert day.plusDays(-28).toString() == "2024-01-31"
    assert day.toString() == "2024-02-28"
    rejected = False
    try:
        local_date(i32(2026), i32(2), i32(29))
    except DateTimeException:
        rejected = True
    assert rejected
    return local_today().toString()
'''


def test_calendar_arithmetic_invalid_dates_and_device_today(tmp_path):
    result = run_jvm(CALENDAR_SOURCE, tmp_path)
    assert result.returncode == 0 and result.stderr == "", result.stderr
    assert date.fromisoformat(result.stdout).isoformat() == result.stdout


def test_calendar_bindings_compile_for_android(tmp_path):
    assert_compiles_to_android_dex(CALENDAR_SOURCE, tmp_path)


def test_named_zone_and_invalid_zone_id(tmp_path):
    result = run_jvm('''
from pyjs.java.time import DateTimeException, fixed_clock, instant_from_epoch_millis, local_date_at, zone_id
def main() -> str:
    clock = fixed_clock(instant_from_epoch_millis(0), zone_id("America/New_York"))
    assert local_date_at(clock).toString() == "1969-12-31"
    try:
        zone_id("Not/A_Zone")
    except DateTimeException:
        return "rejected"
    return "missed invalid zone"
''', tmp_path)
    assert result.returncode == 0 and result.stderr == "", result.stderr
    assert result.stdout == "rejected"
