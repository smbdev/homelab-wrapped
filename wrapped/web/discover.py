"""Service discovery over the Docker socket, for the Settings scan button.

Reads ``/var/run/docker.sock`` (an **opt-in, read-only** mount — see README)
to find containers running services we have connectors for, and turns them
into prefilled suggestions. Local socket only; the privacy promise holds —
nothing leaves the machine, and without the mount this module reports
unavailable instead of failing.
"""

from __future__ import annotations

import http.client
import json
import socket
from pathlib import Path
from typing import Any

SOCKET_PATH = "/var/run/docker.sock"

# ponytail: discovery signatures live here while there are two of them;
# move onto the connector classes when the list grows.
_JELLYFIN_MOUNT_TARGET = "/jellyfin-data"


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str) -> None:
        super().__init__("localhost", timeout=10)
        self._path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect(self._path)
        self.sock = sock


def docker_available() -> bool:
    """True when the Docker socket is mounted into this environment."""
    return Path(SOCKET_PATH).is_socket()


def _docker_get(path: str) -> Any:
    conn = _UnixHTTPConnection(SOCKET_PATH)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        if resp.status != 200:
            raise OSError(f"Docker API returned {resp.status} for {path}")
        return json.load(resp)
    finally:
        conn.close()


def _public_port(container: dict, private: int) -> int | None:
    ports = container.get("Ports") or []
    for p in ports:
        if p.get("PrivatePort") == private and p.get("PublicPort"):
            return p["PublicPort"]
    for p in ports:  # fall back to any published port
        if p.get("PublicPort"):
            return p["PublicPort"]
    return None


def _config_mount(container: dict) -> str | None:
    for m in container.get("Mounts") or []:
        if m.get("Destination", "").rstrip("/") == "/config" and m.get("Source"):
            return m["Source"]
    return None


def scan() -> list[dict[str, Any]]:
    """Return connector suggestions for recognised running containers.

    Each suggestion: ``type`` and ``name`` for the add form, ``fields`` to
    prefill, ``ready`` (everything needed is prefilled or just a secret away),
    ``port`` for the browser to compose a URL from its own hostname, and a
    human ``note`` explaining any remaining step.
    """
    suggestions = []
    for c in _docker_get("/containers/json"):
        image = c.get("Image", "")
        name = (c.get("Names") or ["/unknown"])[0].lstrip("/")

        if "jellyfin" in image.lower() or name.lower() == "jellyfin":
            in_container = f"{_JELLYFIN_MOUNT_TARGET}/data/playback_reporting.db"
            host_config = _config_mount(c)
            if Path(in_container).exists():
                note = "Found its database — ready to add."
                ready = True
            elif host_config:
                note = (
                    f"Mount Jellyfin's config into this container first: add "
                    f"-v {host_config}:{_JELLYFIN_MOUNT_TARGET}:ro to Homelab Wrapped, "
                    "then add this service."
                )
                ready = False
            else:
                note = (
                    "Mount Jellyfin's config folder into this container as "
                    f"{_JELLYFIN_MOUNT_TARGET} (read-only), then add this service."
                )
                ready = False
            suggestions.append(
                {
                    "type": "jellyfin",
                    "name": name,
                    "fields": {"db_path": in_container},
                    "port": None,
                    "ready": ready,
                    "note": note,
                }
            )
        elif "immich-server" in image.lower() or "immich_server" in name.lower():
            port = _public_port(c, 2283)
            suggestions.append(
                {
                    "type": "immich",
                    "name": "immich",
                    "fields": {},
                    "port": port,
                    "ready": port is not None,
                    "note": "Paste an API key from Immich → Account Settings → API Keys.",
                }
            )
    return suggestions
