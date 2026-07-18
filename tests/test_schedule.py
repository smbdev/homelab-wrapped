"""Scheduled jobs and email digests — no scheduler loop, no real SMTP."""

import smtplib
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from wrapped.core.config import EmailConfig, load_config
from wrapped.core.digest import render_digest, send_digest
from wrapped.core.schedule import monthly_job, on_this_day_job, run_scheduler

FIXTURES = Path(__file__).parent / "fixtures"


def write_config(tmp_path, extra=""):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"""
database: {tmp_path}/data/events.db
connectors:
  media:
    type: generic_csv
    path: {FIXTURES / "events.csv"}
{extra}"""
    )
    return load_config(cfg)


# -- config ------------------------------------------------------------


def test_schedule_and_email_config(tmp_path):
    config = write_config(
        tmp_path,
        """
schedule:
  monthly_recap: true
  hour: 7
email:
  smtp_host: mail.local
  from: a@local
  to: b@local
  starttls: false
""",
    )
    assert config.schedule.monthly_recap is True
    assert config.schedule.on_this_day is False
    assert config.schedule.hour == 7
    assert config.email.smtp_host == "mail.local"
    assert config.email.starttls is False
    assert config.email.smtp_port == 587


def test_email_config_missing_keys(tmp_path):
    with pytest.raises(ValueError, match="missing required keys"):
        write_config(tmp_path, "email:\n  smtp_host: mail.local\n")


def test_defaults_no_schedule(tmp_path):
    config = write_config(tmp_path)
    assert config.schedule.monthly_recap is False
    assert config.email is None


# -- digest rendering --------------------------------------------------


STORY = {
    "period": {"type": "month", "id": "2026-01", "label": "January 2026"},
    "cards": [
        {"headline": "9 hours watched", "sub": "Not bad"},
        {"headline": "Your top shows", "items": [{"label": "The Bear", "value": "2 eps"}]},
    ],
}


def test_render_digest():
    subject, body = render_digest(STORY)
    assert subject == "Homelab Wrapped: January 2026"
    assert "• 9 hours watched" in body
    assert "  Not bad" in body
    assert "The Bear — 2 eps" in body
    assert "your own server" in body


def test_send_digest_uses_own_smtp(monkeypatch):
    calls = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls["conn"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            calls["tls"] = True

        def login(self, user, pw):
            calls["login"] = (user, pw)

        def send_message(self, msg):
            calls["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    email = EmailConfig(
        smtp_host="mail.local", from_addr="a@local", to="b@local", username="u", password="p"
    )
    send_digest(email, "Subject!", "Body.")
    assert calls["conn"] == ("mail.local", 587)
    assert calls["tls"] is True
    assert calls["login"] == ("u", "p")
    assert calls["msg"]["Subject"] == "Subject!"
    assert calls["msg"]["To"] == "b@local"


# -- jobs --------------------------------------------------------------


def test_monthly_job_builds_previous_month(tmp_path):
    config = write_config(tmp_path)
    story = monthly_job(config, now=datetime(2026, 2, 1, 6, 0, tzinfo=UTC))
    assert story["period"]["id"] == "2026-01"
    assert (tmp_path / "data" / "stories" / "2026-01.json").exists()
    assert any(c["fact"] == "media.total_hours" for c in story["cards"])


def test_monthly_job_january_rolls_year(tmp_path):
    config = write_config(tmp_path)
    story = monthly_job(config, now=datetime(2027, 1, 1, 6, 0, tzinfo=UTC))
    assert story["period"]["id"] == "2026-12"


def test_on_this_day_job(tmp_path):
    config = write_config(tmp_path)
    story = on_this_day_job(config, now=datetime(2027, 6, 1, 6, 0, tzinfo=UTC))
    assert story["period"]["id"] == "day-06-01"
    (card,) = story["cards"]  # Severance, 2025-06-01
    assert card["headline"] == "2 years ago today"


def test_jobs_email_only_when_cards_exist(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr("wrapped.core.schedule.send_digest", lambda *a: sent.append(a))
    config = write_config(tmp_path, "email:\n  smtp_host: m\n  from: a@l\n  to: b@l\n")
    on_this_day_job(config, now=datetime(2027, 6, 1, 6, 0, tzinfo=UTC))
    assert len(sent) == 1  # cards → emailed
    on_this_day_job(config, now=datetime(2027, 12, 25, 6, 0, tzinfo=UTC))
    assert len(sent) == 1  # no events that day → no email


def test_job_respects_timezone(tmp_path):
    # 2027-06-01 00:30 UTC is still 2027-05-31 in New York — the on-this-day
    # page must be for May 31, not June 1.
    config = write_config(tmp_path, "timezone: America/New_York\n")
    assert config.timezone == ZoneInfo("America/New_York")
    story = on_this_day_job(config, now=datetime(2027, 6, 1, 0, 30, tzinfo=UTC))
    assert story["period"]["id"] == "day-05-31"


def test_refresh_current_year_builds_story(tmp_path):
    from wrapped.core.schedule import refresh_current_year

    config = write_config(tmp_path)
    story = refresh_current_year(config, now=datetime(2026, 7, 18, tzinfo=UTC))
    assert story["period"]["id"] == "2026"
    assert (tmp_path / "data" / "stories" / "2026.json").exists()
    assert story["cards"]  # fixture events landed


def test_refresh_skips_without_connectors(tmp_path):
    from wrapped.core.config import load_config
    from wrapped.core.schedule import refresh_current_year

    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"database: {tmp_path}/e.db\n")
    assert refresh_current_year(load_config(cfg)) is None


def test_refresh_never_raises_on_broken_connector(tmp_path):
    from wrapped.core.schedule import refresh_current_year

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"database: {tmp_path}/e.db\nconnectors:\n  bad:\n    type: generic_csv\n"
        "    path: /nope/absent.csv\n"
    )
    from wrapped.core.config import load_config

    assert refresh_current_year(load_config(cfg)) is None  # logged, not raised


def test_background_scheduler_none_without_jobs(tmp_path):
    from wrapped.core.schedule import start_background_scheduler

    assert start_background_scheduler(write_config(tmp_path)) is None


def test_background_scheduler_runs_enabled_jobs(tmp_path):
    from wrapped.core.schedule import start_background_scheduler

    config = write_config(tmp_path, "schedule:\n  monthly_recap: true\n  on_this_day: true\n")
    scheduler = start_background_scheduler(config)
    try:
        assert sorted(j.name for j in scheduler.get_jobs()) == ["monthly-recap", "on-this-day"]
        assert scheduler.running
    finally:
        scheduler.shutdown(wait=False)


def test_run_scheduler_refuses_empty_config(tmp_path):
    config = write_config(tmp_path)
    with pytest.raises(ValueError, match="no scheduled jobs"):
        run_scheduler(config)
