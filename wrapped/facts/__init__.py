"""Fact definitions: what a recap can say, and the words it says it with.

A fact is a small function that turns windowed event aggregates into one
story card (or ``None`` when there's no data — absent facts simply don't
appear, they never crash). All copy is deterministic string templating; no AI.

Facts are discovered from data: each declares the event ``kind`` it feeds on,
so any connector that emits that kind lights the fact up automatically.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any

from wrapped.core.events import EventStore, busiest_day, longest_streak


@dataclass(frozen=True)
class FactContext:
    """Everything a fact function needs to compute its card."""

    store: EventStore
    since: datetime
    until: datetime
    tz: tzinfo


def plural(n: int | float, noun: str, plural_form: str | None = None) -> str:
    """Format a count with its correctly pluralised noun: ``plural(2, 'hour')`` → ``"2 hours"``."""
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    word = noun if n == 1 else (plural_form or noun + "s")
    return f"{n:,} {word}"


def _media_total_hours(ctx: FactContext) -> dict[str, Any] | None:
    plays, minutes = ctx.store.totals(ctx.since, ctx.until, kind="media.play")
    if not plays:
        return None
    hours = round(minutes / 60)
    card: dict[str, Any] = {
        "value": hours,
        "headline": f"{plural(hours, 'hour')} watched",
    }
    days = minutes / 60 / 24
    if days >= 1:
        card["sub"] = f"That's {plural(round(days), 'full day')} of telly"
    return card


def _media_top_shows(ctx: FactContext) -> dict[str, Any] | None:
    top = ctx.store.top(ctx.since, ctx.until, kind="media.play", by="count")
    if not top:
        return None
    return {
        "headline": "Your top shows",
        "items": [{"label": label, "value": plural(n, "ep")} for label, n, _ in top],
    }


def _photos_total(ctx: FactContext) -> dict[str, Any] | None:
    count, _ = ctx.store.totals(ctx.since, ctx.until, kind="photo.taken")
    if not count:
        return None
    return {"value": count, "headline": f"{plural(count, 'photo')} taken"}


def _photos_busiest_day(ctx: FactContext) -> dict[str, Any] | None:
    days = ctx.store.by_day(ctx.since, ctx.until, ctx.tz, kind="photo.taken")
    best = busiest_day(days)
    if best is None:
        return None
    day, count = best
    return {
        "value": int(count),
        "headline": f"{plural(int(count), 'photo')} in one day",
        "sub": f"Your camera's big day out: {day:%-d %B}",
    }


def _activity_streak(ctx: FactContext) -> dict[str, Any] | None:
    days = ctx.store.by_day(ctx.since, ctx.until, ctx.tz)
    length, start = longest_streak(days)
    if length < 2:
        return None
    return {
        "value": length,
        "headline": f"A {length}-day streak",
        "sub": f"Every single day from {start:%-d %B}",
    }


def _activity_heatmap(ctx: FactContext) -> dict[str, Any] | None:
    # Counts, not values: values mix units across kinds (minutes vs photos).
    days = ctx.store.by_day(ctx.since, ctx.until, ctx.tz, count=True)
    if not days:
        return None
    return {
        "headline": "Your year, day by day",
        "data": {d.isoformat(): int(v) for d, v in sorted(days.items())},
    }


@dataclass(frozen=True)
class Fact:
    """One recap fact: id, card template, privacy default, and its compute fn."""

    id: str
    template: str
    compute: Callable[[FactContext], dict[str, Any] | None]
    private: bool = False  # private facts render locally but are stripped from exports


FACTS: list[Fact] = [
    Fact("media.total_hours", "big_number", _media_total_hours),
    Fact("media.top_shows", "top_list", _media_top_shows),
    Fact("photos.total", "big_number", _photos_total),
    Fact("photos.busiest_day", "superlative", _photos_busiest_day),
    Fact("activity.streak", "streak", _activity_streak),
    Fact("activity.by_day", "heatmap", _activity_heatmap),
]
