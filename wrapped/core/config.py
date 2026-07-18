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

import re
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
class EmailConfig:
    """The user's own SMTP server — never a third-party mail service."""

    smtp_host: str
    from_addr: str
    to: str
    smtp_port: int = 587
    username: str | None = None
    password: str | None = None
    starttls: bool = True


@dataclass
class ScheduleConfig:
    """Which scheduled jobs run when ``wrapped schedule`` is active."""

    monthly_recap: bool = False
    on_this_day: bool = False
    hour: int = 6  # local hour both jobs fire at


@dataclass
class AppConfig:
    """Parsed and validated application configuration."""

    timezone: ZoneInfo
    database: Path
    retention_days: int | None
    connectors: list[ConnectorEntry]
    schedule: ScheduleConfig
    email: EmailConfig | None


_MANAGED_HEADER = (
    "# Homelab Wrapped configuration.\n"
    "# Editable by hand or from the web UI's Settings page (which rewrites\n"
    "# this file and does not preserve comments).\n"
    "# All options: https://github.com/smbdev/homelab-wrapped/blob/main/config.example.yaml\n"
)


def _rewrite(path: str | Path, raw: dict[str, Any]) -> None:
    Path(path).write_text(_MANAGED_HEADER + yaml.safe_dump(raw, sort_keys=False))


def add_connector(path: str | Path, name: str, type_: str, cfg: dict[str, Any]) -> None:
    """Add a connector instance to config.yaml (used by the Settings page).

    Args:
        path: The config file (must exist).
        name: Instance name — becomes ``Event.source``.
        type_: Plugin id, e.g. ``"jellyfin"``.
        cfg: The plugin-specific keys, already validated by the caller.

    Raises:
        ValueError: On an invalid name or a duplicate instance.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError(f"instance name {name!r} must be letters, digits, - or _")
    raw = yaml.safe_load(Path(path).read_text()) or {}
    connectors = raw.setdefault("connectors", {}) or {}
    if name in connectors:
        raise ValueError(f"a connector called {name!r} already exists")
    connectors[name] = {"type": type_, **cfg}
    raw["connectors"] = connectors
    _rewrite(path, raw)


def remove_connector(path: str | Path, name: str) -> None:
    """Remove a connector instance from config.yaml.

    Raises:
        ValueError: If no such instance exists.
    """
    raw = yaml.safe_load(Path(path).read_text()) or {}
    connectors = raw.get("connectors") or {}
    if name not in connectors:
        raise ValueError(f"no connector called {name!r}")
    del connectors[name]
    raw["connectors"] = connectors
    _rewrite(path, raw)


def create_starter_config(path: str | Path) -> AppConfig:
    """Write the commented example config to ``path`` and load it.

    Called on first ``wrapped serve`` when no config exists yet, so a fresh
    Docker volume boots straight into a working (if empty) app instead of a
    crash loop — the user edits the generated file to add their services.
    """
    from importlib import resources

    packaged = resources.files("wrapped").joinpath("config.example.yaml")
    if packaged.is_file():
        text = packaged.read_text()
    else:  # editable install / repo checkout: the example lives at the repo root
        text = (Path(__file__).parent.parent.parent / "config.example.yaml").read_text()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return load_config(path)


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

    sched_raw = raw.get("schedule") or {}
    if not isinstance(sched_raw, dict):
        raise ValueError(f"{path}: schedule must be a mapping")
    schedule = ScheduleConfig(
        monthly_recap=bool(sched_raw.get("monthly_recap", False)),
        on_this_day=bool(sched_raw.get("on_this_day", False)),
        hour=int(sched_raw.get("hour", 6)),
    )

    email = None
    email_raw = raw.get("email")
    if email_raw is not None:
        if not isinstance(email_raw, dict):
            raise ValueError(f"{path}: email must be a mapping")
        missing = [k for k in ("smtp_host", "from", "to") if not email_raw.get(k)]
        if missing:
            raise ValueError(f"{path}: email block missing required keys {missing}")
        email = EmailConfig(
            smtp_host=str(email_raw["smtp_host"]),
            from_addr=str(email_raw["from"]),
            to=str(email_raw["to"]),
            smtp_port=int(email_raw.get("smtp_port", 587)),
            username=email_raw.get("username"),
            password=email_raw.get("password"),
            starttls=bool(email_raw.get("starttls", True)),
        )

    database = Path(raw.get("database", "data/events.db"))
    if not database.is_absolute():
        # Relative to the config file, not the process cwd — so the web UI's
        # background jobs and the CLI agree on where the data lives.
        database = Path(path).parent / database

    return AppConfig(
        timezone=tz,
        database=database,
        retention_days=retention,
        connectors=connectors,
        schedule=schedule,
        email=email,
    )
