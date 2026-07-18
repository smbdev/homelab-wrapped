"""config.yaml parsing and validation."""

from pathlib import Path
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
    assert cfg.database == tmp_path / "data" / "events.db"  # relative to the config file
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


def test_create_starter_config(tmp_path):
    from wrapped.core.config import create_starter_config

    path = tmp_path / "data" / "config.yaml"
    cfg = create_starter_config(path)
    assert path.is_file()
    assert "connectors" in path.read_text()
    assert cfg.connectors == []  # safe by default: nothing enabled
    assert cfg.schedule.monthly_recap is False
    assert cfg.email is None
    assert load_config(path).connectors == []  # the written file round-trips


def test_repo_example_config_is_valid():
    example = Path(__file__).parent.parent / "config.example.yaml"
    cfg = load_config(example)
    assert cfg.connectors == []


def test_add_and_remove_connector(tmp_path):
    from wrapped.core.config import add_connector, create_starter_config, remove_connector

    path = tmp_path / "config.yaml"
    create_starter_config(path)
    add_connector(path, "media", "generic_csv", {"path": "/data/x.csv"})
    (entry,) = load_config(path).connectors
    assert (entry.name, entry.type, entry.cfg) == ("media", "generic_csv", {"path": "/data/x.csv"})

    with pytest.raises(ValueError, match="already exists"):
        add_connector(path, "media", "generic_csv", {"path": "/y.csv"})
    with pytest.raises(ValueError, match="letters, digits"):
        add_connector(path, "bad name!", "generic_csv", {"path": "/y.csv"})

    remove_connector(path, "media")
    assert load_config(path).connectors == []
    with pytest.raises(ValueError, match="no connector"):
        remove_connector(path, "media")


def test_add_connector_preserves_other_settings(tmp_path):
    from wrapped.core.config import add_connector

    path = tmp_path / "config.yaml"
    path.write_text("timezone: Europe/Berlin\nretention_days: 30\n")
    add_connector(path, "media", "generic_csv", {"path": "/x.csv"})
    cfg = load_config(path)
    assert cfg.timezone == ZoneInfo("Europe/Berlin")
    assert cfg.retention_days == 30
    assert len(cfg.connectors) == 1
