"""The Settings page: connect, scan, test, and maintain services from the browser.

Forms are parsed with stdlib ``urllib.parse`` (no multipart dependency), the
add flow validates against each plugin's declared schema, runs the plugin's
own ``test()``, writes config.yaml, and kicks off a background sync+build —
so adding a service never requires a shell, an editor, or a restart.

Connector health lives in ``status.json`` next to config.yaml: the result of
the last connection test per connector. "Synced Nm ago" comes from the event
store's sync_state table.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from wrapped.connectors import all_connectors
from wrapped.connectors.base import missing_required
from wrapped.core.config import add_connector, load_config, remove_connector
from wrapped.core.events import EventStore
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


def _ago(ts: datetime) -> str:
    mins = max(0, int((datetime.now(tz=UTC) - ts).total_seconds() // 60))
    if mins < 60:
        return f"synced {mins}m ago"
    if mins < 48 * 60:
        return f"synced {mins // 60}h ago"
    return f"synced {mins // (24 * 60)}d ago"


class _Status:
    """Last connection-test result per connector, in status.json."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def set(self, name: str, ok: bool, message: str) -> None:
        data = self.load()
        data[name] = {"ok": ok, "message": message, "ts": time.time()}
        self.path.write_text(json.dumps(data))

    def drop(self, name: str) -> None:
        data = self.load()
        if data.pop(name, None) is not None:
            self.path.write_text(json.dumps(data))


def add_settings_routes(app: FastAPI, templates, config_path: Path) -> None:
    """Register the settings page and its form handlers on ``app``."""
    status = _Status(config_path.parent / "status.json")

    def last_synced(names: list[str]) -> dict[str, datetime]:
        try:
            db = load_config(config_path).database
        except (FileNotFoundError, ValueError):
            return {}
        if not Path(db).exists():
            return {}
        store = EventStore(db)
        try:
            return {n: ts for n in names if (ts := store.last_sync(n))}
        finally:
            store.close()

    @app.get("/settings")
    def settings(request: Request):
        try:
            configured = load_config(config_path).connectors
        except (FileNotFoundError, ValueError):
            configured = []
        tests = status.load()
        synced = last_synced([c.name for c in configured])
        rows = []
        for c in configured:
            t = tests.get(c.name)
            ok = t is None or t["ok"]
            if not ok:
                detail = t["message"]
            elif c.name in synced:
                detail = _ago(synced[c.name])
            else:
                detail = "not synced yet"
            rows.append({"name": c.name, "type": c.type, "ok": ok, "detail": detail})
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "configured": rows,
                "plugins": {
                    pid: {
                        "name": p.name,
                        "fields": [
                            {"key": f.key, "description": f.description, "required": f.required}
                            for f in p.schema
                        ],
                    }
                    for pid, p in sorted(all_connectors().items())
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
        status.set(name, result.ok, result.message)
        _refresh_in_background(config_path)
        if result.ok:
            return _back(f"Added “{name}” — {result.message} Building your recap now…")
        return _back(f"Added “{name}”, but its connection test failed: {result.message}", ok=False)

    @app.post("/settings/scan/add")
    async def scan_add(request: Request):
        """One-click add from a scan result: test first, only write config on success."""
        try:
            body = json.loads(await request.body())
        except json.JSONDecodeError:
            return JSONResponse({"ok": False, "error": "Bad request body."}, status_code=400)
        name = str(body.get("name", "")).strip()
        type_ = str(body.get("type", ""))
        fields = {str(k): str(v).strip() for k, v in (body.get("fields") or {}).items() if v}
        plugin = all_connectors().get(type_)
        if plugin is None:
            return JSONResponse({"ok": False, "error": f"Unknown service type {type_!r}."})
        missing = missing_required(plugin.schema, fields)
        if missing:
            return JSONResponse({"ok": False, "error": f"Missing: {', '.join(missing)}."})
        result = plugin.test(fields)
        if not result.ok:
            return JSONResponse({"ok": False, "error": result.message})
        try:
            add_connector(config_path, name, type_, fields)
        except (ValueError, OSError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        status.set(name, True, result.message)
        _refresh_in_background(config_path)
        return {"ok": True, "message": result.message}

    @app.post("/settings/connectors/{name}/retest")
    def retest(name: str):
        try:
            configured = load_config(config_path).connectors
        except (FileNotFoundError, ValueError) as exc:
            return _back(str(exc), ok=False)
        entry = next((c for c in configured if c.name == name), None)
        if entry is None:
            return _back(f"No connector called “{name}”.", ok=False)
        result = all_connectors()[entry.type].test(entry.cfg)
        status.set(name, result.ok, result.message)
        if result.ok:
            _refresh_in_background(config_path)
            return _back(f"“{name}” is back — {result.message} Syncing now…")
        return _back(f"“{name}” still failing: {result.message}", ok=False)

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
            result = discover.scan()
        except OSError as exc:
            return JSONResponse({"error": f"Could not read Docker: {exc}"}, status_code=502)
        # already-connected services aren't suggestions — they're in the list above
        configured = {c.type for c in load_config(config_path).connectors}
        result["found"] = [s for s in result["found"] if s["type"] not in configured]
        plugins = all_connectors()
        for s in result["found"]:
            # which required fields the browser can't derive (url comes from
            # the scanned port) — these expand the inline credential step
            schema = plugins[s["type"]].schema
            s["missing"] = [
                f.key
                for f in schema
                if f.required
                and f.key not in s["fields"]
                and not (f.key == "url" and s.get("port"))
            ]
            s["descriptions"] = {f.key: f.description for f in schema}
        return result

    @app.post("/settings/connectors/{name}/delete")
    def delete(name: str):
        try:
            remove_connector(config_path, name)
        except (ValueError, OSError) as exc:
            return _back(str(exc), ok=False)
        status.drop(name)
        return _back(f"Removed “{name}” — its credentials are gone, built recaps are kept.")

    @app.post("/settings/rebuild")
    def rebuild():
        _refresh_in_background(config_path)
        return _back("Rebuilding this year's recap in the background — refresh in a minute.")

    @app.post("/settings/purge")
    def purge():
        try:
            db = load_config(config_path).database
        except (FileNotFoundError, ValueError) as exc:
            return _back(str(exc), ok=False)
        store = EventStore(db)
        try:
            n = store.purge()
        finally:
            store.close()
        return _back(f"Purged {n} cached events. The next sync starts from scratch.")
