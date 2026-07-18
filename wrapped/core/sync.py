"""Sync orchestration: run configured connectors, store their events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from wrapped.connectors import all_connectors
from wrapped.connectors.base import missing_required
from wrapped.core.config import AppConfig
from wrapped.core.events import EventStore

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def sync_all(config: AppConfig, store: EventStore, now: datetime | None = None) -> dict[str, int]:
    """Collect new events from every configured connector.

    Incremental: each connector's window starts at its last successful sync
    (the epoch on first run) and ends at ``now``. The configured instance
    name becomes ``Event.source``, so two instances of the same plugin stay
    distinct. Applies the ``retention_days`` purge afterwards.

    Args:
        config: Parsed application config.
        store: Open event store.
        now: Window end; defaults to the current time (injectable for tests).

    Returns:
        Mapping of connector instance name to number of events stored.

    Raises:
        ValueError: If a config block names an unknown connector type or is
            missing required keys.
    """
    # ponytail: one failing connector aborts the whole sync — loud beats
    # half-synced; add per-connector error isolation if it bites in practice
    now = now or datetime.now(tz=UTC)
    plugins = all_connectors()
    counts: dict[str, int] = {}
    for entry in config.connectors:
        plugin = plugins.get(entry.type)
        if plugin is None:
            raise ValueError(
                f"connector {entry.name!r}: unknown type {entry.type!r}"
                f" (available: {', '.join(sorted(plugins))})"
            )
        missing = missing_required(plugin.schema, entry.cfg)
        if missing:
            raise ValueError(f"connector {entry.name!r}: missing config keys {missing}")

        since = store.last_sync(entry.name) or _EPOCH

        def renamed(events, name=entry.name):
            for e in events:
                e.source = name
                yield e

        counts[entry.name] = store.add_events(renamed(plugin.collect(entry.cfg, since, now)))
        store.set_last_sync(entry.name, now)

    if config.retention_days is not None:
        store.purge(before=now - timedelta(days=config.retention_days))
    return counts
