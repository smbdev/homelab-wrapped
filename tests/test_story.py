"""Story builder: modes, persistence, and the snapshot test for card output."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wrapped.connectors.generic_csv import CONNECTOR
from wrapped.core.events import EventStore
from wrapped.core.story import Period, build_story, list_stories, load_story, save_story

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2027, 1, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def store():
    """Store loaded from the committed CSV/JSON fixtures — same data as a real sync."""
    s = EventStore()
    window = (datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC))
    for path in ("events.csv", "events.json"):
        s.add_events(CONNECTOR.collect({"path": str(FIXTURES / path)}, *window))
    yield s
    s.close()


def test_year_story_matches_snapshot(store):
    story = build_story(store, Period("year", year=2026), UTC, now=NOW)
    snapshot_path = FIXTURES / "snapshots" / "year-2026.json"
    expected = json.loads(snapshot_path.read_text())
    assert story == expected, f"story spec changed — if intended, update {snapshot_path}"


def test_month_story_only_sees_its_month(store):
    story = build_story(store, Period("month", year=2026, month=1), UTC, now=NOW)
    assert story["period"] == {"type": "month", "id": "2026-01", "label": "January 2026"}
    facts = [c["fact"] for c in story["cards"]]
    assert "media.total_hours" in facts
    assert "photos.total" not in facts  # the photo is in February


def test_empty_period_gives_empty_cards(store):
    story = build_story(store, Period("year", year=1999), UTC, now=NOW)
    assert story["cards"] == []


def test_cards_run_in_rank_order(store):
    """The recap is a story, so cards follow FACTS' rank, not list order."""
    from wrapped.facts import FACTS

    rank = {f.id: f.rank for f in FACTS}
    story = build_story(store, Period("year", year=2026), UTC, now=NOW)
    ranks = [rank[c["fact"]] for c in story["cards"]]
    assert ranks == sorted(ranks)


def test_arc_survives_a_sparse_homelab(store):
    """One connector's worth of data still opens warm and closes on the year."""
    story = build_story(store, Period("year", year=2026), UTC, now=NOW)
    facts = [c["fact"] for c in story["cards"]]
    assert facts[0] == "media.total_hours", "the recap opens on something human"
    assert facts[-1] == "activity.by_day", "and closes on the whole year at once"


def test_on_this_day(store):
    story = build_story(store, Period("day", month=6, day=1), UTC, now=NOW)
    (card,) = story["cards"]  # Severance was played 2025-06-01
    assert card["year"] == 2025
    assert card["headline"] == "2 years ago today"
    assert card["sub"] == "1 thing watched"
    assert story["period"]["id"] == "day-06-01"


def test_on_this_day_empty_store():
    s = EventStore()
    story = build_story(s, Period("day", month=6, day=1), UTC, now=NOW)
    assert story["cards"] == []
    s.close()


def test_save_load_list_roundtrip(store, tmp_path):
    year = build_story(store, Period("year", year=2026), UTC, now=NOW)
    month = build_story(store, Period("month", year=2026, month=1), UTC, now=NOW)
    save_story(tmp_path / "stories", year)
    save_story(tmp_path / "stories", month)
    assert list_stories(tmp_path / "stories") == ["2026-01", "2026"]
    assert load_story(tmp_path / "stories", "2026") == year


def test_list_stories_missing_dir(tmp_path):
    assert list_stories(tmp_path / "nope") == []
