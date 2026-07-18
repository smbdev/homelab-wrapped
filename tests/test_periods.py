"""Window computation: year/month/day/on-this-day, DST and leap edges."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from wrapped.core.periods import day_window, month_window, on_this_day_windows, year_window

BERLIN = ZoneInfo("Europe/Berlin")


def test_year_window():
    start, end = year_window(2026, BERLIN)
    assert start == datetime(2026, 1, 1, tzinfo=BERLIN)
    assert end == datetime(2027, 1, 1, tzinfo=BERLIN)


def test_month_window_december_rolls_year():
    start, end = month_window(2026, 12, BERLIN)
    assert end == datetime(2027, 1, 1, tzinfo=BERLIN)


def test_leap_february_length():
    start, end = month_window(2028, 2, UTC)
    assert (end - start).days == 29


def test_dst_spring_forward_day_is_23_hours():
    start, end = day_window(2026, 3, 29, BERLIN)  # DST starts in Berlin
    assert end - start == timedelta(days=1)  # wall clock
    assert (end.astimezone(UTC) - start.astimezone(UTC)) == timedelta(hours=23)  # real time


def test_dst_fall_back_day_is_25_hours():
    start, end = day_window(2026, 10, 25, BERLIN)
    assert (end.astimezone(UTC) - start.astimezone(UTC)) == timedelta(hours=25)


def test_on_this_day_windows():
    windows = on_this_day_windows(7, 18, UTC, 2024, 2026)
    assert [y for y, _, _ in windows] == [2024, 2025, 2026]
    year, start, end = windows[0]
    assert start == datetime(2024, 7, 18, tzinfo=UTC)
    assert end == datetime(2024, 7, 19, tzinfo=UTC)


def test_on_this_day_feb29_skips_non_leap_years():
    windows = on_this_day_windows(2, 29, UTC, 2024, 2029)
    assert [y for y, _, _ in windows] == [2024, 2028]
