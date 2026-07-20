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
from datetime import UTC, datetime, tzinfo
from typing import Any

from wrapped.core.events import EventStore, busiest_day, longest_streak


@dataclass(frozen=True)
class PriorWindow:
    """The equivalent window one period back, for year-over-year copy.

    Attributes:
        since: Inclusive start of the earlier window.
        until: Exclusive end of the earlier window.
        label: What to call it in copy, e.g. ``"2025"`` or ``"February"``.
    """

    since: datetime
    until: datetime
    label: str


@dataclass(frozen=True)
class FactContext:
    """Everything a fact function needs to compute its card.

    ``prior`` is the same-length window one period earlier, or ``None`` when
    there isn't a sensible one (on-this-day recaps). It's computed by the
    story builder, which is the only place that knows whether this is a year
    or a month.
    """

    store: EventStore
    since: datetime
    until: datetime
    tz: tzinfo
    prior: PriorWindow | None = None


def plural(n: int | float, noun: str, plural_form: str | None = None) -> str:
    """Format a count with its correctly pluralised noun: ``plural(2, 'hour')`` → ``"2 hours"``."""
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    word = noun if n == 1 else (plural_form or noun + "s")
    return f"{n:,} {word}"


# Below this many events in the earlier window, any comparison is noise.
# ponytail: a flat threshold, not a significance test — this is a recap, not
# a statistics package; raise it if real homelabs still produce silly deltas.
_MIN_PRIOR_EVENTS = 3


def versus_prior(ctx: FactContext, current: float, kind: str, by: str = "value") -> str | None:
    """Compare a total against the same window a period earlier.

    The single most shareable line a recap has ("up 38% on 2025"), and the
    data is already in the store — it's the same query one window back.

    Silent (returns ``None``) whenever a comparison would mislead: no prior
    window, a current total of zero, or too little recorded back then. That
    last guard matters — a first-year homelab shouldn't be told it grew
    infinitely, and "up 300%" off a single stray event last year is noise
    dressed up as a statistic. Big multiples get words instead of a
    percentage, because "up 4,200%" reads as a bug.

    Args:
        ctx: The fact's context; uses ``ctx.prior``.
        current: This window's total, in the same unit as ``by``.
        kind: Event kind to total over, e.g. ``"photo.taken"``.
        by: ``"value"`` to sum event values, ``"count"`` to count events.

    Returns:
        A sub-line like ``"up 38% on 2025"``, or ``None`` to stay quiet.
    """
    if ctx.prior is None or not current:
        return None
    count, value = ctx.store.totals(ctx.prior.since, ctx.prior.until, kind=kind)
    if count < _MIN_PRIOR_EVENTS:
        return None
    before = count if by == "count" else value
    if not before:
        return None

    ratio = current / before
    label = ctx.prior.label
    if ratio >= 3:
        return f"more than triple {label}"
    if ratio >= 2:
        return f"more than double {label}"
    if ratio > 1.05:
        return f"up {round((ratio - 1) * 100)}% on {label}"
    if ratio < 0.5:
        return f"less than half {label}"
    if ratio < 0.95:
        return f"down {round((1 - ratio) * 100)}% on {label}"
    return f"almost exactly what you managed in {label}"


def _media_total_hours(ctx: FactContext) -> dict[str, Any] | None:
    plays, minutes = ctx.store.totals(ctx.since, ctx.until, kind="media.play")
    if not plays:
        return None
    hours = round(minutes / 60)
    card: dict[str, Any] = {
        "value": hours,
        "headline": f"{plural(hours, 'hour')} watched",
    }
    # A year-over-year line beats the flavour text when we have one; the
    # flavour text is the fallback for a homelab's first recap.
    days = minutes / 60 / 24
    flavour = f"That's {plural(round(days), 'full day')} of telly" if days >= 1 else None
    sub = versus_prior(ctx, minutes, "media.play") or flavour
    if sub:
        card["sub"] = sub
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
    card: dict[str, Any] = {"value": count, "headline": f"{plural(count, 'photo')} taken"}
    sub = versus_prior(ctx, count, "photo.taken", by="count")
    if sub:
        card["sub"] = sub
    return card


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


