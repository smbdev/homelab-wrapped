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


def _bytes_parts(n: float) -> tuple[float, str]:
    """Scale bytes to a display (number, unit) pair — the number is the hero."""
    if n >= 1e12:
        return round(n / 1e12, 1), "TB"
    if n >= 1e9:
        return round(n / 1e9), "GB"
    return round(n / 1e6), "MB"


def _human_bytes(n: float) -> str:
    num, unit = _bytes_parts(n)
    return f"{num:,} {unit}"


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


def _docs_total(ctx: FactContext) -> dict[str, Any] | None:
    count, _ = ctx.store.totals(ctx.since, ctx.until, kind="doc.added")
    if not count:
        return None
    return {
        "value": count,
        "headline": f"{plural(count, 'document')} archived",
        "sub": "the filing cabinet never stood a chance",
    }


def _docs_top_senders(ctx: FactContext) -> dict[str, Any] | None:
    top = ctx.store.top(ctx.since, ctx.until, kind="doc.added", by="count")
    top = [(label, n, v) for label, n, v in top if label]
    if not top:
        return None
    return {
        "headline": "Who sent all that paper",
        "items": [{"label": label, "value": plural(n, "doc")} for label, n, _ in top],
    }


def _files_total(ctx: FactContext) -> dict[str, Any] | None:
    count, _ = ctx.store.totals(ctx.since, ctx.until, kind="file.created")
    if not count:
        return None
    return {
        "value": count,
        "headline": f"{plural(count, 'file')} added to your cloud",
        "sub": "synced, safe, and self-hosted",
    }


def _files_top_folders(ctx: FactContext) -> dict[str, Any] | None:
    top = ctx.store.top(ctx.since, ctx.until, kind="file.created", by="count")
    if not top:
        return None
    return {
        "headline": "Where they all went",
        "items": [{"label": label, "value": plural(n, "file")} for label, n, _ in top],
    }


def _storage_growth(ctx: FactContext) -> dict[str, Any] | None:
    samples = [e.value for e in ctx.store.events(ctx.since, ctx.until, kind="storage.used")]
    if not samples:
        return None
    current = samples[-1]
    grown = current - samples[0]
    # value is the scaled display number (71 for "71 MB"), never raw bytes —
    # the big-number template renders it as the hero
    if grown > 0:
        num, unit = _bytes_parts(grown)
        return {
            "value": num,
            "headline": f"{num:,} {unit} added to your cloud",
            "sub": f"now {_human_bytes(current)} in total",
        }
    num, unit = _bytes_parts(current)
    return {
        "value": num,
        "headline": f"{num:,} {unit} in your cloud",
        "sub": "and holding steady",
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
    """One recap fact: id, card template, running order, and its compute fn.

    Attributes:
        id: Stable fact identifier, e.g. ``media.top_shows``.
        template: Which player card template renders it.
        compute: Turns a :class:`FactContext` into a card, or ``None``.
        rank: Position in the story. Cards are emitted in ascending rank, not
            in list order, so a fact can be added anywhere in ``FACTS`` and
            still land in the right beat of the recap. See :data:`FACTS`.
        private: Private facts render locally but are stripped from exports.
    """

    id: str
    template: str
    compute: Callable[[FactContext], dict[str, Any] | None]
    rank: int
    private: bool = False


# The running order of the recap, not a registry — the list is sorted by
# ``rank`` before rendering, so this is the story's shape:
#
#   10–40    what you watched and shot — the warm, personal open
#   50–90    what you filed and stored — your stuff piling up
#   100–140  the machines: containers, bandwidth, ads swallowed. The numbers
#            get big here; dns.blocked_total is the loudest brag we have.
#   150–160  back to you: the streak, then the whole year as one grid
#
# Facts with no data return no card, so the arc degrades gracefully — a
# Jellyfin-only homelab still opens on hours watched and closes on its
# heatmap. Ranks are spaced by 10 so a new fact can slot between two
# existing beats without renumbering.
#
# ponytail: static ranks, not data-driven scoring — an "impressiveness"
# score per card would let a monster number promote itself to the finale;
# add that if a fixed order proves boring across real homelabs.
FACTS: list[Fact] = [
    Fact("media.total_hours", "big_number", _media_total_hours, rank=10),
    Fact("media.top_shows", "top_list", _media_top_shows, rank=20),
    Fact("photos.total", "big_number", _photos_total, rank=30),
    Fact("photos.busiest_day", "superlative", _photos_busiest_day, rank=40),
    Fact("files.total", "big_number", _files_total, rank=50),
    Fact("files.top_folders", "top_list", _files_top_folders, rank=60),
    Fact("docs.total", "big_number", _docs_total, rank=70),
    Fact("docs.top_senders", "top_list", _docs_top_senders, rank=80),
    Fact("storage.growth", "big_number", _storage_growth, rank=90),
    Fact("system.containers", "big_number", _system_containers, rank=100),
    Fact("network.total", "big_number", _network_total, rank=110),
    Fact("network.by_service", "comparison", _network_by_service, rank=120),
    Fact("dns.blocked_total", "big_number", _dns_blocked_total, rank=130),
    Fact("dns.top_blocked", "top_list", _dns_top_blocked, rank=140),
    Fact("activity.streak", "streak", _activity_streak, rank=150),
    Fact("activity.by_day", "heatmap", _activity_heatmap, rank=160),
]
