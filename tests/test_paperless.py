"""Paperless-ngx connector: windowing, pagination, correspondents, facts."""

from datetime import UTC, datetime

import pytest

import wrapped.connectors.paperless as pl
from wrapped.core.events import EventStore
from wrapped.facts import FactContext, _docs_top_senders, _docs_total

SINCE = datetime(2026, 1, 1, tzinfo=UTC)
UNTIL = datetime(2027, 1, 1, tzinfo=UTC)
CFG = {"url": "http://paperless.local:8000", "api_token": "tok"}

PAGE1 = {
    "count": 3,
    "next": "http://paperless.local:8000/api/documents/?page=2",
    "results": [
        {"title": "Electric bill", "added": "2026-02-01T10:00:00+00:00", "correspondent": 1},
        {"title": "Payslip", "added": "2026-03-01T10:00:00+00:00", "correspondent": 2},
    ],
}
PAGE2 = {
    "count": 3,
    "next": None,
    "results": [
        {"title": "Old letter", "added": "2025-01-01T10:00:00+00:00", "correspondent": None},
    ],
}
CORRESPONDENTS = {
    "count": 2,
    "next": None,
    "results": [{"id": 1, "name": "PowerCo"}, {"id": 2, "name": "Work"}],
}


@pytest.fixture
def fake_api(monkeypatch):
    def fake_request(url, token):
        assert token == "tok"
        if "/api/correspondents/" in url:
            return CORRESPONDENTS
        if "page=2" in url:
            return PAGE2
        if "page_size=1" in url:
            return {"count": 3, "next": None, "results": []}
        assert "added__date__gt=" in url
        return PAGE1

    monkeypatch.setattr(pl, "_request", fake_request)


def test_collect_pages_windows_and_names_correspondents(fake_api):
    events = list(pl.CONNECTOR.collect(CFG, SINCE, UNTIL))
    assert [e.entity for e in events] == ["Electric bill", "Payslip"]  # 2025 doc windowed out
    assert [e.entity_group for e in events] == ["PowerCo", "Work"]
    assert all(e.kind == "doc.added" for e in events)


def test_correspondent_lookup_failure_is_tolerated(fake_api, monkeypatch):
    def flaky(url, token):
        if "/api/correspondents/" in url:
            raise OSError("boom")
        return PAGE2 if "page=2" in url else PAGE1

    monkeypatch.setattr(pl, "_request", flaky)
    events = list(pl.CONNECTOR.collect(CFG, SINCE, UNTIL))
    assert [e.entity_group for e in events] == [None, None]  # docs still counted


def test_test_reports_document_count(fake_api):
    result = pl.CONNECTOR.test(CFG)
    assert result.ok
    assert "3 documents" in result.message


def test_docs_facts(fake_api):
    store = EventStore(":memory:")
    store.add_events(pl.CONNECTOR.collect(CFG, SINCE, UNTIL))
    ctx = FactContext(store=store, since=SINCE, until=UNTIL, tz=UTC)
    total = _docs_total(ctx)
    assert total["value"] == 2
    assert total["headline"] == "2 documents archived"
    senders = _docs_top_senders(ctx)
    assert {i["label"] for i in senders["items"]} == {"PowerCo", "Work"}
