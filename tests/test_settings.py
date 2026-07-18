"""Settings page: add/remove connectors from the browser."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wrapped.core.config import create_starter_config, load_config
from wrapped.web import create_app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.yaml"
    create_starter_config(path)
    return path


@pytest.fixture
def client(tmp_path, config_path):
    c = TestClient(create_app(tmp_path / "stories", config_path=config_path))
    c.post(  # first-run: create the admin so the session cookie is set
        "/setup",
        data={"username": "admin", "password": "hunter2secret", "confirm": "hunter2secret"},
    )
    return c


def test_settings_disabled_without_config_path(tmp_path):
    client = TestClient(create_app(tmp_path / "stories"))
    assert client.get("/settings").status_code == 404
    assert "Settings" not in client.get("/").text


def test_settings_page_lists_plugins(client):
    r = client.get("/settings")
    assert r.status_code == 200
    for label in ("Jellyfin", "Immich", "Generic CSV/JSON"):
        assert label in r.text
    assert "plugin-schemas" in r.text  # schema JSON for the dynamic form


def test_index_links_to_settings(client):
    r = client.get("/")
    assert "/settings" in r.text


def test_add_connector_via_form(client, config_path):
    r = client.post(
        "/settings/connectors",
        data={"name": "media", "type": "generic_csv", "path": str(FIXTURES / "events.csv")},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "Added" in r.text
    assert "4 events" in r.text  # the plugin's own test() ran
    (entry,) = load_config(config_path).connectors
    assert entry.name == "media"


def test_add_with_failing_test_still_saves_but_warns(client, config_path):
    r = client.post(
        "/settings/connectors",
        data={"name": "broken", "type": "generic_csv", "path": "/nope.csv"},
        follow_redirects=True,
    )
    assert "connection test failed" in r.text
    assert len(load_config(config_path).connectors) == 1  # saved regardless


def test_add_missing_required_field(client, config_path):
    r = client.post(
        "/settings/connectors",
        data={"name": "media", "type": "generic_csv"},
        follow_redirects=True,
    )
    assert "Missing required fields: path" in r.text
    assert load_config(config_path).connectors == []


def test_add_unknown_type(client, config_path):
    r = client.post(
        "/settings/connectors",
        data={"name": "x", "type": "nope"},
        follow_redirects=True,
    )
    assert "Unknown service type" in r.text


def test_duplicate_name_rejected(client, config_path):
    for _ in range(2):
        r = client.post(
            "/settings/connectors",
            data={"name": "media", "type": "generic_csv", "path": "/x.csv"},
            follow_redirects=True,
        )
    assert "already exists" in r.text
    assert len(load_config(config_path).connectors) == 1


def test_settings_page_has_scan_button(client):
    assert "scan-btn" in client.get("/settings").text


def test_scan_route_returns_suggestions(client, monkeypatch):
    import wrapped.web.discover as discover

    monkeypatch.setattr(discover, "docker_available", lambda: True)
    monkeypatch.setattr(
        discover,
        "scan",
        lambda: [
            {
                "type": "immich",
                "name": "immich",
                "fields": {},
                "port": 2283,
                "ready": True,
                "note": "n",
            }
        ],
    )
    r = client.get("/settings/scan")
    assert r.status_code == 200
    assert r.json()["found"][0]["type"] == "immich"


def test_scan_route_explains_missing_socket(client, monkeypatch):
    import wrapped.web.discover as discover

    monkeypatch.setattr(discover, "docker_available", lambda: False)
    r = client.get("/settings/scan")
    assert r.status_code == 503
    assert "docker.sock" in r.json()["error"]


def test_remove_connector(client, config_path):
    client.post(
        "/settings/connectors",
        data={"name": "media", "type": "generic_csv", "path": "/x.csv"},
    )
    r = client.post("/settings/connectors/media/delete", follow_redirects=True)
    assert "Removed" in r.text
    assert load_config(config_path).connectors == []
