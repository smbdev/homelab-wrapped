"""Service discovery over the Docker socket, for the Settings scan button.

Reads ``/var/run/docker.sock`` (an **opt-in, read-only** mount — see README)
to find containers running services we have connectors for, and turns them
into prefilled suggestions. Local socket only; the privacy promise holds —
nothing leaves the machine, and without the mount this module reports
unavailable instead of failing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from wrapped.connectors.docker_stats import docker_get

SOCKET_PATH = "/var/run/docker.sock"

# ponytail: discovery signatures live here while there are two of them;
# move onto the connector classes when the list grows.
_JELLYFIN_MOUNT_TARGET = "/jellyfin-data"
_PIHOLE_MOUNT_TARGET = "/pihole-data"


def docker_available() -> bool:
    """True when the Docker socket is mounted into this environment."""
    return Path(SOCKET_PATH).is_socket()


def _public_port(container: dict, private: int) -> int | None:
    ports = container.get("Ports") or []
    for p in ports:
        if p.get("PrivatePort") == private and p.get("PublicPort"):
            return p["PublicPort"]
    for p in ports:  # fall back to any published port
        if p.get("PublicPort"):
            return p["PublicPort"]
    return None


def _mount_source(container: dict, destination: str) -> str | None:
    """Host path mounted at ``destination`` inside the scanned container."""
    for m in container.get("Mounts") or []:
        if m.get("Destination", "").rstrip("/") == destination and m.get("Source"):
            return m["Source"]
    return None


def scan() -> dict[str, Any]:
    """Return connector suggestions for recognised running containers.

    Returns ``found`` (suggestions) and ``unknown`` (running containers we
    have no connector for yet). Each suggestion: ``type`` and ``name`` for
    the add form, ``fields`` to prefill, ``ready`` (everything needed is
    prefilled or just a secret away), ``port`` for the browser to compose a
    URL from its own hostname, and a human ``note`` for any remaining step.
    """
    suggestions = [
        {
            "type": "docker_stats",
            "name": "this-server",
            "fields": {},
            "port": None,
            "ready": True,
            "note": "Network traffic and container counts from the Docker socket "
            "you already mounted — no credentials needed.",
        }
    ]
    unknown: list[str] = []
    for c in docker_get("/containers/json"):
        image = c.get("Image", "")
        name = (c.get("Names") or ["/unknown"])[0].lstrip("/")

        if "jellyfin" in image.lower() or name.lower() == "jellyfin":
            in_container = f"{_JELLYFIN_MOUNT_TARGET}/data/playback_reporting.db"
            host_config = _mount_source(c, "/config")
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
        elif "paperless" in image.lower():
            port = _public_port(c, 8000)
            suggestions.append(
                {
                    "type": "paperless",
                    "name": "paperless",
                    "fields": {},
                    "port": port,
                    "ready": port is not None,
                    "note": "Paste an API token from Paperless → your username → My Profile.",
                }
            )
        elif "nextcloud" in image.lower() or name.lower() == "nextcloud":
            port = _public_port(c, 80)
            suggestions.append(
                {
                    "type": "nextcloud",
                    "name": "nextcloud",
                    "fields": {},
                    "port": port,
                    "ready": port is not None,
                    "note": "Paste your login and an app password from Nextcloud → "
                    "Settings → Security → Devices & sessions.",
                }
            )
        elif "pihole" in image.lower() or name.lower() == "pihole":
            in_container = f"{_PIHOLE_MOUNT_TARGET}/pihole-FTL.db"
            host_etc = _mount_source(c, "/etc/pihole")
            if Path(in_container).exists():
                note = "Found its query database — ready to add."
                ready = True
            elif host_etc:
                note = (
                    f"Mount Pi-hole's /etc/pihole into this container first: add "
                    f"-v {host_etc}:{_PIHOLE_MOUNT_TARGET}:ro to Homelab Wrapped, "
                    "then add this service."
                )
                ready = False
            else:
                note = (
                    "Mount Pi-hole's /etc/pihole folder into this container as "
                    f"{_PIHOLE_MOUNT_TARGET} (read-only), then add this service."
                )
                ready = False
            suggestions.append(
                {
                    "type": "pihole",
                    "name": name,
                    "fields": {"db_path": in_container},
                    "port": None,
                    "ready": ready,
                    "note": note,
                }
            )
        elif "homelab-wrapped" not in image:  # don't report ourselves as a mystery
            unknown.append(name)
    return {"found": suggestions, "unknown": sorted(unknown)}
