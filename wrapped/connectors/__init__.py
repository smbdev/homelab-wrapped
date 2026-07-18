"""Connector plugins and their discovery.

Drop a module in this package exposing a module-level ``CONNECTOR`` instance
and it becomes available in config.yaml — no core changes needed.
"""

from __future__ import annotations

import importlib
import pkgutil

from wrapped.connectors.base import Connector


def all_connectors() -> dict[str, Connector]:
    """Discover every connector plugin in this package.

    Returns:
        Mapping of connector id to its ``CONNECTOR`` instance.
    """
    out: dict[str, Connector] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_") or info.name == "base":
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        connector = getattr(module, "CONNECTOR", None)
        if connector is not None:
            out[connector.id] = connector
    return out
