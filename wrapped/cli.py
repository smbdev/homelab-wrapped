"""The ``wrapped`` command line: sync | build | serve | purge."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from wrapped.core.config import create_starter_config, load_config
from wrapped.core.events import EventStore
from wrapped.core.story import Period, build_story, save_story
from wrapped.core.sync import sync_all
from wrapped.facts import plural


def _parse_period(args) -> Period:
    """Turn build-command flags into a :class:`Period` (current year by default)."""
    if args.month:
        year, month = args.month.split("-")
        return Period("month", year=int(year), month=int(month))
    if args.on_this_day:
        if args.on_this_day == "today":
            today = datetime.now()
            return Period("day", month=today.month, day=today.day)
        month, day = args.on_this_day.split("-")
        return Period("day", month=int(month), day=int(day))
    return Period("year", year=args.year or datetime.now().year)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``wrapped`` command.

    Args:
        argv: Argument list, defaulting to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(prog="wrapped", description="Your homelab's year, wrapped.")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sync", help="collect new events from all configured connectors")
    build = sub.add_parser("build", help="build and save a recap story")
    when = build.add_mutually_exclusive_group()
    when.add_argument("--year", type=int, help="calendar year (default: current year)")
    when.add_argument("--month", metavar="YYYY-MM", help="calendar month, e.g. 2026-03")
    when.add_argument(
        "--on-this-day",
        nargs="?",
        const="today",
        metavar="MM-DD",
        help="on-this-day page for a calendar day (default: today)",
    )
    serve = sub.add_parser("serve", help="serve the story player web UI")
    serve.add_argument("--host", default="127.0.0.1", help="bind address (default: local only)")
    serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("schedule", help="run the scheduler (monthly recaps, on-this-day)")
    purge = sub.add_parser("purge", help="wipe the local event cache")
    purge.add_argument("--source", help="only purge this connector instance")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        if args.command == "serve":
            # First run: create a starter config so a fresh Docker volume
            # boots into a working app the user can then configure.
            config = create_starter_config(args.config)
            print(f"Created starter config at {args.config} — edit it to add your services.")
        else:
            print(f"Config file not found: {args.config}", file=sys.stderr)
            return 1
    except ValueError as exc:
        print(f"Invalid config: {exc}", file=sys.stderr)
        return 1

    config.database.parent.mkdir(parents=True, exist_ok=True)
    store = EventStore(config.database)
    try:
        if args.command == "sync":
            try:
                counts = sync_all(config, store)
            except ValueError as exc:
                print(f"Sync failed: {exc}", file=sys.stderr)
                return 1
            for name, n in counts.items():
                print(f"{name}: {n} new events")
            if not counts:
                print("No connectors configured — add some to config.yaml.")
        elif args.command == "build":
            try:
                period = _parse_period(args)
            except ValueError as exc:
                print(f"Invalid period: {exc}", file=sys.stderr)
                return 1
            story = build_story(store, period, config.timezone)
            path = save_story(config.database.parent / "stories", story)
            n_cards = plural(len(story["cards"]), "card")
            print(f"Built '{story['period']['label']}' — {n_cards} → {path}")
        elif args.command == "serve":
            import threading

            import uvicorn

            from wrapped.core.schedule import refresh_current_year, start_background_scheduler
            from wrapped.web import create_app

            store.close()  # serve reads stories from disk, not the event db
            scheduler = start_background_scheduler(config)  # None unless jobs enabled
            if scheduler:
                print("Scheduler active:", ", ".join(j.name for j in scheduler.get_jobs()))
            if config.connectors:
                # Sync + build this year's recap in the background on startup,
                # so "edit config, restart, open browser" is the whole flow.
                threading.Thread(target=refresh_current_year, args=(config,), daemon=True).start()
                print("Syncing and building this year's recap in the background…")
            app = create_app(config.database.parent / "stories", config_path=args.config)
            uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
        elif args.command == "schedule":
            import logging

            from wrapped.core.schedule import run_scheduler

            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
            store.close()  # jobs open their own store per run
            try:
                run_scheduler(config)
            except ValueError as exc:
                print(f"Cannot start scheduler: {exc}", file=sys.stderr)
                return 1
        elif args.command == "purge":
            n = store.purge(source=args.source)
            print(f"Purged {n} events.")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
