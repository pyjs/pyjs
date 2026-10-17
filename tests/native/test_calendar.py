import datetime as dt
import random

import pytest

from pyjs.analysis.diagnostics import CompilationError
from pyjs.native.llvm import transpile_llvm
from pyjs.tooling.llvm import LLVM


@pytest.mark.parametrize("optimize", [0, 2])
def test_duration_normalization_checks_bounds_after_wide_cancellation(optimize):
    result = LLVM().assert_matches_python('''
        from datetime import timedelta
        def main() -> str:
            values = [timedelta(days=999999999, seconds=86399, microseconds=999999),
                      timedelta(days=-999999999), timedelta(days=200000000),
                      timedelta(weeks=2**60, days=-(7 * 2**60), microseconds=-1)]
            result = str(values[0]) + '/' + str(values[1]) + '/' + str(values[2]) + '/' + str(values[3])
            try:
                timedelta(seconds=2**63-1, milliseconds=-(2**63-1))
            except OverflowError:
                result += '/overflow'
            return result
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_large_duration_integer_arithmetic_keeps_wide_intermediates(optimize):
    result = LLVM().assert_matches_python('''
        from datetime import datetime, timedelta
        def main() -> str:
            result: list[str] = []
            for days in [-999999999, -200000000, 200000000, 999999998]:
                value = timedelta(days=days, seconds=7, microseconds=5)
                for divisor in [-7, -2, 1, 3]:
                    unit = timedelta(days=divisor, microseconds=3)
                    quotient, remainder = divmod(value, unit)
                    result.append(str((str(value * 1), str(value / divisor), str(value // divisor),
                                       str(value // unit), str(value % unit), quotient, str(remainder),
                                       value.total_seconds(), value / unit)))
            try:
                timedelta(days=999999999) * (2**63 - 1)
            except OverflowError:
                result.append('overflow')
            for days in [-999999999, 999999999]:
                try:
                    datetime(2024, 1, 1) + timedelta(days=days)
                except OverflowError as error:
                    result.append(str(error))
            return '/'.join(result)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_duration_float_scaling_rounds_the_exact_binary_ratio_once(optimize):
    result = LLVM().assert_matches_python('''
        from datetime import timedelta
        def multiply(value: timedelta, factor: float) -> str:
            try:
                return str(value * factor)
            except OverflowError:
                return 'overflow'
            except ValueError:
                return 'invalid'
        def divide(value: timedelta, factor: float) -> str:
            try:
                return str(value / factor)
            except OverflowError:
                return 'overflow'
            except ValueError:
                return 'invalid'
            except ZeroDivisionError:
                return 'zero'
        def main() -> str:
            result: list[str] = []
            for value in [timedelta(), timedelta(microseconds=3), timedelta(microseconds=9007199254740993),
                          timedelta(days=-200000000, microseconds=5), timedelta(days=999999999)]:
                for factor in [1.0, 0.5, -0.5, 1.1, -7.0, 1e-300, 1e300, 5e-324,
                               -0.0, float('inf'), float('nan')]:
                    result.append(multiply(value, factor) + ':' + divide(value, factor))
            return '/'.join(result)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_duration_float_scaling_randomized_host_parity(tmp_path, optimize):
    source = '''
from datetime import timedelta
def main(value: timedelta, factor: float) -> str:
    try:
        product = str(value * factor)
    except OverflowError:
        product = 'overflow'
    try:
        quotient = str(value / factor)
    except OverflowError:
        quotient = 'overflow'
    return product + '/' + quotient
'''
    namespace = {}
    exec(source, namespace)
    expected = namespace["main"]
    generator = random.Random(7311)
    library = LLVM().compile_library(source, tmp_path, optimize=optimize)
    try:
        for _ in range(160):
            value = dt.timedelta(days=generator.randint(-999999999, 999999998),
                                 seconds=generator.randrange(86400), microseconds=generator.randrange(1000000))
            factor = generator.uniform(-2.0, 2.0) * 2.0**generator.randint(-1070, 900)
            if factor != 0.0:
                assert library.render(value, factor) == expected(value, factor), (value, factor)
    finally:
        library.close()


def test_llvm_marshals_and_constructs_datetime_values(tmp_path):
    comparison = LLVM().assert_library_matches_python(
        """
        from datetime import date, datetime, timedelta

        def render(
            created: date,
            seen: datetime,
            elapsed: timedelta,
        ) -> str:
            generated = date(2024, 2, 29)
            precise = datetime(2026, 9, 6, 1, 2, 3, 456000)
            window = timedelta(days=2, seconds=3, microseconds=4)
            return (
                f"{created.isoformat()}|{seen}|{elapsed.days}:"
                f"{elapsed.seconds}:{elapsed.microseconds}|{generated}|"
                f"{precise.isoformat(timespec='milliseconds')}|"
                f"{window.days}:{window.seconds}:{window.microseconds}"
            )
        """,
        dt.date(2025, 1, 2),
        dt.datetime(2025, 1, 2, 3, 4, 5, 6000),
        dt.timedelta(
            days=4,
            seconds=5,
            microseconds=6,
        ),
        directory=tmp_path,
        entry_point="render",
    )

    assert comparison.matches
    comparison.library.close()


def test_llvm_datetime_arithmetic_and_calendar_methods_match_python(tmp_path):
    comparison = LLVM().assert_library_matches_python(
        """
        from datetime import date, datetime, timedelta

        def render() -> str:
            first = timedelta(
                days=-1,
                seconds=-2,
                microseconds=-3,
                minutes=1,
            )
            second = timedelta(hours=2, milliseconds=7)
            combined = first + second
            start = date(2024, 2, 28)
            end = date(2024, 3, 1)
            early = datetime(2024, 2, 28, 23, 59, 58, 999999)
            late = datetime(2024, 3, 1, 0, 0, 1)
            elapsed = late - early
            return (
                f"{first}|{combined}|{combined.total_seconds()}|"
                f"{start.weekday()}:{start.isoweekday()}:{end - start}|"
                f"{start < end}:{early < late}:{elapsed}"
            )
        """,
        directory=tmp_path,
        entry_point="render",
    )

    assert comparison.matches
    comparison.library.close()


def test_llvm_date_and_datetime_ordinal_construction_matches_python(tmp_path):
    comparison = LLVM().assert_library_matches_python(
        """
        from datetime import date, datetime

        def render() -> str:
            dates = (
                date.fromordinal(1),
                date.fromordinal(730179),
                date.fromordinal(738945),
                date.fromordinal(3652059),
            )
            values: list[str] = []
            for value in dates:
                iso_year, iso_week, iso_day = value.isocalendar()
                values.append(
                    f"{value}:{iso_year}-W{iso_week:02d}-{iso_day}"
                )
            precise = datetime.fromordinal(738945)
            iso_year, iso_week, iso_day = precise.isocalendar()
            values.append(
                f"{precise}:{precise.date()}:{precise.weekday()}:"
                f"{precise.isoweekday()}:{iso_year}-W{iso_week:02d}-"
                f"{iso_day}"
            )
            return "|".join(values)
        """,
        directory=tmp_path,
        entry_point="render",
    )

    assert comparison.matches
    comparison.library.close()


def test_llvm_date_and_datetime_fromordinal_bounds_are_catchable(tmp_path):
    comparison = LLVM().assert_library_matches_python(
        """
        from datetime import date, datetime

        def render() -> str:
            failures = 0
            try:
                date.fromordinal(0)
            except ValueError:
                failures += 1
            try:
                datetime.fromordinal(3652060)
            except ValueError:
                failures += 1
            return str(failures)
        """,
        directory=tmp_path,
        entry_point="render",
    )

    assert comparison.matches
    comparison.library.close()


def test_llvm_date_and_datetime_iso_parsing_matches_python(tmp_path):
    comparison = LLVM().assert_library_matches_python(
        """
        from datetime import date, datetime

        def render() -> str:
            return "|".join(
                (
                    str(date.fromisoformat("2024-02-29")),
                    str(date.fromisoformat("20240229")),
                    datetime.fromisoformat(
                        "2024-02-29T18:07:06.1234567"
                    ).isoformat(),
                    datetime.fromisoformat(
                        "20240229 180706,125"
                    ).isoformat(),
                    datetime.fromisoformat("2024-02-29").isoformat(),
                    datetime.fromisoformat("2024-02-29x18").isoformat(),
                )
            )
        """,
        directory=tmp_path,
        entry_point="render",
    )

    assert comparison.matches
    comparison.library.close()


def test_llvm_date_and_datetime_iso_parse_errors_are_catchable(tmp_path):
    comparison = LLVM().assert_library_matches_python(
        """
        from datetime import date, datetime

        def render() -> str:
            messages: list[str] = []
            try:
                date.fromisoformat("not-a-date")
            except ValueError as error:
                messages.append(str(error))
            try:
                date.fromisoformat("2024-13-01")
            except ValueError as error:
                messages.append(str(error))
            try:
                datetime.fromisoformat("2024-02-29T12:3456")
            except ValueError as error:
                messages.append(str(error))
            return "|".join(messages)
        """,
        directory=tmp_path,
        entry_point="render",
    )

    assert comparison.matches
    comparison.library.close()


@pytest.mark.parametrize("optimize", [0, 2])
def test_datetime_fold_is_keyword_only_in_construction_and_replacement(optimize):
    result = LLVM().assert_matches_python('''
        from datetime import datetime
        def main() -> str:
            value = datetime(2024, 1, 2, fold=1)
            output = str(value.fold) + str(value.replace(fold=0).fold)
            arguments = [2025, 2, 3, 4, 5, 6, 7, 1]
            try:
                datetime(*arguments)
            except TypeError:
                output += '/constructor-error'
            try:
                value.replace(*arguments)
            except TypeError:
                output += '/replace-error'
            return output
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("expression", ["datetime(2024, 1, 2, 3, 4, 5, 6, 1)",
                                         "datetime(2024, 1, 2).replace(2025, 2, 3, 4, 5, 6, 7, 1)"])
def test_positional_fold_has_a_compilation_diagnostic(expression):
    with pytest.raises(CompilationError):
        transpile_llvm(f'''
            from datetime import datetime
            def main() -> str:
                return str({expression})
        ''')


@pytest.mark.parametrize("optimize", [0, 2])
def test_iso_fractions_require_a_seconds_component(optimize):
    result = LLVM().assert_matches_python('''
        from datetime import datetime
        def main() -> str:
            result: list[str] = []
            for clock in ["12.5", "12,5", "12:30.5", "1230.5", "1230,5",
                          "12:30:00.5", "123000,5", "12", "1230", "12:30"]:
                try:
                    result.append(str(datetime.fromisoformat("2020-01-01T" + clock)))
                except ValueError:
                    result.append("invalid")
            return "|".join(result)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_calendar_hashes_use_normalized_immutable_values(optimize):
    result = LLVM().assert_matches_python('''
        from datetime import date, datetime, timedelta
        from pyjs.native import gc_collect
        def main() -> str:
            duration = timedelta(days=-1, seconds=86399, microseconds=999999)
            day = date(2024, 2, 29)
            stamp = datetime(2024, 2, 29, 12, 34, 56, 789)
            before = (hash(duration), hash(day), hash(stamp))
            gc_collect()
            return str((before == (hash(duration), hash(day), hash(stamp)),
                        hash(duration) == hash(timedelta(microseconds=-1)),
                        hash(day) == hash(date.fromordinal(day.toordinal())),
                        hash(stamp) == hash(datetime.fromisoformat(stamp.isoformat()))))
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


@pytest.mark.parametrize("optimize", [0, 2])
def test_iso_fraction_truncation_still_validates_the_entire_input(optimize):
    result = LLVM().assert_matches_python('''
        from datetime import datetime

        def main() -> str:
            results: list[str] = []
            for fraction in ["123456789", "0" * 100, "123456x", "1234567x",
                             "123456.7", "123456,7", "123456７", ""]:
                for separator in [".", ","]:
                    value = "2024-02-29T12:34:56" + separator + fraction
                    try:
                        results.append(str(datetime.fromisoformat(value)))
                    except ValueError as error:
                        results.append(str(error))
            return "|".join(results)
    ''', optimize=optimize, sanitizers=("address", "undefined"))
    assert result.native.stderr == ""


def test_llvm_date_and_datetime_offsets_and_replacements_match_python(
    tmp_path,
):
    comparison = LLVM().assert_library_matches_python(
        """
        from datetime import date, datetime, timedelta

        def render() -> str:
            leap_day = date(2024, 2, 29)
            previous = leap_day - timedelta(days=365, seconds=86399)
            following = timedelta(days=306) + leap_day
            midnight = datetime(2024, 3, 1)
            before = midnight - timedelta(microseconds=1)
            after = timedelta(
                days=365,
                seconds=3661,
                microseconds=7,
            ) + before
            return "|".join(
                (
                    str(previous),
                    str(following),
                    str(leap_day.replace(year=2020, day=28)),
                    str(before),
                    str(after),
                    str(after.replace(month=2, day=3, fold=1)),
                    str(date(1, 1, 1) + timedelta()),
                    str(datetime(9999, 12, 31, 23, 59, 59, 999999)),
                )
            )
        """,
        directory=tmp_path,
        entry_point="render",
    )

    assert comparison.matches
    comparison.library.close()


def test_llvm_date_and_datetime_offset_overflow_is_catchable(tmp_path):
    comparison = LLVM().assert_library_matches_python(
        """
        from datetime import date, datetime, timedelta

        def render() -> str:
            messages: list[str] = []
            try:
                date(1, 1, 1) + timedelta(days=-1)
            except OverflowError as error:
                messages.append(str(error))
            try:
                datetime(9999, 12, 31, 23, 59, 59, 999999) + timedelta(
                    microseconds=1
                )
            except OverflowError as error:
                messages.append(str(error))
            return "|".join(messages)
        """,
        directory=tmp_path,
        entry_point="render",
    )

    assert comparison.matches
    comparison.library.close()


def test_llvm_datetime_replace_rejects_none_instead_of_treating_it_as_omitted():
    with pytest.raises(
        CompilationError,
        match="Argument 'year' to date.replace expects int",
    ):
        transpile_llvm(
            """
            from datetime import date

            def main() -> int:
                date(2024, 1, 2).replace(year=None)
                return 0
            """
        )


def test_llvm_timedelta_scalar_ratio_and_remainder_arithmetic_matches_python(
    tmp_path,
):
    comparison = LLVM().assert_library_matches_python(
        """
        from datetime import timedelta

        def render() -> str:
            value = timedelta(days=-2, seconds=7322, microseconds=500001)
            unit = timedelta(seconds=7, microseconds=3)
            quotient, remainder = divmod(value, unit)
            negative_quotient, negative_remainder = divmod(value, -unit)
            return "|".join(
                (
                    str(+value),
                    str(abs(value)),
                    str(value * 3),
                    str(2 * value),
                    str(value * 1.5),
                    str(value / 3),
                    str(value / 2.5),
                    str(value / unit),
                    str(value // 4),
                    str(value // unit),
                    str(value % unit),
                    str(quotient),
                    str(remainder),
                    str(negative_quotient),
                    str(negative_remainder),
                    str(timedelta(microseconds=1) * 0.5),
                    str(timedelta(microseconds=3) * 0.5),
                    str(timedelta(microseconds=1) / 2),
                    str(timedelta(microseconds=3) / 2),
                )
            )
        """,
        directory=tmp_path,
        entry_point="render",
    )

    assert comparison.matches
    comparison.library.close()


def test_llvm_timedelta_zero_division_is_catchable(tmp_path):
    comparison = LLVM().assert_library_matches_python(
        """
        from datetime import timedelta

        def render() -> str:
            value = timedelta(seconds=1)
            failures = 0
            try:
                value / 0
            except ZeroDivisionError:
                failures += 1
            try:
                value / timedelta()
            except ZeroDivisionError:
                failures += 1
            try:
                value // 0
            except ZeroDivisionError:
                failures += 1
            try:
                value % timedelta()
            except ZeroDivisionError:
                failures += 1
            return str(failures)
        """,
        directory=tmp_path,
        entry_point="render",
    )

    assert comparison.matches
    comparison.library.close()


def test_llvm_datetime_constructor_errors_are_catchable(tmp_path):
    comparison = LLVM().assert_library_matches_python(
        """
        from datetime import date, datetime

        def render() -> str:
            messages: list[str] = []
            try:
                date(2023, 2, 29)
            except ValueError as error:
                messages.append(str(error))
            try:
                datetime(2023, 1, 1, hour=24)
            except ValueError as error:
                messages.append(str(error))
            return "|".join(messages)
        """,
        directory=tmp_path,
        entry_point="render",
    )

    assert comparison.matches
    comparison.library.close()
