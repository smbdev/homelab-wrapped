"""Normalised event storage and aggregation over SQLite.

Everything Homelab Wrapped knows lives in one ``events`` table; every recap
fact is computed from windowed queries over it. Timestamps are stored as
ISO-8601 UTC text and returned as aware datetimes.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    ts TEXT NOT NULL,
    entity TEXT,
    entity_group TEXT,
    value REAL DEFAULT 1,
    meta TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_source_kind ON events(source, kind);

CREATE TABLE IF NOT EXISTS sync_state (
    source TEXT PRIMARY KEY,
    last_sync TEXT
);
"""


@dataclass
class Event:
    """One normalised thing that happened, from any connector.

    Attributes:
        source: Connector id, e.g. ``"jellyfin"``.
        kind: Dotted event type, e.g. ``"media.play"`` or ``"photo.taken"``.
        ts: When it happened. Must be timezone-aware.
        entity: The specific thing, e.g. ``"The Bear S03E01"``.
        entity_group: Its grouping, e.g. ``"The Bear"``.
        value: Magnitude — duration in minutes, bytes, or a plain count of 1.
        meta: Connector-specific extras, stored as JSON.
    """

    source: str
    kind: str
    ts: datetime
    entity: str | None = None
    entity_group: str | None = None
    value: float = 1.0
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError(f"Event.ts must be timezone-aware, got naive {self.ts!r}")


