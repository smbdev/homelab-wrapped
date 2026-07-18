"""Time windows for the three recap modes: yearly, monthly, on-this-day.

All windows are half-open ``[start, end)`` pairs of aware datetimes computed
in the user's timezone, so DST transitions and leap days come out right by
construction (a spring-forward day is simply 23 hours long).
"""

from __future__ import annotations

from calendar import isleap
from datetime import datetime, timedelta, tzinfo


def year_window(year: int, tz: tzinfo) -> tuple[datetime, datetime]:
    """Return the ``[start, end)`` window for a calendar year in ``tz``."""
    return datetime(year, 1, 1, tzinfo=tz), datetime(year + 1, 1, 1, tzinfo=tz)


def month_window(year: int, month: int, tz: tzinfo) -> tuple[datetime, datetime]:
    """Return the ``[start, end)`` window for a calendar month in ``tz``."""
    start = datetime(year, month, 1, tzinfo=tz)
    end = (
        datetime(year + 1, 1, 1, tzinfo=tz)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=tz)
    )
    return start, end


def day_window(year: int, month: int, day: int, tz: tzinfo) -> tuple[datetime, datetime]:
    """Return the ``[start, end)`` window for one calendar day in ``tz``."""
    # Aware-datetime arithmetic is wall-clock: +1 day lands on the next
    # midnight even across DST transitions (that day is just 23/25 real hours).
    start = datetime(year, month, day, tzinfo=tz)
    return start, start + timedelta(days=1)


def on_this_day_windows(
    month: int, day: int, tz: tzinfo, first_year: int, last_year: int
) -> list[tuple[int, datetime, datetime]]:
    """Return one day-window per year for the same calendar day.

    Feb 29 only yields windows in leap years — no remapping to Feb 28.

    Args:
        month: Calendar month of the day.
        day: Day of month.
        tz: User timezone.
        first_year: Earliest year to include.
        last_year: Latest year to include (inclusive).

    Returns:
        ``(year, start, end)`` tuples, oldest first.
    """
    out = []
    for year in range(first_year, last_year + 1):
        if month == 2 and day == 29 and not isleap(year):
            continue
        start, end = day_window(year, month, day, tz)
        out.append((year, start, end))
    return out
