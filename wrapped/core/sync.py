"""Sync orchestration: run configured connectors, store their events."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from wrapped.connectors import all_connectors
from wrapped.connectors.base import missing_required
from wrapped.core.config import AppConfig
from wrapped.core.events import EventStore

log = logging.getLogger("wrapped.sync")

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class SyncReport:
    """What happened to each connector in one sync run.

    Attributes:
        counts: Events stored, per connector instance that succeeded.
        errors: Human-readable failure reason, per connector that didn't.
    """

    counts: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when every configured connector synced without error."""
        return not self.errors

    @property
    def total(self) -> int:
        """Total events stored across all connectors that succeeded."""
        return sum(self.counts.values())


def sync_all(config: AppConfig, store: EventStore, now: datetime | None = None) -> SyncReport:
    """Collect new events from every configured connector.

    Incremental: each connector's window starts at its last successful sync
    (the epoch on first run) and ends at ``now``. The configured instance
    name becomes ``Event.source``, so two instances of the same plugin stay
    distinct. Applies the ``retention_days`` purge afterwards.

    Connectors are isolated: a broken one is recorded in
    :attr:`SyncReport.errors` and the rest still sync. A failed connector
    stores nothing and its last-sync marker is left alone, so the next run
    retries the same window rather than skipping over it. Callers decide how
    loud to be — the CLI exits non-zero, the scheduler logs and carries on
    with whatever data it has.

    Args:
        config: Parsed application config.
        store: Open event store.
        now: Window end; defaults to the current time (injectable for tests).

    Returns:
        A :class:`SyncReport` of per-connector counts and errors.
    """
    now = now or datetime.now(tz=UTC)
    plugins = all_connectors()
    counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    for entry in config.connectors:
        try:
            counts[entry.name] = _sync_one(entry, plugins, store, now)
        except Exception as exc:  # noqa: BLE001 — one bad connector must not sink the rest
            errors[entry.name] = str(exc) or exc.__class__.__name__
            log.warning("connector %r failed: %s", entry.name, errors[entry.name])

    if config.retention_days is not None:
        store.purge(before=now - timedelta(days=config.retention_days))
    return SyncReport(counts=counts, errors=errors)


def _sync_one(entry, plugins, store: EventStore, now: datetime) -> int:
    """Collect and store one connector's window. Raises on any failure."""
    plugin = plugins.get(entry.type)
    if plugin is None:
        raise ValueError(f"unknown type {entry.type!r} (available: {', '.join(sorted(plugins))})")
    missing = missing_required(plugin.schema, entry.cfg)
    if missing:
        raise ValueError(f"missing config keys {missing}")

    since = store.last_sync(entry.name) or _EPOCH

    def renamed(events):
        for e in events:
            e.source = entry.name
            yield e

    # add_events materialises the generator before inserting, so a connector
    # that raises mid-collect writes nothing at all — no half-synced windows.
    n = store.add_events(renamed(plugin.collect(entry.cfg, since, now)))
    store.set_last_sync(entry.name, now)
    return n
