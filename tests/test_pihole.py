"""Pi-hole connector: FTL database aggregation and the DNS facts."""

import sqlite3
from datetime import UTC, datetime

import pytest

from wrapped.connectors.pihole import CONNECTOR
from wrapped.core.events import EventStore
from wrapped.facts import FactContext, _dns_blocked_total, _dns_top_blocked

SINCE = datetime(2026, 1, 1, tzinfo=UTC)
UNTIL = datetime(2027, 1, 1, tzinfo=UTC)


@pytest.fixture
def ftl_db(tmp_path):
    """A miniature pihole-FTL.db: two days of queries."""
    path = tmp_path / "pihole-FTL.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE queries (timestamp INTEGER, status INTEGER, domain TEXT)")
    day1 = int(datetime(2026, 3, 1, 9, tzinfo=UTC).timestamp())
    day2 = int(datetime(2026, 3, 2, 9, tzinfo=UTC).timestamp())
    rows = []
    rows += [(day1, 2, "allowed.example")] * 70  # status 2 = forwarded (allowed)
    rows += [(day1, 1, "ads.example")] * 25  # status 1 = gravity-blocked
    rows += [(day1, 4, "tracker.example")] * 5  # status 4 = regex-blocked
    rows += [(day2, 2, "allowed.example")] * 10
    rows += [(day2, 1, "ads.example")] * 40
    db.executemany("INSERT INTO queries VALUES (?, ?, ?)", rows)
    db.commit()
    db.close()
    return path


def test_test_counts_queries(ftl_db):
    result = CONNECTOR.test({"db_path": str(ftl_db)})
    assert result.ok
    assert "150" in result.message


def test_collect_aggregates_per_day(ftl_db):
    events = list(CONNECTOR.collect({"db_path": str(ftl_db)}, SINCE, UNTIL))
    totals = {(e.kind, e.ts.date().isoformat()): e.value for e in events if e.entity is None}
    assert totals[("dns.query", "2026-03-01")] == 100
    assert totals[("dns.blocked", "2026-03-01")] == 30
    assert totals[("dns.blocked", "2026-03-02")] == 40
    domains = [e for e in events if e.kind == "dns.blocked_domain"]
    assert {(e.entity, e.ts.date().isoformat()): e.value for e in domains}[
        ("ads.example", "2026-03-01")
    ] == 25


def test_collect_respects_window(ftl_db):
    events = list(
        CONNECTOR.collect(
            {"db_path": str(ftl_db)},
            datetime(2026, 3, 2, tzinfo=UTC),
            UNTIL,
        )
    )
    assert {e.ts.date().isoformat() for e in events} == {"2026-03-02"}


def _ctx_from(events):
    store = EventStore(":memory:")
    store.add_events(events)
    return FactContext(store=store, since=SINCE, until=UNTIL, tz=UTC)


def test_dns_facts_from_collected_events(ftl_db):
    ctx = _ctx_from(CONNECTOR.collect({"db_path": str(ftl_db)}, SINCE, UNTIL))
    # only 70 blocked in the fixture — below the four-digit brag threshold
    assert _dns_blocked_total(ctx) is None
    top = _dns_top_blocked(ctx)
    assert top["items"][0]["label"] == "ads.example"
    assert top["items"][0]["value"] == "65×"


def test_dns_blocked_total_with_enough_data():
    from wrapped.core.events import Event

    day = datetime(2026, 5, 1, 12, tzinfo=UTC)
    ctx = _ctx_from(
        [
            Event(source="pihole", kind="dns.blocked", ts=day, value=200_000.0),
            Event(source="pihole", kind="dns.query", ts=day, value=1_000_000.0),
        ]
    )
    card = _dns_blocked_total(ctx)
    assert card["value"] == 200_000
    assert card["headline"] == "200,000 ads and trackers blocked"
    assert "20% of all DNS queries" in card["sub"]


def test_missing_db_fails_test(tmp_path):
    result = CONNECTOR.test({"db_path": str(tmp_path / "nope.db")})
    assert result.ok is False
