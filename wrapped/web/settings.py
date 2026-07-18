"""The Settings page: add and remove connectors from the browser.

Forms are parsed with stdlib ``urllib.parse`` (no multipart dependency), the
add flow validates against each plugin's declared schema, runs the plugin's
own ``test()``, writes config.yaml, and kicks off a background sync+build —
so adding a service never requires a shell, an editor, or a restart.
"""

from __future__ import annotations

import threading
from pathlib import Path
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from wrapped.connectors import all_connectors
from wrapped.connectors.base import missing_required
from wrapped.core.config import add_connector, load_config, remove_connector
from wrapped.core.schedule import refresh_current_year


async def _form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode()
    return {k: v[0].strip() for k, v in parse_qs(body, keep_blank_values=True).items()}


def _refresh_in_background(config_path: Path) -> None:
    threading.Thread(
        target=lambda: refresh_current_year(load_config(config_path)), daemon=True
    ).start()


def _back(msg: str, ok: bool = True) -> RedirectResponse:
    return RedirectResponse(f"/settings?{'msg' if ok else 'err'}={quote(msg)}", status_code=303)


def add_settings_routes(app: FastAPI, templates, config_path: Path) -> None:
    """Register the settings page and its form handlers on ``app``."""

    @app.get("/settings")
    def settings(request: Request):
        plugins = all_connectors()
        try:
            configured = load_config(config_path).connectors
        except (FileNotFoundError, ValueError):
            configured = []
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "configured": [{"name": c.name, "type": c.type} for c in configured],
                "plugins": {
                    pid: {
                        "name": p.name,
                        "fields": [
                            {"key": f.key, "description": f.description, "required": f.required}
                            for f in p.schema
                        ],
                    }
                    for pid, p in sorted(plugins.items())
                },
                "msg": request.query_params.get("msg"),
                "err": request.query_params.get("err"),
            },
        )

    @app.post("/settings/connectors")
    async def add(request: Request):
        form = await _form(request)
        name, type_ = form.get("name", ""), form.get("type", "")
        plugin = all_connectors().get(type_)
        if plugin is None:
            return _back(f"Unknown service type {type_!r}.", ok=False)
        cfg = {f.key: form[f.key] for f in plugin.schema if form.get(f.key)}
        missing = missing_required(plugin.schema, cfg)
        if missing:
            return _back(f"Missing required fields: {', '.join(missing)}.", ok=False)
        try:
            add_connector(config_path, name, type_, cfg)
        except (ValueError, OSError) as exc:
            return _back(str(exc), ok=False)
        result = plugin.test(cfg)
        _refresh_in_background(config_path)
        if result.ok:
            return _back(f"Added “{name}” — {result.message} Building your recap now…")
        return _back(f"Added “{name}”, but its connection test failed: {result.message}", ok=False)

    @app.get("/settings/scan")
    def scan_services():
        from wrapped.web import discover

        if not discover.docker_available():
            return JSONResponse(
                {
                    "error": "Scanning needs read-only access to the Docker socket. Add "
                    "-v /var/run/docker.sock:/var/run/docker.sock:ro to this container "
                    "and restart, or add services manually below."
                },
                status_code=503,
            )
        try:
            return {"found": discover.scan()}
        except OSError as exc:
            return JSONResponse({"error": f"Could not read Docker: {exc}"}, status_code=502)

    @app.post("/settings/connectors/{name}/delete")
    def delete(name: str):
        try:
            remove_connector(config_path, name)
        except (ValueError, OSError) as exc:
            return _back(str(exc), ok=False)
        return _back(f"Removed “{name}”.")
