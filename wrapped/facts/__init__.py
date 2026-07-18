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


_INFRA_KINDS = ("net.", "system.", "dns.")  # samples/aggregates, not human activity


def _activity_streak(ctx: FactContext) -> dict[str, Any] | None:
    days = ctx.store.by_day(ctx.since, ctx.until, ctx.tz, exclude=_INFRA_KINDS)
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
    days = ctx.store.by_day(ctx.since, ctx.until, ctx.tz, count=True, exclude=_INFRA_KINDS)
    if not days:
        return None
    return {
        "headline": "Your year, day by day",
        "data": {d.isoformat(): int(v) for d, v in sorted(days.items())},
    }


def _human_bytes(n: float) -> str:
    if n >= 1e12:
        return f"{n / 1e12:.1f} TB"
    if n >= 1e9:
        return f"{round(n / 1e9):,} GB"
    return f"{round(n / 1e6):,} MB"


def _net_deltas(ctx: FactContext) -> dict[str, float]:
    """Total bytes moved per container across the window.

    Samples are cumulative counters; a counter that shrank means the
    container restarted, so that sample contributes its own value rather
    than a negative delta.
    """
    last: dict[str, float] = {}
    moved: dict[str, float] = {}
    for e in ctx.store.events(ctx.since, ctx.until, kind="net.sample"):
        name = e.entity or "unknown"
        prev = last.get(name)
        if prev is not None:
            moved[name] = moved.get(name, 0.0) + (e.value - prev if e.value >= prev else e.value)
        last[name] = e.value
    return {k: v for k, v in moved.items() if v > 0}


def _network_total(ctx: FactContext) -> dict[str, Any] | None:
    total = sum(_net_deltas(ctx).values())
    if total < 1e9:
        return None  # under a gigabyte isn't a story
    value: float | int
    if total >= 1e12:
        value, unit = round(total / 1e12, 1), "TB"
    else:
        value, unit = round(total / 1e9), "GB"
    days = max((ctx.until - ctx.since).days, 1)
    return {
        "value": value,
        "headline": f"{value:,} {unit} moved by your rack",
        "sub": f"≈ {_human_bytes(total / days)} a day through your containers",
    }


def _network_by_service(ctx: FactContext) -> dict[str, Any] | None:
    per = _net_deltas(ctx)
    if len(per) < 2:
        return None
    top = sorted(per.items(), key=lambda kv: kv[1], reverse=True)[:4]
    return {
        "headline": "Who moved the most bits",
        "items": [{"label": name, "value": _human_bytes(n), "raw": round(n)} for name, n in top],
    }


def _dns_blocked_total(ctx: FactContext) -> dict[str, Any] | None:
    _, blocked = ctx.store.totals(ctx.since, ctx.until, kind="dns.blocked")
    if blocked < 1000:
        return None  # a recap brag needs at least four digits
    n = int(blocked)
    card: dict[str, Any] = {
        "value": n,
        "headline": f"{n:,} ads and trackers blocked",
    }
    _, total = ctx.store.totals(ctx.since, ctx.until, kind="dns.query")
    if total:
        card["sub"] = f"{blocked / total:.0%} of all DNS queries, swallowed by Pi-hole"
    return card


def _dns_top_blocked(ctx: FactContext) -> dict[str, Any] | None:
    top = ctx.store.top(ctx.since, ctx.until, kind="dns.blocked_domain", by="value")
    if not top:
        return None
    return {
        "headline": "Most-blocked domains",
        "items": [{"label": label, "value": f"{int(v):,}×"} for label, _, v in top],
    }


def _system_containers(ctx: FactContext) -> dict[str, Any] | None:
    latest = None
    for e in ctx.store.events(ctx.since, ctx.until, kind="system.containers"):
        latest = e  # events yield oldest→newest
    if latest is None or latest.value < 1:
        return None
    n = int(latest.value)
    return {
        "value": n,
        "headline": f"{plural(n, 'container')} kept running",
        "sub": "one very reliable box",
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
    Fact("network.total", "big_number", _network_total),
    Fact("network.by_service", "comparison", _network_by_service),
    Fact("dns.blocked_total", "big_number", _dns_blocked_total),
    Fact("dns.top_blocked", "top_list", _dns_top_blocked),
    Fact("system.containers", "big_number", _system_containers),
]
