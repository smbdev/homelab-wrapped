"""End-to-end CLI: fixture CSV → sync → db populated → purge."""

from datetime import UTC, datetime
from pathlib import Path

from wrapped.cli import main
from wrapped.core.events import EventStore

FIXTURES = Path(__file__).parent / "fixtures"
ALL_TIME = (datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC))


def write_config(tmp_path):
    db = tmp_path / "events.db"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"""
database: {db}
connectors:
  media:
    type: generic_csv
    path: {FIXTURES / "events.csv"}
  docs:
    type: generic_csv
    path: {FIXTURES / "events.json"}
"""
    )
    return cfg, db


def test_sync_populates_store(tmp_path, capsys):
    cfg, db = write_config(tmp_path)
    assert main(["--config", str(cfg), "sync"]) == 0
    out = capsys.readouterr().out
    assert "media: 4 new events" in out
    assert "docs: 2 new events" in out

    store = EventStore(db)
    assert store.totals(*ALL_TIME)[0] == 6
    # Event.source is the instance name, not the plugin id
    assert store.totals(*ALL_TIME, source="media")[0] == 4
    store.close()


def test_sync_is_incremental(tmp_path, capsys):
    cfg, db = write_config(tmp_path)
    main(["--config", str(cfg), "sync"])
    assert main(["--config", str(cfg), "sync"]) == 0
    assert "media: 0 new events" in capsys.readouterr().out


def test_purge_wipes_cache(tmp_path, capsys):
    cfg, db = write_config(tmp_path)
    main(["--config", str(cfg), "sync"])
    assert main(["--config", str(cfg), "purge"]) == 0
    assert "Purged 6 events." in capsys.readouterr().out
    store = EventStore(db)
    assert store.totals(*ALL_TIME)[0] == 0
    store.close()


def test_unknown_connector_type(tmp_path, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"database: {tmp_path}/e.db\nconnectors:\n  x:\n    type: nope\n")
    assert main(["--config", str(cfg), "sync"]) == 1
    assert "unknown type" in capsys.readouterr().err


def test_missing_config_file(capsys):
    assert main(["--config", "/absent.yaml", "sync"]) == 1
    assert "not found" in capsys.readouterr().err


def test_build_saves_story(tmp_path, capsys):
    cfg, db = write_config(tmp_path)
    main(["--config", str(cfg), "sync"])
    assert main(["--config", str(cfg), "build", "--year", "2026"]) == 0
    out = capsys.readouterr().out
    assert "Your 2026" in out
    story_file = tmp_path / "stories" / "2026.json"
    assert story_file.exists()


def test_build_month_and_on_this_day(tmp_path):
    cfg, db = write_config(tmp_path)
    main(["--config", str(cfg), "sync"])
    assert main(["--config", str(cfg), "build", "--month", "2026-01"]) == 0
    assert main(["--config", str(cfg), "build", "--on-this-day", "06-01"]) == 0
    assert (tmp_path / "stories" / "2026-01.json").exists()
    assert (tmp_path / "stories" / "day-06-01.json").exists()


def test_build_bad_month(tmp_path, capsys):
    cfg, db = write_config(tmp_path)
    assert main(["--config", str(cfg), "build", "--month", "march"]) == 1
    assert "Invalid period" in capsys.readouterr().err


def test_stub_commands(capsys):
    assert main(["serve"]) == 2
