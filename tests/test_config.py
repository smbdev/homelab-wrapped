"""config.yaml parsing and validation."""

from zoneinfo import ZoneInfo

import pytest

from wrapped.core.config import load_config


def write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return p


def test_full_config(tmp_path):
    cfg = load_config(
        write(
            tmp_path,
            """
timezone: Europe/Berlin
database: /data/events.db
retention_days: 730
connectors:
  my_media:
    type: generic_csv
    path: /data/media.csv
""",
        )
    )
    assert cfg.timezone == ZoneInfo("Europe/Berlin")
    assert str(cfg.database) == "/data/events.db"
    assert cfg.retention_days == 730
    (entry,) = cfg.connectors
    assert (entry.name, entry.type) == ("my_media", "generic_csv")
    assert entry.cfg == {"path": "/data/media.csv"}


def test_defaults(tmp_path):
    cfg = load_config(write(tmp_path, ""))
    assert cfg.timezone == ZoneInfo("UTC")
    assert str(cfg.database) == "data/events.db"
    assert cfg.retention_days is None
    assert cfg.connectors == []


def test_unknown_timezone(tmp_path):
    with pytest.raises(ValueError, match="unknown timezone"):
        load_config(write(tmp_path, "timezone: Mars/Olympus_Mons"))


def test_bad_retention(tmp_path):
    with pytest.raises(ValueError, match="retention_days"):
        load_config(write(tmp_path, "retention_days: -5"))


def test_connector_without_type(tmp_path):
    with pytest.raises(ValueError, match="'type' key"):
        load_config(write(tmp_path, "connectors:\n  broken:\n    path: /x.csv\n"))


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "absent.yaml")
