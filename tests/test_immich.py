"""Immich connector against recorded API responses — never a live server."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import wrapped.connectors.immich as immich_mod
from wrapped.connectors import all_connectors
from wrapped.connectors.immich import CONNECTOR

FIXTURES = Path(__file__).parent / "fixtures"
Y2026 = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))
CFG = {"url": "http://immich.local:2283/", "api_key": "test-key"}


@pytest.fixture
def fake_api(monkeypatch):
    """Replace the HTTP layer with recorded responses; captures every call."""
    pages = json.loads((FIXTURES / "immich_search.json").read_text())
    calls = []

    def fake_request(url, api_key, payload=None):
        calls.append({"url": url, "api_key": api_key, "payload": payload})
        if url.endswith("/api/users/me"):
            return {"name": "scott"}
        return pages[str(payload["page"])]

    monkeypatch.setattr(immich_mod, "_request", fake_request)
    return calls


def test_discovered_by_registry():
    assert "immich" in all_connectors()


def test_test_authenticates(fake_api):
    result = CONNECTOR.test(CFG)
    assert result.ok
    assert "scott" in result.message
    assert fake_api[0]["url"] == "http://immich.local:2283/api/users/me"


def test_collect_paginates_and_normalises(fake_api):
    events = list(CONNECTOR.collect(CFG, *Y2026))
    assert len(events) == 3  # two on page 1, one on page 2
    first = events[0]
    assert first.kind == "photo.taken"
    assert first.entity == "IMG_2041.jpg"
    assert first.entity_group == "Seville"
    assert first.ts == datetime(2026, 2, 14, 9, 30, tzinfo=UTC)
    assert first.value == 1.0
    assert first.meta == {"asset_id": "a1"}
    # both pages were fetched, with the window passed server-side
    searches = [c for c in fake_api if c["payload"]]
    assert [c["payload"]["page"] for c in searches] == [1, 2]
    assert searches[0]["payload"]["takenAfter"].startswith("2026-01-01")


def test_asset_without_capture_time_skipped(fake_api):
    events = list(CONNECTOR.collect(CFG, *Y2026))
    assert all(e.entity != "broken.jpg" for e in events)


def test_out_of_window_asset_filtered_client_side(fake_api):
    events = list(CONNECTOR.collect(CFG, *Y2026))
    assert all(e.ts.year == 2026 for e in events)


def test_test_unreachable_server(monkeypatch):
    import urllib.error

    def boom(url, api_key, payload=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(immich_mod, "_request", boom)
    result = CONNECTOR.test(CFG)
    assert not result.ok
    assert "Could not reach" in result.message
