"""Jellyfin connector — reads the Playback Reporting plugin's SQLite database.

Point it at ``playback_reporting.db`` (in Jellyfin's ``data`` directory, with
the Playback Reporting plugin installed). The file is opened read-only via a
SQLite URI, so nothing is ever written and no network is involved at all.

Episode names arrive as ``"Show - s01e05 - Title"``; the show becomes the
event's ``entity_group`` so top-show rankings work out of the box.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from wrapped.connectors.base import Config, ConfigField, ConnectionResult, FactSpec
from wrapped.core.events import Event


class JellyfinConnector:
    """Reads playback history from the Playback Reporting plugin database."""

    id = "jellyfin"
    name = "Jellyfin"
    schema = [
        ConfigField("db_path", "Path to the Playback Reporting plugin's playback_reporting.db"),
        ConfigField(
            "timezone",
            "IANA timezone the Jellyfin server logs in (default: UTC)",
            required=False,
        ),
        ConfigField("user_id", "Only include plays by this Jellyfin user id", required=False),
    ]

    def test(self, cfg: Config) -> ConnectionResult:
        """Open the database read-only and count playback rows."""
        try:
            with self._connect(cfg["db_path"]) as db:
                (count,) = db.execute("SELECT COUNT(*) FROM PlaybackActivity").fetchone()
        except sqlite3.Error as exc:
            return ConnectionResult(False, f"Could not read {cfg.get('db_path')}: {exc}")
        return ConnectionResult(True, f"OK — {count} plays recorded")

    def collect(self, cfg: Config, since: datetime, until: datetime) -> Iterator[Event]:
        """Yield one ``media.play`` event per playback row in the window.

        ``value`` is the play duration in minutes. Rows with unparseable
        dates are skipped rather than raised: Playback Reporting data is
        append-only history the user can't fix.
        """
        tz = ZoneInfo(cfg.get("timezone") or "UTC")
        user_id = cfg.get("user_id")
        with self._connect(cfg["db_path"]) as db:
            rows = db.execute(
                "SELECT DateCreated, ItemName, ItemType, PlayDuration, UserId"
                " FROM PlaybackActivity ORDER BY DateCreated"
            )
            for date_created, item_name, item_type, duration, row_user in rows:
                if user_id and row_user != user_id:
                    continue
                try:
                    ts = datetime.fromisoformat(str(date_created)).replace(tzinfo=tz)
                except ValueError:
                    continue
                if not (since <= ts < until):
                    continue
                yield Event(
                    source=self.id,
                    kind="media.play",
                    ts=ts,
                    entity=item_name,
                    entity_group=_group(item_name, item_type),
                    value=float(duration or 0) / 60.0,
                    meta={"item_type": item_type},
                )

    def facts(self) -> list[FactSpec]:
        """Feeds the media facts."""
        return [
            FactSpec("media.total_hours", "Total hours watched"),
            FactSpec("media.top_shows", "Most-watched shows"),
        ]

    @staticmethod
    def _connect(db_path: str) -> sqlite3.Connection:
        # Read-only URI: the least-privileged access SQLite supports (§1.2).
        path = Path(db_path).absolute()
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _group(item_name: str | None, item_type: str | None) -> str | None:
    """Extract the show from ``"Show - s01e05 - Title"``; movies group as themselves."""
    if not item_name:
        return None
    if item_type == "Episode" and " - " in item_name:
        return item_name.split(" - ")[0]
    return item_name


CONNECTOR = JellyfinConnector()
