"""Scheduled jobs: monthly recaps and On This Day, via APScheduler 3.x.

``wrapped schedule`` runs a blocking scheduler — this is the long-running mode
for people who keep the container up year-round. Each job syncs, builds, saves
the story (so it appears in the web UI), and optionally emails a digest.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from wrapped.core.config import AppConfig
from wrapped.core.digest import render_digest, send_digest
from wrapped.core.events import EventStore
from wrapped.core.story import Period, build_story, save_story
from wrapped.core.sync import sync_all

log = logging.getLogger("wrapped.schedule")


def _run(config: AppConfig, period: Period, email_if: bool, now: datetime) -> dict:
    """Sync, build and save one story; email it when configured and non-empty."""
    config.database.parent.mkdir(parents=True, exist_ok=True)
    store = EventStore(config.database)
    try:
        sync_all(config, store)
        story = build_story(store, period, config.timezone, now=now)
    finally:
        store.close()
    save_story(config.database.parent / "stories", story)
    log.info("built %s (%d cards)", story["period"]["label"], len(story["cards"]))
    if email_if and config.email is not None and story["cards"]:
        send_digest(config.email, *render_digest(story))
        log.info("emailed digest to %s", config.email.to)
    return story


def monthly_job(config: AppConfig, now: datetime | None = None) -> dict:
    """Build last month's recap (runs on the 1st of each month)."""
    now = now or datetime.now(tz=config.timezone)
    last_month = now.astimezone(config.timezone).date().replace(day=1) - timedelta(days=1)
    period = Period("month", year=last_month.year, month=last_month.month)
    return _run(config, period, email_if=True, now=now)


def on_this_day_job(config: AppConfig, now: datetime | None = None) -> dict:
    """Build today's On This Day page (runs daily)."""
    now = now or datetime.now(tz=config.timezone)
    today = now.astimezone(config.timezone).date()
    period = Period("day", month=today.month, day=today.day)
    return _run(config, period, email_if=True, now=now)


def run_scheduler(config: AppConfig) -> None:
    """Start the blocking scheduler with the jobs enabled in config.

    Raises:
        ValueError: If no jobs are enabled — a silent do-nothing scheduler
            helps nobody.
    """
    from apscheduler.schedulers.blocking import BlockingScheduler

    if not (config.schedule.monthly_recap or config.schedule.on_this_day):
        raise ValueError(
            "no scheduled jobs enabled — set schedule.monthly_recap or schedule.on_this_day"
        )

    scheduler = BlockingScheduler(timezone=config.timezone)
    hour = config.schedule.hour
    if config.schedule.monthly_recap:
        scheduler.add_job(
            monthly_job, "cron", day=1, hour=hour, args=[config], name="monthly-recap"
        )
    if config.schedule.on_this_day:
        scheduler.add_job(on_this_day_job, "cron", hour=hour, args=[config], name="on-this-day")
    log.info("scheduler running (%s)", ", ".join(str(j.name) for j in scheduler.get_jobs()))
    scheduler.start()