def _iso(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat()


class EventStore:
    """SQLite-backed store for normalised events and connector sync state.

    Args:
        path: Database file path, or ``":memory:"`` for tests.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._db = sqlite3.connect(str(path))
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        """Close the underlying database connection."""
        self._db.close()

    # -- writing ---------------------------------------------------------

    def add_events(self, events: Iterable[Event]) -> int:
        """Insert events; returns how many were written."""
        rows = [
            (
                e.source,
                e.kind,
                _iso(e.ts),
                e.entity,
                e.entity_group,
                e.value,
                json.dumps(e.meta) if e.meta else None,
            )
            for e in events
        ]
        with self._db:
            self._db.executemany(
                "INSERT INTO events (source, kind, ts, entity, entity_group, value, meta)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def purge(self, before: datetime | None = None, source: str | None = None) -> int:
        """Delete events, optionally only those before a cutoff or from one source.

        With no arguments this wipes the whole cache (the ``wrapped purge``
        command); with ``before`` it implements retention. Sync state for a
        fully-purged source is reset so the next sync starts from scratch.

        Returns:
            Number of events deleted.
        """
        clauses, params = [], []
        if before is not None:
            clauses.append("ts < ?")
            params.append(_iso(before))
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._db:
            cur = self._db.execute(f"DELETE FROM events{where}", params)  # noqa: S608
            if before is None:
                if source is None:
                    self._db.execute("DELETE FROM sync_state")
                else:
                    self._db.execute("DELETE FROM sync_state WHERE source = ?", (source,))
        return cur.rowcount

    # -- sync state ------------------------------------------------------

    def last_sync(self, source: str) -> datetime | None:
        """Return the last successful sync time for a connector, if any."""
        row = self._db.execute(
            "SELECT last_sync FROM sync_state WHERE source = ?", (source,)
        ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def set_last_sync(self, source: str, ts: datetime) -> None:
        """Record a successful sync for a connector."""
        with self._db:
            self._db.execute(
                "INSERT INTO sync_state (source, last_sync) VALUES (?, ?)"
                " ON CONFLICT(source) DO UPDATE SET last_sync = excluded.last_sync",
                (source, _iso(ts)),
            )

    # -- reading ---------------------------------------------------------

    def events(
        self,
        since: datetime,
        until: datetime,
        kind: str | None = None,
        source: str | None = None,
    ) -> Iterator[Event]:
        """Yield events with ``since <= ts < until``, newest last.

        Args:
            since: Inclusive window start (aware).
            until: Exclusive window end (aware).
            kind: Optional exact kind filter, or a prefix ending in ``.*``
                (``"media.*"`` matches ``media.play`` and ``media.listen``).
            source: Optional connector id filter.
        """
        clauses, params = self._window(since, until, kind, source)
        rows = self._db.execute(
            f"SELECT source, kind, ts, entity, entity_group, value, meta FROM events"
            f" WHERE {clauses} ORDER BY ts",  # noqa: S608
            params,
        )
        for source_, kind_, ts, entity, group, value, meta in rows:
            yield Event(
                source=source_,
                kind=kind_,
                ts=datetime.fromisoformat(ts),
                entity=entity,
                entity_group=group,
                value=value,
                meta=json.loads(meta) if meta else {},
            )

    def totals(
        self,
        since: datetime,
        until: datetime,
        kind: str | None = None,
        source: str | None = None,
    ) -> tuple[int, float]:
        """Return ``(event_count, value_sum)`` for a window."""
        clauses, params = self._window(since, until, kind, source)
        row = self._db.execute(
            f"SELECT COUNT(*), COALESCE(SUM(value), 0) FROM events WHERE {clauses}",  # noqa: S608
            params,
        ).fetchone()
        return row[0], row[1]

    def top(
        self,
        since: datetime,
        until: datetime,
        kind: str | None = None,
        source: str | None = None,
        group: bool = True,
        by: str = "count",
        limit: int = 5,
    ) -> list[tuple[str, int, float]]:
        """Rank entities in a window.

        Args:
            group: Rank by ``entity_group`` (True) or individual ``entity``.
            by: ``"count"`` or ``"value"`` — what to order by, descending.
            limit: Max rows returned.

        Returns:
            List of ``(label, count, value_sum)`` tuples, best first.
        """
        if by not in ("count", "value"):
            raise ValueError(f"by must be 'count' or 'value', got {by!r}")
        col = "entity_group" if group else "entity"
        order = "n DESC" if by == "count" else "v DESC"
        clauses, params = self._window(since, until, kind, source)
        rows = self._db.execute(
            f"SELECT {col}, COUNT(*) AS n, COALESCE(SUM(value), 0) AS v FROM events"  # noqa: S608
            f" WHERE {clauses} AND {col} IS NOT NULL"
            f" GROUP BY {col} ORDER BY {order} LIMIT ?",
            (*params, limit),
        )
        return [(label, n, v) for label, n, v in rows]

    def by_day(
        self,
        since: datetime,
        until: datetime,
        tz: Any,
        kind: str | None = None,
        source: str | None = None,
    ) -> dict[date, float]:
        """Sum event values per local calendar day (heatmaps, streaks, busiest day).

        Grouping happens in Python because day boundaries depend on the
        user's timezone, which SQLite can't resolve.

        Args:
            tz: The user's tzinfo; days are bucketed in this zone.
        """
        # ponytail: O(n) over window rows — fine at homelab scale, push to SQL if it isn't
        days: dict[date, float] = {}
        clauses, params = self._window(since, until, kind, source)
        rows = self._db.execute(
            f"SELECT ts, value FROM events WHERE {clauses}",  # noqa: S608
            params,
        )
        for ts, value in rows:
            d = datetime.fromisoformat(ts).astimezone(tz).date()
            days[d] = days.get(d, 0.0) + value
        return days

    @staticmethod
    def _window(
        since: datetime,
        until: datetime,
        kind: str | None,
        source: str | None,
    ) -> tuple[str, list[str]]:
        clauses = ["ts >= ?", "ts < ?"]
        params = [_iso(since), _iso(until)]
        if kind is not None:
            if kind.endswith(".*"):
                clauses.append("kind LIKE ?")
                params.append(kind[:-1] + "%")
            else:
                clauses.append("kind = ?")
                params.append(kind)
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        return " AND ".join(clauses), params


def longest_streak(days: dict[date, float]) -> tuple[int, date | None]:
    """Find the longest run of consecutive active days.

    Args:
        days: Per-day values from :meth:`EventStore.by_day`.

    Returns:
        ``(length, start_date)`` of the longest streak; ``(0, None)`` if empty.
    """
    best, best_start = 0, None
    run, run_start = 0, None
    prev: date | None = None
    for d in sorted(days):
        if prev is not None and (d - prev).days == 1:
            run += 1
        else:
            run, run_start = 1, d
        if run > best:
            best, best_start = run, run_start
        prev = d
    return best, best_start


def busiest_day(days: dict[date, float]) -> tuple[date, float] | None:
    """Return the ``(day, value)`` with the highest value, or None if empty."""
    if not days:
        return None
    d = max(days, key=lambda k: days[k])
    return d, days[d]
