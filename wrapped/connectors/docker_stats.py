"""Docker stats connector: network traffic + container counts from the socket.

Reads the same read-only ``/var/run/docker.sock`` mount the Settings scan
uses — no credentials, nothing leaves the machine. Each sync stores one
*sample* per running container (cumulative rx/tx byte counters) plus one
container-count sample; the network facts turn successive samples into
daily deltas, so restarts (counter resets) never produce negative traffic.
"""

from __future__ import annotations

import http.client
import json
import socket
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from wrapped.connectors.base import Config, ConfigField, ConnectionResult, FactSpec
from wrapped.core.events import Event

DEFAULT_SOCKET = "/var/run/docker.sock"


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str) -> None:
        super().__init__("localhost", timeout=10)
        self._path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect(self._path)
        self.sock = sock


def docker_get(path: str, socket_path: str = DEFAULT_SOCKET) -> Any:
    """GET a Docker API path over the local unix socket."""
    conn = _UnixHTTPConnection(socket_path)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        if resp.status != 200:
            raise OSError(f"Docker API returned {resp.status} for {path}")
        return json.load(resp)
    finally:
        conn.close()


def service_name(container: dict) -> str:
    """Human service name: the compose service label ("caddy") beats the
    generated container name ("caddy-caddy-1"); prettified for cards."""
    labels = container.get("Labels") or {}
    raw = labels.get("com.docker.compose.service") or (container.get("Names") or ["/unknown"])[
        0
    ].lstrip("/")
    return raw.replace("_", " ").title()


def _net_totals(stats: dict) -> tuple[int, int]:
    rx = tx = 0
    for iface in (stats.get("networks") or {}).values():
        rx += int(iface.get("rx_bytes", 0))
        tx += int(iface.get("tx_bytes", 0))
    return rx, tx


class DockerStatsConnector:
    """Samples per-container network counters and the running-container count."""

    id = "docker_stats"
    name = "This server (Docker)"
    schema = [
        ConfigField(
            "socket_path",
            f"Docker socket path (default: {DEFAULT_SOCKET})",
            required=False,
        ),
    ]

    def _socket(self, cfg: Config) -> str:
        return cfg.get("socket_path") or DEFAULT_SOCKET

    def test(self, cfg: Config) -> ConnectionResult:
        path = self._socket(cfg)
        if not Path(path).is_socket():
            return ConnectionResult(
                False,
                f"No Docker socket at {path} — mount it read-only: "
                "-v /var/run/docker.sock:/var/run/docker.sock:ro",
            )
        try:
            containers = docker_get("/containers/json", path)
        except OSError as exc:
            return ConnectionResult(False, f"Could not read Docker: {exc}")
        return ConnectionResult(True, f"OK — {len(containers)} running containers visible.")

    def collect(self, cfg: Config, since: datetime, until: datetime) -> Iterator[Event]:
        """Emit one point-in-time sample per running container, stamped ``until``.

        Samples are cumulative byte counters; the facts layer diffs
        consecutive samples per container, treating a shrinking counter as a
        restart (delta = new value, not negative).
        """
        path = self._socket(cfg)
        containers = docker_get("/containers/json", path)
        for c in containers:
            name = service_name(c)
            try:
                stats = docker_get(f"/containers/{c['Id']}/stats?stream=false&one-shot=true", path)
            except OSError:
                continue  # a single vanished container shouldn't kill the sync
            rx, tx = _net_totals(stats)
            yield Event(
                source="docker",
                kind="net.sample",
                ts=until,
                entity=name,
                value=float(rx + tx),
                meta={"rx": rx, "tx": tx},
            )
        yield Event(
            source="docker",
            kind="system.containers",
            ts=until,
            value=float(len(containers)),
        )

    def facts(self) -> list[FactSpec]:
        return [
            FactSpec("network.total", "Total bytes moved by your containers"),
            FactSpec("network.by_service", "Traffic per service"),
            FactSpec("system.containers", "Running container count"),
        ]


CONNECTOR = DockerStatsConnector()
