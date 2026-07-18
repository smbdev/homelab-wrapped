"""Immich connector — reads photo metadata over the Immich HTTP API.

Uses a read-only flow: ``GET /api/users/me`` to validate the key and paginated
``POST /api/search/metadata`` to list assets in the sync window. Only the
configured base URL is ever contacted (stdlib ``urllib``, no HTTP client
dependency), and only metadata is read — never image bytes.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from wrapped.connectors.base import Config, ConfigField, ConnectionResult, FactSpec
from wrapped.core.events import Event

_PAGE_SIZE = 1000


def _request(url: str, api_key: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET (payload=None) or POST JSON to the Immich API and decode the response."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — user-configured base URL
        return json.load(resp)


class ImmichConnector:
    """Reads photo/video capture events from an Immich server."""

    id = "immich"
    name = "Immich"
    schema = [
        ConfigField("url", "Base URL of the Immich server, e.g. http://immich.local:2283"),
        ConfigField("api_key", "Immich API key (create a read-only one in account settings)"),
    ]

    def test(self, cfg: Config) -> ConnectionResult:
        """Validate the base URL and API key without touching any assets."""
        try:
            me = _request(f"{cfg['url'].rstrip('/')}/api/users/me", cfg["api_key"])
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            return ConnectionResult(False, f"Could not reach Immich at {cfg.get('url')}: {exc}")
        return ConnectionResult(True, f"OK — authenticated as {me.get('name', 'unknown')}")

    def collect(self, cfg: Config, since: datetime, until: datetime) -> Iterator[Event]:
        """Yield one ``photo.taken`` event per asset captured in the window."""
        base = cfg["url"].rstrip("/")
        page: int | str | None = 1
        while page:
            result = _request(
                f"{base}/api/search/metadata",
                cfg["api_key"],
                {
                    "takenAfter": since.astimezone(UTC).isoformat(),
                    "takenBefore": until.astimezone(UTC).isoformat(),
                    "page": int(page),
                    "size": _PAGE_SIZE,
                },
            )
            assets = result.get("assets", {})
            for asset in assets.get("items", []):
                try:
                    ts = datetime.fromisoformat(asset["fileCreatedAt"].replace("Z", "+00:00"))
                except (KeyError, ValueError):
                    continue  # assets without a capture time can't be placed in a recap
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if not (since <= ts < until):
                    continue
                city = (asset.get("exifInfo") or {}).get("city")
                yield Event(
                    source=self.id,
                    kind="photo.taken",
                    ts=ts,
                    entity=asset.get("originalFileName"),
                    entity_group=city,
                    meta={"asset_id": asset.get("id")},
                )
            page = assets.get("nextPage")

    def facts(self) -> list[FactSpec]:
        """Feeds the photo facts."""
        return [
            FactSpec("photos.total", "Photos taken"),
            FactSpec("photos.busiest_day", "Most photos in one day"),
        ]


CONNECTOR = ImmichConnector()
