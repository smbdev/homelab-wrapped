"""Event store: roundtrip, sync state, purge, aggregation."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from wrapped.core.events import Event, EventStore, busiest_day, longest_streak

BERLIN = ZoneInfo("Europe/Berlin")


def ev(day, kind="media.play", entity=None, group=None, value=1.0, hour=20, source="test"):
    return Event(
        source=source,
        kind=kind,
        ts=datetime(2026, 1, day, hour, tzinfo=UTC),
        entity=entity,
        entity_group=group,
        value=value,
        meta={"n": day},
    )


JAN = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


@pytest.fixture
def store():
    s = EventStore()
    yield s
    s.close()


def test_roundtrip(store):
    store.add_events([ev(5, entity="The Bear S03E01", group="The Bear", value=28.0)])
    (e,) = store.events(*JAN)
    assert e.source == "test"
    assert e.kind == "media.play"
    assert e.ts == datetime(2026, 1, 5, 20, tzinfo=UTC)
    assert e.entity == "The Bear S03E01"
    assert e.entity_group == "The Bear"
    assert e.value == 28.0
    assert e.meta == {"n": 5}


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        Event(source="x", kind="y", ts=datetime(2026, 1, 1))


def test_window_is_half_open(store):
    store.add_events([ev(1, hour=0), ev(31, hour=23)])
    until = datetime(2026, 1, 31, 23, tzinfo=UTC)
    assert store.totals(JAN[0], until)[0] == 1  # boundary event excluded


def test_kind_filters(store):
    store.add_events([ev(1), ev(2, kind="media.listen"), ev(3, kind="photo.taken")])
    assert store.totals(*JAN, kind="media.play")[0] == 1
    assert store.totals(*JAN, kind="media.*")[0] == 2
    assert store.totals(*JAN)[0] == 3


def test_totals_sums_values(store):
    store.add_events([ev(1, value=10.5), ev(2, value=4.5)])
    assert store.totals(*JAN) == (2, 15.0)


def test_totals_empty_window(store):
    assert store.totals(*JAN) == (0, 0)


def test_top_by_count_and_value(store):
    store.add_events(
        [
            ev(1, group="The Bear", value=30),
            ev(2, group="The Bear", value=30),
            ev(3, group="Severance", value=100),
        ]
    )
    assert store.top(*JAN, by="count")[0] == ("The Bear", 2, 60.0)
    assert store.top(*JAN, by="value")[0] == ("Severance", 1, 100.0)
    assert store.top(*JAN, limit=1) == [("The Bear", 2, 60.0)]
    with pytest.raises(ValueError, match="count.*value"):
        store.top(*JAN, by="entity; DROP TABLE events")


def test_top_skips_null_groups(store):
    store.add_events([ev(1), ev(2, group="Named")])
    assert store.top(*JAN) == [("Named", 1, 1.0)]


def test_by_day_buckets_in_local_timezone(store):
    # 23:30 UTC on Jan 5 is already Jan 6 in Berlin (UTC+1).
    store.add_events([ev(5, hour=23, value=2.0)])
    assert store.by_day(*JAN, tz=BERLIN) == {date(2026, 1, 6): 2.0}
    assert store.by_day(*JAN, tz=UTC) == {date(2026, 1, 5): 2.0}


def test_sync_state(store):
    assert store.last_sync("jellyfin") is None
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 2, 1, tzinfo=UTC)
    store.set_last_sync("jellyfin", t1)
    assert store.last_sync("jellyfin") == t1
    store.set_last_sync("jellyfin", t2)  # upsert
    assert store.last_sync("jellyfin") == t2


def test_purge_all_resets_sync_state(store):
    store.add_events([ev(1), ev(2)])
    store.set_last_sync("test", datetime(2026, 1, 2, tzinfo=UTC))
    assert store.purge() == 2
    assert store.totals(*JAN)[0] == 0
    assert store.last_sync("test") is None


def test_purge_retention_cutoff(store):
    store.add_events([ev(1), ev(20)])
    assert store.purge(before=datetime(2026, 1, 10, tzinfo=UTC)) == 1
    assert store.totals(*JAN)[0] == 1
    # retention purge keeps sync state — not a full reset


def test_purge_single_source(store):
    store.add_events([ev(1), ev(2, source="other")])
    store.set_last_sync("other", datetime(2026, 1, 2, tzinfo=UTC))
    store.set_last_sync("test", datetime(2026, 1, 2, tzinfo=UTC))
    assert store.purge(source="other") == 1
    assert store.last_sync("other") is None
    assert store.last_sync("test") is not None


def test_longest_streak():
    days = {date(2026, 1, d): 1.0 for d in (1, 2, 3, 7, 8, 9, 10, 20)}
    assert longest_streak(days) == (4, date(2026, 1, 7))
    assert longest_streak({}) == (0, None)
    assert longest_streak({date(2026, 1, 5): 1.0}) == (1, date(2026, 1, 5))


def test_streak_across_month_boundary():
    days = {date(2026, 1, 31): 1.0, date(2026, 2, 1): 1.0, date(2026, 2, 2): 1.0}
    assert longest_streak(days) == (3, date(2026, 1, 31))


def test_busiest_day():
    assert busiest_day({}) is None
    days = {date(2026, 1, 1): 3.0, date(2026, 1, 2): 9.0}
    assert busiest_day(days) == (date(2026, 1, 2), 9.0)


def test_persistence_to_file(tmp_path):
    path = tmp_path / "events.db"
    s = EventStore(path)
    s.add_events([ev(1)])
    s.close()
    s2 = EventStore(path)
    assert s2.totals(*JAN)[0] == 1
    s2.close()
