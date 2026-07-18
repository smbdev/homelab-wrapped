"""Pi-hole connector — reads the FTL long-term SQLite database.

Point it at ``pihole-FTL.db`` (in Pi-hole's ``/etc/pihole`` directory,
mounted read-only into this container). The file is opened read-only via a
SQLite URI — nothing is written, no network, no API token needed. FTL keeps
a year of query history by default (``MAXDBDAYS``), which is exactly a
recap's window.

Queries are aggregated per day before storage: one ``dns.query`` and one
``dns.blocked`` event per day carrying counts, plus per-domain daily events
for the top blocked domains so the "most blocked" list works.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from wrapped.connectors.base import Config, ConfigField, ConnectionResult, FactSpec
from wrapped.core.events import Event

# FTL status codes that mean "we blocked this" (gravity, regex, exact
# blacklist, external NXDOMAIN/NULL/CNAME, database, special domain).
BLOCKED_STATUSES = (1, 4, 5, 6, 7, 8, 9, 10, 11, 15, 16)
_TOP_DOMAINS_PER_DAY = 25  # ponytail: caps event volume; a year ≈ 9k rows max


class PiholeConnector:
    """Aggregates DNS query history from Pi-hole's FTL database."""

    id = "pihole"
    name = "Pi-hole"
    schema = [
        ConfigField("db_path", "Path to Pi-hole's pihole-FTL.db (mounted read-only)"),
    ]

    def test(self, cfg: Config) -> ConnectionResult:
        """Open the database read-only and count logged queries."""
        try:
            with self._connect(cfg["db_path"]) as db:
                (count,) = db.execute("SELECT COUNT(*) FROM queries").fetchone()
        except sqlite3.Error as exc:
            return ConnectionResult(False, f"Could not read {cfg.get('db_path')}: {exc}")
        return ConnectionResult(True, f"OK — {count:,} DNS queries logged")

    def collect(self, cfg: Config, since: datetime, until: datetime) -> Iterator[Event]:
        """Yield per-day aggregates for queries, blocks, and top blocked domains."""
        with self._connect(cfg["db_path"]) as db:
            days: dict[str, dict] = {}
            rows = db.execute(
                "SELECT timestamp, status, domain FROM queries"
                " WHERE timestamp >= ? AND timestamp < ?",
                (int(since.timestamp()), int(until.timestamp())),
            )
            for ts_epoch, status, domain in rows:
                day = datetime.fromtimestamp(ts_epoch, tz=UTC).date().isoformat()
                bucket = days.setdefault(day, {"total": 0, "blocked": 0, "domains": Counter()})
                bucket["total"] += 1
                if status in BLOCKED_STATUSES:
                    bucket["blocked"] += 1
                    bucket["domains"][domain] += 1
        for day, bucket in sorted(days.items()):
            noon = datetime.fromisoformat(day).replace(hour=12, tzinfo=UTC)
            yield Event(
                source=self.id,
                kind="dns.query",
                ts=noon,
                value=float(bucket["total"]),
            )
            if bucket["blocked"]:
                yield Event(
                    source=self.id,
                    kind="dns.blocked",
                    ts=noon,
                    value=float(bucket["blocked"]),
                )
            for domain, n in bucket["domains"].most_common(_TOP_DOMAINS_PER_DAY):
                yield Event(
                    source=self.id,
                    kind="dns.blocked_domain",
                    ts=noon,
                    entity=domain,
                    entity_group=domain,
                    value=float(n),
                )

    def facts(self) -> list[FactSpec]:
        return [
            FactSpec("dns.blocked_total", "Ads and trackers blocked"),
            FactSpec("dns.top_blocked", "Most-blocked domains"),
        ]

    @staticmethod
    def _connect(db_path: str) -> sqlite3.Connection:
        path = Path(db_path).absolute()
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


CONNECTOR = PiholeConnector()
