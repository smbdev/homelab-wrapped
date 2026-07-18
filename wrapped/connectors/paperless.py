"""Paperless-ngx connector — reads document metadata over the REST API.

Read-only: ``GET /api/documents/`` filtered by the sync window and paginated,
plus one ``GET /api/correspondents/`` to resolve ids to names. Only the
configured base URL is ever contacted (stdlib ``urllib``, token auth), and
only metadata is read — never document contents.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from wrapped.connectors.base import Config, ConfigField, ConnectionResult, FactSpec
from wrapped.core.events import Event

_PAGE_SIZE = 250


def _request(url: str, token: str) -> dict[str, Any]:
    """GET a Paperless API URL and decode the JSON response."""
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Token {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — user-configured base URL
        return json.load(resp)


class PaperlessConnector:
    """Reads document-archived events from a Paperless-ngx server."""

    id = "paperless"
    name = "Paperless-ngx"
    schema = [
        ConfigField("url", "Base URL of Paperless-ngx, e.g. http://paperless.local:8000"),
        ConfigField("api_token", "Paperless API token (Settings → Django admin → Auth tokens)"),
    ]

    def test(self, cfg: Config) -> ConnectionResult:
        """Validate the URL and token by asking for a single document page."""
        base = cfg["url"].rstrip("/")
        try:
            data = _request(f"{base}/api/documents/?page_size=1", cfg["api_token"])
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            return ConnectionResult(False, f"Could not reach Paperless at {cfg.get('url')}: {exc}")
        return ConnectionResult(True, f"OK — {data.get('count', 0):,} documents in the archive")

    def collect(self, cfg: Config, since: datetime, until: datetime) -> Iterator[Event]:
        """Yield one ``doc.added`` event per document archived in the window."""
        base = cfg["url"].rstrip("/")
        token = cfg["api_token"]
        correspondents = self._correspondents(base, token)
        query = urllib.parse.urlencode(
            {
                "added__date__gt": since.date().isoformat(),
                "ordering": "added",
                "page_size": _PAGE_SIZE,
            }
        )
        url: str | None = f"{base}/api/documents/?{query}"
        while url:
            data = _request(url, token)
            for doc in data.get("results", []):
                try:
                    ts = datetime.fromisoformat(str(doc.get("added", "")))
                except ValueError:
                    continue
                if not (since <= ts < until):
                    continue
                who = correspondents.get(doc.get("correspondent"))
                yield Event(
                    source=self.id,
                    kind="doc.added",
                    ts=ts,
                    entity=doc.get("title"),
                    entity_group=who,
                    value=1.0,
                )
            url = data.get("next")

    def facts(self) -> list[FactSpec]:
        return [
            FactSpec("docs.total", "Documents archived"),
            FactSpec("docs.top_senders", "Who sent all that paper"),
        ]

    @staticmethod
    def _correspondents(base: str, token: str) -> dict[int, str]:
        """id → name for every correspondent; tolerated as empty on failure."""
        out: dict[int, str] = {}
        url: str | None = f"{base}/api/correspondents/?page_size={_PAGE_SIZE}"
        try:
            while url:
                data = _request(url, token)
                for c in data.get("results", []):
                    out[c["id"]] = c["name"]
                url = data.get("next")
        except (urllib.error.URLError, json.JSONDecodeError, OSError):
            return {}  # names are garnish; documents still count
        return out


CONNECTOR = PaperlessConnector()
