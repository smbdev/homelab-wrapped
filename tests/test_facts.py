"""Fact computation and copy templates."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from wrapped.core.events import Event, EventStore
from wrapped.facts import FACTS, FactContext, plural

Y2026 = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))


def fact(fact_id):
    return next(f for f in FACTS if f.id == fact_id)


@pytest.fixture
def store():
    s = EventStore()
    yield s
    s.close()


def ctx(store, tz=UTC):
    return FactContext(store=store, since=Y2026[0], until=Y2026[1], tz=tz)


def play(day, ep, show, minutes=30.0, month=1):
    return Event(
        source="t",
        kind="media.play",
        ts=datetime(2026, month, day, 20, tzinfo=UTC),
        entity=ep,
        entity_group=show,
        value=minutes,
    )


def photo(day, month=1, hour=12):
    return Event(source="t", kind="photo.taken", ts=datetime(2026, month, day, hour, tzinfo=UTC))


def test_plural():
    assert plural(1, "hour") == "1 hour"
    assert plural(2, "hour") == "2 hours"
    assert plural(1500, "photo") == "1,500 photos"
    assert plural(2, "ep") == "2 eps"
    assert plural(1.0, "full day") == "1 full day"
    assert plural(3, "year") == "3 years"


def test_all_facts_none_on_empty_store(store):
    c = ctx(store)
    assert all(f.compute(c) is None for f in FACTS)


def test_fact_ranks_are_unique():
    """Two facts sharing a rank makes their order arbitrary — usually a copy-paste."""
    ranks = [f.rank for f in FACTS]
    dupes = {r for r in ranks if ranks.count(r) > 1}
    assert not dupes, f"duplicate fact ranks: {sorted(dupes)}"


def test_total_hours_copy(store):
    store.add_events([play(d, f"E{d}", "The Bear", minutes=100.0) for d in range(1, 16)])
    card = fact("media.total_hours").compute(ctx(store))
    assert card["value"] == 25
    assert card["headline"] == "25 hours watched"
    assert card["sub"] == "That's 1 full day of telly"


def test_total_hours_no_sub_under_a_day(store):
    store.add_events([play(1, "E1", "The Bear", minutes=90.0)])
    card = fact("media.total_hours").compute(ctx(store))
    assert card["headline"] == "2 hours watched"  # 1.5 rounds to 2
    assert "sub" not in card


def test_top_shows(store):
    store.add_events(
        [play(1, "E1", "The Bear"), play(2, "E2", "The Bear"), play(3, "E1", "Severance")]
    )
    card = fact("media.top_shows").compute(ctx(store))
    assert card["items"][0] == {"label": "The Bear", "value": "2 eps"}
    assert card["items"][1] == {"label": "Severance", "value": "1 ep"}


def test_busiest_photo_day(store):
    store.add_events([photo(14, month=2, hour=h) for h in range(9, 12)] + [photo(1)])
    card = fact("photos.busiest_day").compute(ctx(store))
    assert card["value"] == 3
    assert card["sub"] == "Your camera's big day out: 14 February"


def test_streak_requires_two_days(store):
    store.add_events([photo(5)])
    assert fact("activity.streak").compute(ctx(store)) is None
    store.add_events([photo(6), photo(7)])
    card = fact("activity.streak").compute(ctx(store))
    assert card["headline"] == "A 3-day streak"
    assert card["sub"] == "Every single day from 5 January"


def test_heatmap_data_keys_are_iso_dates(store):
    store.add_events([photo(5), photo(5), photo(9)])
    card = fact("activity.by_day").compute(ctx(store))
    assert card["data"] == {"2026-01-05": 2, "2026-01-09": 1}


def test_heatmap_respects_timezone(store):
    # 23:30 UTC Jan 5 is Jan 6 in Berlin
    store.add_events([photo(5, hour=23)])
    card = fact("activity.by_day").compute(ctx(store, tz=ZoneInfo("Europe/Berlin")))
    assert list(card["data"]) == ["2026-01-06"]
