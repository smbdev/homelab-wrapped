"""config.yaml loading and validation.

One file drives everything:

.. code-block:: yaml

    timezone: Europe/Berlin      # optional, default UTC
    database: data/events.db     # optional, default data/events.db
    retention_days: 730          # optional, default keep forever
    connectors:
      my_media:                  # instance name — becomes Event.source
        type: generic_csv        # which plugin
        path: /data/media.csv    # plugin-specific keys per its schema
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml


@dataclass
class ConnectorEntry:
    """One configured connector instance from config.yaml."""

    name: str
    type: str
    cfg: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppConfig:
    """Parsed and validated application configuration."""

    timezone: ZoneInfo
    database: Path
    retention_days: int | None
    connectors: list[ConnectorEntry]


def load_config(path: str | Path) -> AppConfig:
    """Load and validate config.yaml.

    Args:
        path: Path to the YAML config file.

    Returns:
        The parsed :class:`AppConfig`.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: On malformed YAML or invalid values (unknown timezone,
            non-mapping connector blocks, missing connector ``type``).
    """
    raw = yaml.safe_load(Path(path).read_text())
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top level must be a mapping, got {type(raw).__name__}")

    try:
        tz = ZoneInfo(raw.get("timezone", "UTC"))
    except KeyError as exc:
        raise ValueError(f"{path}: unknown timezone {raw.get('timezone')!r}") from exc

    retention = raw.get("retention_days")
    if retention is not None and (not isinstance(retention, int) or retention <= 0):
        raise ValueError(f"{path}: retention_days must be a positive integer, got {retention!r}")

    connectors = []
    for name, block in (raw.get("connectors") or {}).items():
        if not isinstance(block, dict) or "type" not in block:
            raise ValueError(f"{path}: connector {name!r} needs a mapping with a 'type' key")
        cfg = {k: v for k, v in block.items() if k != "type"}
        connectors.append(ConnectorEntry(name=str(name), type=str(block["type"]), cfg=cfg))

    return AppConfig(
        timezone=tz,
        database=Path(raw.get("database", "data/events.db")),
        retention_days=retention,
        connectors=connectors,
    )
