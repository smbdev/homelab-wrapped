"""Story builder: turn windowed facts into the JSON the player renders.

A story spec (§5 of the spec) is plain JSON — a period, and a list of cards
each naming a presentation template. Specs are saved to disk so past recaps
stay browsable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Any

from wrapped.core.events import EventStore
from wrapped.core.periods import month_window, on_this_day_windows, year_window
from wrapped.facts import FACTS, FactContext, plural

# Human nouns for event kinds, used in on-this-day summaries.
_KIND_NOUNS = {
    "media.play": ("thing watched", "things watched"),
    "media.listen": ("listen", "listens"),
    "photo.taken": ("photo", "photos"),
    "doc.added": ("document", "documents"),
}


@dataclass(frozen=True)
class Period:
    """A recap period: a year, a month, or an on-this-day calendar day."""

    type: str  # "year" | "month" | "day"
    year: int | None = None
    month: int | None = None
    day: int | None = None

    @property
    def id(self) -> str:
        """Filesystem-safe identifier, e.g. ``2026``, ``2026-03``, ``day-07-18``."""
        if self.type == "year":
            return str(self.year)
        if self.type == "month":
            return f"{self.year}-{self.month:02d}"
        return f"day-{self.month:02d}-{self.day:02d}"

    @property
    def label(self) -> str:
        """Human title, e.g. ``Your 2026``, ``March 2026``, ``On this day``."""
        if self.type == "year":
            return f"Your {self.year}"
        if self.type == "month":
            return f"{datetime(self.year, self.month, 1):%B %Y}"
        return f"On this day, {datetime(2000, self.month, self.day):%-d %B}"


def build_story(
    store: EventStore, period: Period, tz: tzinfo, now: datetime | None = None
) -> dict[str, Any]:
    """Compute every applicable fact for a period and assemble the story spec.

    Facts with no data return no card — an empty homelab yields an empty
    ``cards`` list, never an error.

    Args:
        store: Open event store.
        period: What to recap.
        tz: User timezone for day bucketing.
        now: Injectable clock for deterministic tests.

    Returns:
        The story spec dict (see §5 of the build spec).
    """
    now = now or datetime.now(tz=UTC)
    if period.type == "day":
        cards = _on_this_day_cards(store, period, tz, now)
    else:
        if period.type == "year":
            since, until = year_window(period.year, tz)
        else:
            since, until = month_window(period.year, period.month, tz)
        ctx = FactContext(store=store, since=since, until=until, tz=tz)
        cards = []
        # Ascending rank, not list order — see FACTS for the shape of the arc.
        for fact in sorted(FACTS, key=lambda f: f.rank):
            card = fact.compute(ctx)
            if card is not None:
                cards.append(
                    {"template": fact.template, "fact": fact.id, "private": fact.private, **card}
                )
    return {
        "version": 1,
        "period": {"type": period.type, "id": period.id, "label": period.label},
        "generated_at": now.isoformat(),
        "cards": cards,
    }


def _on_this_day_cards(
    store: EventStore, period: Period, tz: tzinfo, now: datetime
) -> list[dict[str, Any]]:
    """One card per past year that had activity on this calendar day."""
    first = store.first_event_ts()
    if first is None:
        return []
    windows = on_this_day_windows(
        period.month, period.day, tz, first.astimezone(tz).year, now.astimezone(tz).year - 1
    )
    cards = []
    for year, since, until in reversed(windows):  # most recent year first
        kinds = store.count_by_kind(since, until)
        if not kinds:
            continue
        years_ago = now.astimezone(tz).year - year
        bits = []
        for kind, count in sorted(kinds.items(), key=lambda kv: -kv[1]):
            noun = _KIND_NOUNS.get(kind, (kind.rsplit(".", 1)[-1], kind.rsplit(".", 1)[-1] + "s"))
            bits.append(plural(count, noun[0], noun[1]))
        cards.append(
            {
                "template": "big_number",
                "fact": "on_this_day.year",
                "private": False,
                "value": sum(kinds.values()),
                "headline": f"{plural(years_ago, 'year')} ago today",
                "sub": ", ".join(bits).capitalize(),
                "year": year,
            }
        )
    return cards


def save_story(stories_dir: str | Path, story: dict[str, Any]) -> Path:
    """Write a story spec to ``<stories_dir>/<period id>.json`` and return the path."""
    directory = Path(stories_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{story['period']['id']}.json"
    path.write_text(json.dumps(story, indent=2, ensure_ascii=False) + "\n")
    return path


def load_story(stories_dir: str | Path, period_id: str) -> dict[str, Any]:
    """Load a previously saved story spec by its period id."""
    return json.loads((Path(stories_dir) / f"{period_id}.json").read_text())


def list_stories(stories_dir: str | Path) -> list[str]:
    """Return saved period ids, newest first (years/months sort naturally)."""
    directory = Path(stories_dir)
    if not directory.is_dir():
        return []
    return sorted((p.stem for p in directory.glob("*.json")), reverse=True)
