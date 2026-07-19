"""The web UI: a FastAPI app serving the story player.

Two pages (index, player) rendered from Jinja templates, story JSON inlined
into the player shell (no fetch, no loading state), and self-contained static
assets — no CDNs, no webfonts, no build step. The privacy promise applies to
the frontend too: the pages make zero external requests.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from wrapped.core.story import list_stories, load_story
from wrapped.facts import plural

_HERE = Path(__file__).parent


def create_app(stories_dir: str | Path, config_path: str | Path | None = None) -> FastAPI:
    """Build the FastAPI app serving recaps from a stories directory.

    Args:
        stories_dir: Directory of saved ``<period-id>.json`` story specs.
        config_path: The config.yaml the Settings page manages; without it
            the Settings page is disabled (read-only deployments, tests).

    Returns:
        The configured application.
    """
    stories_dir = Path(stories_dir)
    app = FastAPI(title="Homelab Wrapped", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.auth_mode = "off"  # no config file → read-only deployment, no auth
    app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")
    templates = Jinja2Templates(directory=_HERE / "templates")

    if config_path is not None:
        from wrapped.core.config import load_config
        from wrapped.web.auth import add_auth
        from wrapped.web.settings import add_settings_routes

        config_path = Path(config_path)
        try:
            auth_mode = load_config(config_path).auth
        except (FileNotFoundError, ValueError):
            auth_mode = "local"
        add_auth(app, templates, config_path.parent / "auth.json", auth_mode)
        add_settings_routes(app, templates, config_path)

    def story_index() -> list[dict]:
        entries = []
        for period_id in list_stories(stories_dir):
            try:
                story = load_story(stories_dir, period_id)
            except (OSError, json.JSONDecodeError):
                continue  # a corrupt file shouldn't take down the index
            cards = story.get("cards", [])
            entries.append(
                {
                    "id": period_id,
                    "label": story["period"]["label"],
                    "kind": {"year": "yearly", "month": "monthly", "day": "on this day"}.get(
                        story["period"].get("type", ""), "recap"
                    ),
                    "n_cards": plural(len(cards), "chapter"),
                    "minutes": max(1, round(len(cards) * 12 / 60)),
                    "cards": cards,
                }
            )
        # yearly recaps lead (newest first), monthlies follow, on-this-day
        # last — the first entry is the dashboard's featured card; two
        # stable sorts do it
        entries.sort(key=lambda e: e["id"], reverse=True)
        entries.sort(key=lambda e: {"yearly": 0, "monthly": 1}.get(e["kind"], 2))
        return entries

    def dashboard_extras(stories: list[dict]) -> dict:
        """Stat strip + ticker for the hub, from real facts only (no card data
        leaves this function for private cards — same redaction rule as export)."""
        stats: list[dict] = [{"value": len(stories), "unit": "", "label": "recaps"}]
        if config_path is not None:
            try:
                from wrapped.core.config import load_config

                stats.insert(
                    0,
                    {
                        "value": len(load_config(config_path).connectors),
                        "unit": "",
                        "label": "services",
                    },
                )
            except (FileNotFoundError, ValueError):
                pass
        ticker: list[str] = []
        if stories:
            public = [c for c in stories[0]["cards"] if not c.get("private")]
            for card in public:
                if card.get("fact") == "media.total_hours" and card.get("value"):
                    stats.append({"value": card["value"], "unit": "h", "label": "watched"})
                if card.get("headline"):
                    ticker.append(card["headline"])
        return {"stats": stats, "ticker": ticker}

    def hub_slots(stories: list[dict]) -> dict:
        """The hub's three bottom cards: featured recap + latest monthly +
        latest on-this-day; a missing kind renders as a greyed placeholder."""
        featured = stories[0] if stories else None
        rest = [s for s in stories if s is not featured]
        return {
            "featured": featured,
            "monthly": next((s for s in rest if s["kind"] == "monthly"), None),
            "otd": next((s for s in rest if s["kind"] == "on this day"), None),
        }

    has_settings = config_path is not None

    def index_context() -> dict:
        """Everything index.html needs — also used by the story-404 page."""
        stories = story_index()
        return {
            "stories": stories,
            "has_settings": has_settings,
            "today": f"{datetime.now():%-d %b}".upper(),
            "month_label": f"{datetime.now():%B}",
            **hub_slots(stories),
            **dashboard_extras(stories),
        }

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html", index_context())

    @app.get("/story/{period_id}", response_class=HTMLResponse)
    def story_page(request: Request, period_id: str) -> HTMLResponse:
        try:
            story = load_story(stories_dir, period_id)
        except (OSError, json.JSONDecodeError):
            return templates.TemplateResponse(
                request,
                "index.html",
                {**index_context(), "missing": period_id},
                status_code=404,
            )
        return templates.TemplateResponse(request, "story.html", {"story": story})

    @app.get("/api/stories")
    def api_stories() -> list[dict[str, str]]:
        return [{"id": e["id"], "label": e["label"]} for e in story_index()]

    @app.get("/api/stories/{period_id}")
    def api_story(period_id: str):
        try:
            return load_story(stories_dir, period_id)
        except (OSError, json.JSONDecodeError):
            return JSONResponse({"error": f"no story {period_id!r}"}, status_code=404)

    return app
