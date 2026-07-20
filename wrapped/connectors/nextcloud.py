"""Nextcloud connector — reads file activity over the OCS Activity API.

Read-only: pages ``GET /ocs/v2.php/apps/activity/api/v2/activity`` newest
first, plus one ``GET /ocs/v2.php/cloud/users/{username}`` for a storage-used
snapshot. Only the configured base URL is ever contacted (stdlib ``urllib``,
Basic auth with an app password), and only metadata is read — never file
contents.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from wrapped.connectors.base import Config, ConfigField, ConnectionResult, FactSpec
from wrapped.core.events import Event

_PAGE_SIZE = 200
# Only types a fact actually consumes. Storing anything else fills the event
# cache with rows nothing ever reads — add the fact first, then the mapping.
_KINDS = {"file_created": "file.created"}


def _request(url: str, username: str, password: str) -> tuple[int, dict[str, Any] | None]:
    """GET an OCS URL; return ``(status, body)`` with body None on 204/304."""
    creds = base64.b64encode(f"{username}:{password}".encode()).decode()
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Basic {creds}",
            "OCS-APIRequest": "true",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — user-configured base URL
            if resp.status == 204:  # no activities recorded at all
                return 204, None
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 304:  # nothing newer than the `since` cursor
            return 304, None
        raise


def _folder(path: str) -> str:
    """Top-level folder of a Nextcloud path; files in the root get ``/``."""
    parts = path.strip("/").split("/")
    return parts[0] if len(parts) > 1 else "/"


class NextcloudConnector:
    """Reads file-created events and a storage snapshot from Nextcloud."""

    id = "nextcloud"
    name = "Nextcloud"
    schema = [
        ConfigField("url", "Base URL of Nextcloud, e.g. http://nextcloud.local:8080"),
        ConfigField("username", "Nextcloud login name"),
        ConfigField(
            "app_password",
            "App password — create one under Personal settings → Security → "
            "Devices & sessions → Create new app password",
        ),
    ]

    def test(self, cfg: Config) -> ConnectionResult:
        """Validate URL, credentials, and the Activity app in one call."""
        base = cfg["url"].rstrip("/")
        url = f"{base}/ocs/v2.php/apps/activity/api/v2/activity?format=json&limit=1"
        try:
            status, data = _request(url, cfg["username"], cfg["app_password"])
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            return ConnectionResult(False, f"Could not reach Nextcloud at {cfg.get('url')}: {exc}")
        if data is None:
            return ConnectionResult(True, "OK — reachable, no activity recorded yet")
        return ConnectionResult(True, f"OK — Activity API reachable as {cfg['username']}")

    def collect(self, cfg: Config, since: datetime, until: datetime) -> Iterator[Event]:
        """Yield file events in the window, then one ``storage.used`` sample."""
        base = cfg["url"].rstrip("/")
        user, password = cfg["username"], cfg["app_password"]
        cursor: Any = None
        while True:
            url = f"{base}/ocs/v2.php/apps/activity/api/v2/activity?format=json&limit={_PAGE_SIZE}"
            if cursor is not None:
                url += f"&since={cursor}"
            _, data = _request(url, user, password)
            entries = data.get("ocs", {}).get("data", []) if data else []
            if not entries:
                break
            oldest = None
            for act in entries:
                try:
                    ts = datetime.fromisoformat(str(act.get("datetime", "")))
                except ValueError:
                    continue
                oldest = ts
                kind = _KINDS.get(act.get("type"))
                if kind is None or not (since <= ts < until):
                    continue
                path = str(act.get("object_name") or "")
                yield Event(
                    source=self.id,
                    kind=kind,
                    ts=ts,
                    entity=path.rsplit("/", 1)[-1] or None,
                    entity_group=_folder(path),
                    value=1.0,
                )
            cursor = entries[-1].get("activity_id")
            if cursor is None or len(entries) < _PAGE_SIZE or (oldest and oldest < since):
                break
        used = self._quota_used(base, user, password)
        if used:
            yield Event(source=self.id, kind="storage.used", ts=until, value=used)

    def facts(self) -> list[FactSpec]:
        return [
            FactSpec("files.total", "Files added to your cloud"),
            FactSpec("files.top_folders", "Where they all went"),
            FactSpec("storage.growth", "How much your cloud grew"),
        ]

    @staticmethod
    def _quota_used(base: str, user: str, password: str) -> float:
        """Bytes used per the user's quota; 0 on failure (snapshot is garnish)."""
        try:
            _, data = _request(f"{base}/ocs/v2.php/cloud/users/{user}?format=json", user, password)
            quota = (data or {}).get("ocs", {}).get("data", {}).get("quota") or {}
            return float(quota.get("used", 0))
        except (urllib.error.URLError, json.JSONDecodeError, OSError, TypeError, ValueError):
            return 0.0  # activity events still count


CONNECTOR = NextcloudConnector()
