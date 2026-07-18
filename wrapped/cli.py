"""The ``wrapped`` command line: sync | build | serve | purge."""

from __future__ import annotations

import argparse
import sys

from wrapped.core.config import load_config
from wrapped.core.events import EventStore
from wrapped.core.sync import sync_all


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
    sub.add_parser("build", help="build a recap story (arrives in M2)")
    sub.add_parser("serve", help="serve the story player web UI (arrives in M3)")
    purge = sub.add_parser("purge", help="wipe the local event cache")
    purge.add_argument("--source", help="only purge this connector instance")
    args = parser.parse_args(argv)

    if args.command in ("build", "serve"):
        print(f"'{args.command}' is not implemented yet — coming in a later milestone.")
        return 2

    try:
        config = load_config(args.config)
    except FileNotFoundError:
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
        elif args.command == "purge":
            n = store.purge(source=args.source)
            print(f"Purged {n} events.")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
