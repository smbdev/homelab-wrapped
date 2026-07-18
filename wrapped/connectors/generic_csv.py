"""Generic CSV/JSON connector — the reference implementation.

Reads events from a local CSV file (with a header row) or a JSON file (a list
of objects). Columns/keys: ``ts`` (ISO-8601, required), ``kind`` (required),
``entity``, ``entity_group``, ``value``. Use it to wrap any service we don't
have a connector for yet: export your data to CSV, point this at it.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from wrapped.connectors.base import Config, ConfigField, ConnectionResult, FactSpec
from wrapped.core.events import Event


class GenericCsvConnector:
    """Reads normalised events from a local CSV or JSON file."""

    id = "generic_csv"
    name = "Generic CSV/JSON"
    schema = [
        ConfigField("path", "Path to a .csv (with header row) or .json (list of objects) file"),
        ConfigField(
            "timezone",
            "IANA timezone applied to naive timestamps (default: UTC)",
            required=False,
        ),
    ]

    def test(self, cfg: Config) -> ConnectionResult:
        """Check the file exists and its rows parse; reports the row count."""
        try:
            forever = (datetime.min.replace(tzinfo=UTC), datetime.max.replace(tzinfo=UTC))
            count = sum(1 for _ in self.collect(cfg, *forever))
        except FileNotFoundError:
            return ConnectionResult(False, f"File not found: {cfg.get('path')}")
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            return ConnectionResult(False, f"Could not parse {cfg.get('path')}: {exc}")
        return ConnectionResult(True, f"OK — {count} events in {cfg.get('path')}")

    def collect(self, cfg: Config, since: datetime, until: datetime) -> Iterator[Event]:
        """Yield events from the file whose timestamps fall in the window.

        Naive timestamps are localised to the configured ``timezone`` (UTC by
        default). Rows without ``ts`` or ``kind`` raise ``ValueError`` — bad
        data should be loud, not silently dropped.
        """
        path = Path(cfg["path"])
        tz = ZoneInfo(cfg.get("timezone") or "UTC")
        if path.suffix.lower() == ".json":
            rows = json.loads(path.read_text())
        else:
            rows = csv.DictReader(path.read_text().splitlines())
        for i, row in enumerate(rows, start=1):
            ts_raw, kind = row.get("ts"), row.get("kind")
            if not ts_raw or not kind:
                raise ValueError(f"row {i}: 'ts' and 'kind' are required")
            ts = datetime.fromisoformat(str(ts_raw))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=tz)
            if not (since <= ts < until):
                continue
            yield Event(
                source=self.id,
                kind=str(kind),
                ts=ts,
                entity=row.get("entity") or None,
                entity_group=row.get("entity_group") or None,
                value=float(row.get("value") or 1),
            )

    def facts(self) -> list[FactSpec]:
        """Generic files can feed any fact; declarations arrive with M2 facts."""
        return []


CONNECTOR = GenericCsvConnector()
