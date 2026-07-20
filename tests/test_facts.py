"""Fact computation and copy templates."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from wrapped.core.events import Event, EventStore
from wrapped.facts import FACTS, FactContext, PriorWindow, plural, versus_prior

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


def test_private_facts_are_the_ones_naming_real_world_things():
    """Cards that name people, folders or domains stay off the record.

    Pinned deliberately: adding a fact that names real-world things without
    marking it private would silently make it exportable as a PNG.
    """
    private = {f.id for f in FACTS if f.private}
    assert private == {
        "docs.top_senders",
        "docs.top_tags",
        "files.top_folders",
        "dns.top_blocked",
    }


def test_top_shows_stays_shareable():
    """The flagship card — taste, not identity — must not drift to private."""
    assert fact("media.top_shows").private is False


def test_aggregate_totals_are_never_private():
    """A bare number leaks nothing, so it should always be exportable."""
    totals = ["media.total_hours", "photos.total", "files.total", "docs.total"]
    assert not any(fact(f).private for f in totals)


def test_fact_ranks_are_unique():
    """Two facts sharing a rank makes their order arbitrary — usually a copy-paste."""
    ranks = [f.rank for f in FACTS]
    dupes = {r for r in ranks if ranks.count(r) > 1}
    assert not dupes, f"duplicate fact ranks: {sorted(dupes)}"


# -- year-over-year comparisons ----------------------------------------

Y2025 = (datetime(2025, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC))


def ctx_vs_2025(store, tz=UTC):
    """A 2026 context that compares against 2025."""
    return FactContext(
        store=store,
        since=Y2026[0],
        until=Y2026[1],
        tz=tz,
        prior=PriorWindow(Y2025[0], Y2025[1], "2025"),
    )


def prior_plays(n, minutes=10.0):
    """``n`` media.play events in 2025, spread over distinct days."""
    return [
        Event(
            source="t",
            kind="media.play",
            ts=datetime(2025, 1 + i // 28, 1 + i % 28, 20, tzinfo=UTC),
            entity=f"P{i}",
            entity_group="Old Show",
            value=minutes,
        )
        for i in range(n)
    ]


def test_versus_prior_silent_without_a_prior_window(store):
    store.add_events(prior_plays(5))
    assert versus_prior(ctx(store), 100.0, "media.play") is None


def test_versus_prior_silent_on_a_first_year_homelab(store):
    """Nothing recorded last year must not become "up ∞%"."""
    assert versus_prior(ctx_vs_2025(store), 100.0, "media.play") is None


def test_versus_prior_silent_when_prior_is_too_thin(store):
    """Two stray events last year is noise, not a baseline."""
    store.add_events(prior_plays(2, minutes=50.0))
    assert versus_prior(ctx_vs_2025(store), 100.0, "media.play") is None


def test_versus_prior_silent_when_current_is_zero(store):
    store.add_events(prior_plays(5, minutes=50.0))
    assert versus_prior(ctx_vs_2025(store), 0, "media.play") is None


@pytest.mark.parametrize(
    "current,expected",
    [
        (500.0, "more than triple 2025"),  # 5.0x
        (300.0, "more than triple 2025"),  # exactly 3.0x
        (250.0, "more than double 2025"),  # 2.5x
        (140.0, "up 40% on 2025"),
        (103.0, "almost exactly what you managed in 2025"),  # 1.03x
        (97.0, "almost exactly what you managed in 2025"),  # 0.97x
        (70.0, "down 30% on 2025"),
        (40.0, "less than half 2025"),
    ],
)
def test_versus_prior_bands(store, current, expected):
    store.add_events(prior_plays(5, minutes=20.0))  # 100 minutes in 2025
    assert versus_prior(ctx_vs_2025(store), current, "media.play") == expected


def test_versus_prior_counts_events_when_asked(store):
    """by='count' compares event counts, not summed values."""
    store.add_events(
        [
            Event(source="t", kind="photo.taken", ts=datetime(2025, 3, i + 1, tzinfo=UTC))
            for i in range(10)
        ]
    )
    got = versus_prior(ctx_vs_2025(store), 20, "photo.taken", by="count")
    assert got == "more than double 2025"


def test_comparison_replaces_flavour_text(store):
    """When there's a real comparison it wins the sub-line; flavour is the fallback."""
    store.add_events(prior_plays(5, minutes=200.0))  # 1000 minutes in 2025
    store.add_events([play(d, f"E{d}", "The Bear", minutes=100.0) for d in range(1, 16)])

    card = fact("media.total_hours").compute(ctx_vs_2025(store))
    assert card["sub"] == "up 50% on 2025"  # 1500 vs 1000 minutes

    without_prior = fact("media.total_hours").compute(ctx(store))
    assert without_prior["sub"] == "That's 1 full day of telly"


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
