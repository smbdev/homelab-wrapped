"""Web app routes against a stories directory of fixtures."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wrapped.web import create_app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def stories_dir(tmp_path):
    d = tmp_path / "stories"
    d.mkdir()
    story = json.loads((FIXTURES / "snapshots" / "year-2026.json").read_text())
    (d / "2026.json").write_text(json.dumps(story))
    return d


@pytest.fixture
def client(stories_dir):
    return TestClient(create_app(stories_dir))


def test_index_lists_recaps(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Your 2026" in r.text
    assert "/story/2026" in r.text


def test_index_empty_state(tmp_path):
    client = TestClient(create_app(tmp_path / "none"))
    r = client.get("/")
    assert r.status_code == 200
    assert "wrapped sync" in r.text  # teaches the two commands


def test_story_page_inlines_json(client):
    r = client.get("/story/2026")
    assert r.status_code == 200
    assert "story-data" in r.text
    assert "media.total_hours" in r.text
    assert "player.js" in r.text


def test_unknown_story_404_lists_available(client):
    r = client.get("/story/1999")
    assert r.status_code == 404
    assert "Your 2026" in r.text  # 404 page still offers what exists


def test_api_story_roundtrip(client, stories_dir):
    r = client.get("/api/stories/2026")
    assert r.status_code == 200
    assert r.json() == json.loads((stories_dir / "2026.json").read_text())
    assert client.get("/api/stories/nope").status_code == 404


def test_api_index(client):
    assert client.get("/api/stories").json() == [{"id": "2026", "label": "Your 2026"}]


def test_static_assets_served(client):
    for asset in ("hw.css", "story.css", "player.js", "export.js", "canvas-bg.js"):
        assert client.get(f"/static/{asset}").status_code == 200


def test_corrupt_story_skipped_in_index(client, stories_dir):
    (stories_dir / "bad.json").write_text("{not json")
    r = client.get("/")
    assert r.status_code == 200
    assert "Your 2026" in r.text
