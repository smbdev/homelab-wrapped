"""Sync orchestration: per-connector isolation and reporting."""

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from wrapped.core.config import AppConfig, ConnectorEntry, ScheduleConfig
from wrapped.core.events import EventStore
from wrapped.core.sync import sync_all

NOW = datetime(2026, 6, 1, tzinfo=UTC)


@pytest.fixture
def store():
    s = EventStore()
    yield s
    s.close()


def config(tmp_path, *entries, retention_days=None):
    return AppConfig(
        timezone=ZoneInfo("UTC"),
        database=Path(tmp_path) / "e.db",
        retention_days=retention_days,
        connectors=list(entries),
        schedule=ScheduleConfig(),
        email=None,
    )


def csv_entry(name, tmp_path, rows=2):
    path = Path(tmp_path) / f"{name}.csv"
    path.write_text(
        "ts,kind,entity,entity_group,value\n"
        + "".join(
            f"2026-03-0{i + 1}T20:00:00+00:00,media.play,E{i},The Bear,50\n" for i in range(rows)
        )
    )
    return ConnectorEntry(name=name, type="generic_csv", cfg={"path": str(path)})


def broken_entry(name="bad"):
    return ConnectorEntry(name=name, type="generic_csv", cfg={"path": "/nope/absent.csv"})


def test_healthy_connectors_report_counts(store, tmp_path):
    report = sync_all(config(tmp_path, csv_entry("a", tmp_path, rows=3)), store, now=NOW)
    assert report.ok
    assert report.counts == {"a": 3}
    assert report.total == 3


def test_one_broken_connector_does_not_stop_the_others(store, tmp_path):
    cfg = config(tmp_path, csv_entry("good", tmp_path, rows=2), broken_entry())
    report = sync_all(cfg, store, now=NOW)

    assert report.counts == {"good": 2}, "the healthy connector still synced"
    assert not report.ok
    assert "bad" in report.errors
    assert report.total == 2


def test_unknown_type_is_an_error_not_a_crash(store, tmp_path):
    cfg = config(tmp_path, ConnectorEntry(name="huh", type="nosuchthing", cfg={}))
    report = sync_all(cfg, store, now=NOW)
    assert not report.ok
    assert "nosuchthing" in report.errors["huh"]


def test_missing_required_keys_is_an_error_not_a_crash(store, tmp_path):
    cfg = config(tmp_path, ConnectorEntry(name="nopath", type="generic_csv", cfg={}))
    report = sync_all(cfg, store, now=NOW)
    assert not report.ok
    assert "path" in report.errors["nopath"]


def test_failed_connector_stores_nothing_and_retries_next_run(store, tmp_path):
    """A failure must not advance last_sync, or its window is skipped forever."""
    entry = broken_entry()
    sync_all(config(tmp_path, entry), store, now=NOW)

    assert store.last_sync("bad") is None
    assert list(store.events(datetime(2020, 1, 1, tzinfo=UTC), NOW)) == []


def test_healthy_connector_advances_last_sync(store, tmp_path):
    sync_all(config(tmp_path, csv_entry("a", tmp_path)), store, now=NOW)
    assert store.last_sync("a") == NOW


def test_no_connectors_is_a_clean_empty_report(store, tmp_path):
    report = sync_all(config(tmp_path), store, now=NOW)
    assert report.ok
    assert report.counts == {}
    assert report.total == 0
