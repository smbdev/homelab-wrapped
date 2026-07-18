"""The web UI: a FastAPI app serving the story player.

Two pages (index, player) rendered from Jinja templates, story JSON inlined
into the player shell (no fetch, no loading state), and self-contained static
assets — no CDNs, no webfonts, no build step. The privacy promise applies to
the frontend too: the pages make zero external requests.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from wrapped.core.story import list_stories, load_story

_HERE = Path(__file__).parent


def create_app(stories_dir: str | Path) -> FastAPI:
    """Build the FastAPI app serving recaps from a stories directory.

    Args:
        stories_dir: Directory of saved ``<period-id>.json`` story specs.

    Returns:
        The configured application.
    """
    stories_dir = Path(stories_dir)
    app = FastAPI(title="Homelab Wrapped", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")
    templates = Jinja2Templates(directory=_HERE / "templates")

    def story_index() -> list[dict[str, str]]:
        entries = []
        for period_id in list_stories(stories_dir):
            try:
                story = load_story(stories_dir, period_id)
            except (OSError, json.JSONDecodeError):
                continue  # a corrupt file shouldn't take down the index
            entries.append({"id": period_id, "label": story["period"]["label"]})
        return entries

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html", {"stories": story_index()})

    @app.get("/story/{period_id}", response_class=HTMLResponse)
    def story_page(request: Request, period_id: str) -> HTMLResponse:
        try:
            story = load_story(stories_dir, period_id)
        except (OSError, json.JSONDecodeError):
            return templates.TemplateResponse(
                request,
                "index.html",
                {"stories": story_index(), "missing": period_id},
                status_code=404,
            )
        return templates.TemplateResponse(request, "story.html", {"story": story})

    @app.get("/api/stories")
    def api_stories() -> list[dict[str, str]]:
        return story_index()

    @app.get("/api/stories/{period_id}")
    def api_story(period_id: str):
        try:
            return load_story(stories_dir, period_id)
        except (OSError, json.JSONDecodeError):
            return JSONResponse({"error": f"no story {period_id!r}"}, status_code=404)

    return app
