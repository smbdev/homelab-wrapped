"""Playwright smoke-suite fixtures: a real server on a random local port.

The stories directory contains a rich story (all card templates, including a
``private`` card to exercise the redaction path) and an empty one.
"""

import json
import threading
import time

import pytest
import uvicorn

from wrapped.core.config import create_starter_config
from wrapped.web import create_app

RICH_STORY = {
    "version": 1,
    "period": {"type": "year", "id": "2026", "label": "Your 2026"},
    "generated_at": "2027-01-01T09:00:00+00:00",
    "cards": [
        {
            "template": "big_number",
            "fact": "media.total_hours",
            "private": False,
            "value": 412,
            "headline": "412 hours watched",
            "sub": "That's 17 full days of telly",
        },
        {
            "template": "top_list",
            "fact": "media.top_shows",
            "private": False,
            "headline": "Your top shows",
            "items": [
                {"label": "The Bear", "value": "31 eps"},
                {"label": "Severance", "value": "18 eps"},
            ],
        },
        {
            "template": "superlative",
            "fact": "photos.busiest_day",
            "private": True,
            "value": 132,
            "headline": "132 photos in one day",
            "sub": "Your camera's big day out: 14 June",
        },
        {
            "template": "streak",
            "fact": "activity.streak",
            "private": False,
            "value": 23,
            "headline": "A 23-day streak",
            "sub": "Every single day from 1 September",
        },
        {
            "template": "heatmap",
            "fact": "activity.by_day",
            "private": False,
            "headline": "Your year, day by day",
            "data": {"2026-01-05": 3, "2026-01-06": 1, "2026-06-14": 12},
        },
        # Carries its own satellites instead of borrowing from a sibling card.
        {
            "template": "big_number",
            "fact": "network.total",
            "private": False,
            "value": 34,
            "headline": "34 GB moved by your rack",
            "sub": "≈ 92 MB a day through your containers",
            "sats": [
                {"k": "downloaded", "v": "28 GB"},
                {"k": "uploaded", "v": "6 GB"},
            ],
        },
    ],
}

EMPTY_STORY = {
    "version": 1,
    "period": {"type": "month", "id": "2026-02", "label": "February 2026"},
    "generated_at": "2026-03-01T09:00:00+00:00",
    "cards": [],
}


@pytest.fixture(scope="session")
def server_url(tmp_path_factory):
    root = tmp_path_factory.mktemp("app")
    stories = root / "stories"
    stories.mkdir()
    (stories / "2026.json").write_text(json.dumps(RICH_STORY))
    (stories / "2026-02.json").write_text(json.dumps(EMPTY_STORY))
    config_path = root / "config.yaml"
    create_starter_config(config_path)

    config = uvicorn.Config(
        create_app(stories, config_path=config_path), host="127.0.0.1", port=0, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("test server failed to start")
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def auth_cookie(server_url):
    """Create the admin account once and hand out its session cookie."""
    import http.cookiejar
    import urllib.parse
    import urllib.request

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    data = urllib.parse.urlencode(
        {"username": "admin", "password": "hunter2secret", "confirm": "hunter2secret"}
    ).encode()
    opener.open(f"{server_url}/setup", data=data)
    for cookie in jar:
        if cookie.name == "wrapped_session":
            return cookie.value
    raise RuntimeError("setup did not return a session cookie")


@pytest.fixture(autouse=True)
def _signed_in(context, server_url, auth_cookie):
    """Every page in the e2e suite starts with a valid session."""
    context.add_cookies([{"name": "wrapped_session", "value": auth_cookie, "url": server_url}])
