"""The connector plugin interface.

A connector is one self-contained module in ``wrapped/connectors/`` exposing a
module-level ``CONNECTOR`` instance that satisfies :class:`Connector`. It must
not import other connectors and must not make network calls outside its
configured base URL (CI enforces this with the network-allowlist fixture).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from wrapped.core.events import Event

Config = dict[str, Any]


@dataclass(frozen=True)
class ConfigField:
    """One config.yaml key a connector needs.

    Attributes:
        key: The key name under the connector's config block.
        description: Human explanation shown in docs and error messages.
        required: Whether ``test``/``collect`` can run without it.
    """

    key: str
    description: str
    required: bool = True


@dataclass(frozen=True)
class ConnectionResult:
    """Outcome of a connectivity/config check, shown to the user verbatim."""

    ok: bool
    message: str


@dataclass(frozen=True)
class FactSpec:
    """A recap fact this connector can feed, e.g. ``media.top_shows``."""

    id: str
    description: str


@runtime_checkable
class Connector(Protocol):
    """The plugin interface every connector implements."""

    id: str
    name: str
    schema: list[ConfigField]

    def test(self, cfg: Config) -> ConnectionResult:
        """Check config and connectivity without writing anything anywhere."""
        ...

    def collect(self, cfg: Config, since: datetime, until: datetime) -> Iterator[Event]:
        """Yield normalised events with ``since <= ts < until``."""
        ...

    def facts(self) -> list[FactSpec]:
        """Declare which recap facts this source can populate."""
        ...


def missing_required(schema: list[ConfigField], cfg: Config) -> list[str]:
    """Return the required config keys absent from ``cfg``, in schema order."""
    return [f.key for f in schema if f.required and not cfg.get(f.key)]
