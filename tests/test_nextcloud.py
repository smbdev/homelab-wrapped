"""Nextcloud connector: type mapping, windowing, pagination, snapshot, facts."""

from datetime import UTC, datetime

import pytest

import wrapped.connectors.nextcloud as nc
from wrapped.core.events import Event, EventStore
from wrapped.facts import FactContext, _files_top_folders, _files_total, _storage_growth

SINCE = datetime(2026, 1, 1, tzinfo=UTC)
UNTIL = datetime(2027, 1, 1, tzinfo=UTC)
CFG = {"url": "http://nextcloud.local", "username": "scott", "app_password": "pw"}


def _activity(aid, type_, dt, path):
    return {"activity_id": aid, "type": type_, "datetime": dt, "object_name": path}


PAGE1 = {
    "ocs": {
        "data": [
            _activity(30, "file_created", "2026-06-01T10:00:00+00:00", "/Photos/cat.jpg"),
            _activity(29, "shared", "2026-05-01T10:00:00+00:00", "/Photos/cat.jpg"),
            _activity(28, "file_deleted", "2026-04-01T10:00:00+00:00", "/tmp.txt"),
        ]
    }
}
PAGE2 = {
    "ocs": {
        "data": [
            _activity(27, "file_created", "2026-03-01T10:00:00+00:00", "/notes.md"),
            _activity(26, "file_created", "2025-01-01T10:00:00+00:00", "/old.txt"),
        ]
    }
}
QUOTA = {"ocs": {"data": {"quota": {"used": 5_000_000_000}}}}


@pytest.fixture
def fake_api(monkeypatch):
    monkeypatch.setattr(nc, "_PAGE_SIZE", 3)  # PAGE1 fills a page, forcing pagination

    def fake_request(url, username, password):
        assert (username, password) == ("scott", "pw")
        if "/cloud/users/scott" in url:
            return 200, QUOTA
        if "since=28" in url:
            return 200, PAGE2
        assert "since=" not in url
        return 200, PAGE1

    monkeypatch.setattr(nc, "_request", fake_request)


def test_collect_maps_types_windows_and_folders(fake_api):
    events = list(nc.CONNECTOR.collect(CFG, SINCE, UNTIL))
    created = [e for e in events if e.kind == "file.created"]
    assert [e.entity for e in created] == ["cat.jpg", "notes.md"]  # 2025 file windowed out
    assert [e.entity_group for e in created] == ["Photos", "/"]
    assert len([e for e in events if e.kind == "file.shared"]) == 1
    assert not [e for e in events if "deleted" in e.kind]  # unmapped types dropped
    (snap,) = [e for e in events if e.kind == "storage.used"]
    assert snap.value == 5_000_000_000
    assert snap.ts == UNTIL


def test_quota_failure_keeps_activity_events(fake_api, monkeypatch):
    def flaky(url, username, password):
        if "/cloud/users/" in url:
            raise OSError("boom")
        return (200, PAGE2) if "since=" in url else (200, PAGE1)

    monkeypatch.setattr(nc, "_request", flaky)
    events = list(nc.CONNECTOR.collect(CFG, SINCE, UNTIL))
    assert not [e for e in events if e.kind == "storage.used"]
    assert [e for e in events if e.kind == "file.created"]  # files still counted


def test_test_reports_ok(fake_api):
    result = nc.CONNECTOR.test(CFG)
    assert result.ok
    assert "scott" in result.message


def test_test_handles_empty_server(monkeypatch):
    monkeypatch.setattr(nc, "_request", lambda url, u, p: (204, None))
    result = nc.CONNECTOR.test(CFG)
    assert result.ok
    assert "no activity" in result.message


def test_files_and_storage_facts(fake_api):
    store = EventStore(":memory:")
    # Collect mid-year so the ts=until snapshot lands inside the fact window.
    store.add_events(nc.CONNECTOR.collect(CFG, SINCE, datetime(2026, 7, 1, tzinfo=UTC)))
    store.add_events(
        [
            Event(
                source="nextcloud",
                kind="storage.used",
                ts=datetime(2026, 2, 1, tzinfo=UTC),
                value=2_000_000_000,
            )
        ]
    )
    ctx = FactContext(store=store, since=SINCE, until=UNTIL, tz=UTC)
    total = _files_total(ctx)
    assert total["value"] == 2
    assert total["headline"] == "2 files added to your cloud"
    folders = _files_top_folders(ctx)
    assert {i["label"] for i in folders["items"]} == {"Photos", "/"}
    growth = _storage_growth(ctx)
    assert growth["headline"] == "3 GB added to your cloud"
    assert "5 GB" in growth["sub"]