# Kinds that must not count as "a thing you did on this day": infrastructure
# samples and aggregates, plus doc.tagged, which shadows a doc.added that's
# already counted (a three-tag document is one document, not four).
_INFRA_KINDS = ("net.", "system.", "dns.", "doc.tagged")


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


def _direction(component: str) -> Callable[[Any], float]:
    """Read one direction off a net.sample: total, or the rx/tx half in meta."""
    if component == "total":
        return lambda e: e.value
    return lambda e: float((e.meta or {}).get(component) or 0.0)


def _counter_deltas(
    ctx: FactContext, kind: str, read: Callable[[Any], float] | None = None
) -> dict[str, float]:
    """Consumption per container across the window, from cumulative samples.

    Docker reports bytes moved and CPU time as counters that only ever climb,
    so what happened *during* a window is the sum of the gaps between
    consecutive samples. A counter that shrank means the container restarted,
    so that sample contributes its own value rather than a negative delta.

    Args:
        kind: Sample kind to walk, e.g. ``"net.sample"``.
        read: Pulls the counter off an event; defaults to ``Event.value``.
    """
    read = read or (lambda e: e.value)
    last: dict[str, float] = {}
    moved: dict[str, float] = {}
    for e in ctx.store.events(ctx.since, ctx.until, kind=kind):
        name = e.entity or "unknown"
        current = read(e)
        prev = last.get(name)
        if prev is not None:
            moved[name] = moved.get(name, 0.0) + (current - prev if current >= prev else current)
        last[name] = current
    return {k: v for k, v in moved.items() if v > 0}


def _net_deltas(ctx: FactContext, component: str = "total") -> dict[str, float]:
    """Bytes moved per container across the window, in one direction.

    Args:
        component: ``"total"`` for the whole sample value, or ``"rx"`` /
            ``"tx"`` to walk the per-direction counters the connector stores
            in ``meta``. Samples missing that key contribute nothing, so an
            event cache written before the split existed degrades to zero
            rather than lying.
    """
    return _counter_deltas(ctx, "net.sample", _direction(component))


def _latest_event_per_entity(ctx: FactContext, kind: str) -> dict[str, Any]:
    """Most recent sample event per container for a gauge kind.

    Gauges describe a moment rather than accumulating, so only the newest
    sample in the window is meaningful. Events arrive oldest-first, so the
    last write per entity wins. Returns the whole event, because when a
    gauge was taken matters as much as what it said.
    """
    out: dict[str, Any] = {}
    for e in ctx.store.events(ctx.since, ctx.until, kind=kind):
        if e.entity:
            out[e.entity] = e
    return out


def _latest_per_entity(ctx: FactContext, kind: str) -> dict[str, float]:
    """Newest gauge value per container (memory, and friends)."""
    return {name: e.value for name, e in _latest_event_per_entity(ctx, kind).items()}


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
    card: dict[str, Any] = {
        "value": value,
        "headline": f"{value:,} {unit} moved by your rack",
        "sub": f"≈ {_human_bytes(total / days)} a day through your containers",
    }
    # The connector has always stored the rx/tx split in meta; splitting the
    # hero number into "down" and "up" is the one thing it's obviously for.
    down = sum(_net_deltas(ctx, "rx").values())
    up = sum(_net_deltas(ctx, "tx").values())
    if down or up:
        card["sats"] = [
            {"k": "downloaded", "v": _human_bytes(down)},
            {"k": "uploaded", "v": _human_bytes(up)},
        ]
    return card


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
        "sub": versus_prior(ctx, count, "doc.added", by="count")
        or "the filing cabinet never stood a chance",
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


def _docs_top_tags(ctx: FactContext) -> dict[str, Any] | None:
    top = ctx.store.top(ctx.since, ctx.until, kind="doc.tagged", by="count")
    if not top:
        return None
    return {
        "headline": "What all that paper was about",
        "items": [{"label": label, "value": plural(n, "doc")} for label, n, _ in top],
    }


