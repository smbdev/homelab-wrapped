"""Docker stats connector: network traffic + container counts from the socket.

Reads the same read-only ``/var/run/docker.sock`` mount the Settings scan
uses — no credentials, nothing leaves the machine.

Each sync stores, per running container, a network sample (cumulative rx/tx
byte counters), a CPU-time sample (also cumulative), a memory gauge and the
container's creation stamp, plus one container-count sample. The facts layer
turns successive counter samples into deltas, so restarts (counter resets)
never produce negative usage.

The stats API call was already being made for network bytes and returns CPU
and memory in the same payload, so the extra kinds cost no additional
requests — only rows: four samples per container per sync instead of one.
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


def _cpu_nanoseconds(stats: dict) -> float | None:
    """Cumulative CPU time this container has used, in nanoseconds.

    Not a percentage: a one-shot stats read has no previous sample to
    compare against (``precpu_stats`` comes back zeroed), so an instant
    CPU% is not computable here. The raw counter is better anyway — the
    facts layer diffs it into "hours of CPU burned this year", which is a
    total worth putting on a card rather than a gauge worth graphing.
    """
    total = ((stats.get("cpu_stats") or {}).get("cpu_usage") or {}).get("total_usage")
    return float(total) if total else None


def _memory_bytes(stats: dict) -> float | None:
    """Current memory in use, or None when the runtime didn't report it."""
    usage = (stats.get("memory_stats") or {}).get("usage")
    return float(usage) if usage else None


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
            cpu = _cpu_nanoseconds(stats)
            if cpu is not None:
                yield Event(source="docker", kind="system.cpu", ts=until, entity=name, value=cpu)
            memory = _memory_bytes(stats)
            if memory is not None:
                yield Event(
                    source="docker", kind="system.memory", ts=until, entity=name, value=memory
                )
            created = c.get("Created")
            if created:
                # The creation stamp itself, not an age — an absolute value
                # stays true whichever window a recap later asks about.
                yield Event(
                    source="docker",
                    kind="system.container_started",
                    ts=until,
                    entity=name,
                    value=float(created),
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
            FactSpec("system.oldest_container", "Your longest-serving container"),
        ]


CONNECTOR = DockerStatsConnector()
