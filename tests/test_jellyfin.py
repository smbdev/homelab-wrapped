"""Jellyfin connector against a fixture Playback Reporting database."""

from datetime import UTC, datetime

import pytest

from wrapped.connectors import all_connectors
from wrapped.connectors.jellyfin import CONNECTOR

Y2026 = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))

ROWS = [
    # (DateCreated, ItemName, ItemType, PlayDuration seconds, UserId)
    ("2026-01-05 20:00:00", "The Bear - s03e01 - Tomorrow", "Episode", 1680, "user-a"),
    ("2026-01-06 21:15:00", "The Bear - s03e02 - Next", "Episode", 1740, "user-a"),
    ("2026-02-01 19:00:00", "Heat", "Movie", 10200, "user-b"),
    ("2025-06-01 12:00:00", "Severance - s01e01 - Good News", "Episode", 3300, "user-a"),
    ("not-a-date", "Broken Row", "Episode", 60, "user-a"),
]


@pytest.fixture
def db_path(tmp_path):
    import sqlite3

    path = tmp_path / "playback_reporting.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE PlaybackActivity (DateCreated TEXT, ItemName TEXT,"
        " ItemType TEXT, PlayDuration INT, UserId TEXT)"
    )
    db.executemany("INSERT INTO PlaybackActivity VALUES (?, ?, ?, ?, ?)", ROWS)
    db.commit()
    db.close()
    return str(path)


def test_discovered_by_registry():
    assert "jellyfin" in all_connectors()


def test_collect_window_and_normalisation(db_path):
    events = list(CONNECTOR.collect({"db_path": db_path}, *Y2026))
    assert len(events) == 3  # 2025 row outside window, broken row skipped
    bear = events[0]
    assert bear.kind == "media.play"
    assert bear.entity == "The Bear - s03e01 - Tomorrow"
    assert bear.entity_group == "The Bear"
    assert bear.value == 28.0  # 1680s → minutes
    assert bear.meta == {"item_type": "Episode"}


def test_movie_groups_as_itself(db_path):
    movie = next(e for e in CONNECTOR.collect({"db_path": db_path}, *Y2026) if e.entity == "Heat")
    assert movie.entity_group == "Heat"


def test_timezone_applied(db_path):
    cfg = {"db_path": db_path, "timezone": "Europe/Berlin"}
    first = next(iter(CONNECTOR.collect(cfg, *Y2026)))
    assert first.ts.utcoffset() is not None
    assert first.ts.astimezone(UTC) == datetime(2026, 1, 5, 19, 0, tzinfo=UTC)  # CET is UTC+1


def test_user_filter(db_path):
    cfg = {"db_path": db_path, "user_id": "user-b"}
    events = list(CONNECTOR.collect(cfg, *Y2026))
    assert [e.entity for e in events] == ["Heat"]


def test_test_reports_count(db_path):
    result = CONNECTOR.test({"db_path": db_path})
    assert result.ok
    assert "5 plays" in result.message


def test_test_missing_db(tmp_path):
    result = CONNECTOR.test({"db_path": str(tmp_path / "nope.db")})
    assert not result.ok


def test_db_opened_read_only(db_path):
    import sqlite3

    with CONNECTOR._connect(db_path) as db, pytest.raises(sqlite3.OperationalError):
        db.execute("INSERT INTO PlaybackActivity VALUES ('x','x','x',1,'x')")