def _files_total(ctx: FactContext) -> dict[str, Any] | None:
    count, _ = ctx.store.totals(ctx.since, ctx.until, kind="file.created")
    if not count:
        return None
    return {
        "value": count,
        "headline": f"{plural(count, 'file')} added to your cloud",
        "sub": versus_prior(ctx, count, "file.created", by="count")
        or "synced, safe, and self-hosted",
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
    share = f"{blocked / total:.0%} of all DNS queries, swallowed by Pi-hole" if total else None
    sub = versus_prior(ctx, blocked, "dns.blocked") or share
    if sub:
        card["sub"] = sub
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
    card: dict[str, Any] = {
        "value": n,
        "headline": f"{plural(n, 'container')} kept running",
        "sub": "one very reliable box",
    }
    # The system category has no sibling card to borrow satellites from, so
    # this one carries what the containers were actually doing.
    sats = []
    hours = sum(_counter_deltas(ctx, "system.cpu").values()) / 1e9 / 3600
    if hours >= 1:
        sats.append({"k": "cpu time burned", "v": plural(round(hours), "hour")})
    memory = sum(_latest_per_entity(ctx, "system.memory").values())
    if memory:
        sats.append({"k": "memory in use", "v": _human_bytes(memory)})
    if sats:
        card["sats"] = sats
    return card


def _system_oldest_container(ctx: FactContext) -> dict[str, Any] | None:
    """The container that's been alive longest, by Docker's creation stamp.

    Deliberately "old" rather than "uptime": restarting a container leaves
    its creation stamp alone, so this measures how long it has existed, not
    how long the process has been up. Claiming uptime would be wrong.

    Age is measured to the moment the sample was taken, never to the end of
    the recap window — an in-progress year runs to 31 December, so measuring
    against it would report the age a container is going to reach.
    """
    started = _latest_event_per_entity(ctx, "system.container_started")
    if not started:
        return None
    name, sample = min(started.items(), key=lambda kv: kv[1].value)
    created = datetime.fromtimestamp(sample.value, tz=UTC)
    days = (sample.ts - created).days
    if days < 1:
        return None
    return {
        "value": days,
        "headline": f"{plural(days, 'day')} old",
        "sub": f"{name} is your longest-serving container, born {created:%-d %B %Y}",
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
        private: Off the record. The card still renders in the player — you
            can see your own data — but it can't be exported as a PNG, it
            never feeds the summary card, and it's skipped as a satellite.
            The export list shows it greyed with an "off the record" chip, so
            the redaction is visible rather than silent.

            Mark a fact private when its card names **specific real-world
            things** rather than reporting a number: people who send you post,
            folder names, domains your devices talked to. The test is what a
            stranger learns from the image alone. Aggregate totals are safe;
            named lists usually aren't.
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
#
# Three facts are private=True: the ones whose cards name real-world things
# (correspondents, folder names, blocked domains) rather than reporting a
# number. media.top_shows is deliberately NOT private — it's the flagship
# shareable card, and what you watched is taste rather than identity.
FACTS: list[Fact] = [
    Fact("media.total_hours", "big_number", _media_total_hours, rank=10),
    Fact("media.top_shows", "top_list", _media_top_shows, rank=20),
    Fact("photos.total", "big_number", _photos_total, rank=30),
    Fact("photos.busiest_day", "superlative", _photos_busiest_day, rank=40),
    Fact("files.total", "big_number", _files_total, rank=50),
    Fact("files.top_folders", "top_list", _files_top_folders, rank=60, private=True),
    Fact("docs.total", "big_number", _docs_total, rank=70),
    Fact("docs.top_senders", "top_list", _docs_top_senders, rank=80, private=True),
    Fact("docs.top_tags", "top_list", _docs_top_tags, rank=85, private=True),
    Fact("storage.growth", "big_number", _storage_growth, rank=90),
    Fact("system.containers", "big_number", _system_containers, rank=100),
    Fact("system.oldest_container", "big_number", _system_oldest_container, rank=105),
    Fact("network.total", "big_number", _network_total, rank=110),
    Fact("network.by_service", "comparison", _network_by_service, rank=120),
    Fact("dns.blocked_total", "big_number", _dns_blocked_total, rank=130),
    Fact("dns.top_blocked", "top_list", _dns_top_blocked, rank=140, private=True),
    Fact("activity.streak", "streak", _activity_streak, rank=150),
    Fact("activity.by_day", "heatmap", _activity_heatmap, rank=160),
]
