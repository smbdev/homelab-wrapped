"""Generic CSV/JSON connector against committed fixtures."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from wrapped.connectors import all_connectors
from wrapped.connectors.base import Connector, missing_required
from wrapped.connectors.generic_csv import CONNECTOR

FIXTURES = Path(__file__).parent / "fixtures"
Y2026 = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))


def test_discovered_by_registry():
    connectors = all_connectors()
    assert "generic_csv" in connectors
    assert isinstance(connectors["generic_csv"], Connector)


def test_collect_csv_window_filters():
    cfg = {"path": str(FIXTURES / "events.csv")}
    events = list(CONNECTOR.collect(cfg, *Y2026))
    assert len(events) == 3  # the 2025 Severance row is outside the window
    assert events[0].entity == "The Bear S03E01"
    assert events[0].value == 28.0
    assert events[0].entity_group == "The Bear"


def test_naive_timestamps_localised_to_configured_tz():
    cfg = {"path": str(FIXTURES / "events.csv"), "timezone": "Europe/Berlin"}
    photo = next(e for e in CONNECTOR.collect(cfg, *Y2026) if e.kind == "photo.taken")
    assert photo.ts.utcoffset() is not None
    assert photo.ts.astimezone(UTC) == datetime(2026, 2, 14, 8, 30, tzinfo=UTC)  # 09:30 CET


def test_collect_json():
    cfg = {"path": str(FIXTURES / "events.json")}
    events = list(CONNECTOR.collect(cfg, *Y2026))
    assert [e.entity for e in events] == ["invoice-march.pdf", "warranty.pdf"]
    assert events[0].value == 1.0  # default when absent


def test_test_reports_count():
    result = CONNECTOR.test({"path": str(FIXTURES / "events.csv")})
    assert result.ok
    assert "4 events" in result.message


def test_test_missing_file():
    result = CONNECTOR.test({"path": "/nope/nothing.csv"})
    assert not result.ok
    assert "not found" in result.message


def test_bad_row_is_loud(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("ts,kind\n2026-01-01T00:00:00,\n")
    with pytest.raises(ValueError, match="row 1"):
        list(CONNECTOR.collect({"path": str(bad)}, *Y2026))
    assert not CONNECTOR.test({"path": str(bad)}).ok


def test_missing_required_config():
    assert missing_required(CONNECTOR.schema, {}) == ["path"]
    assert missing_required(CONNECTOR.schema, {"path": "x"}) == []
