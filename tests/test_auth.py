"""Auth: first-run setup, sessions, account changes, proxy mode."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wrapped.core.config import create_starter_config
from wrapped.web import create_app
from wrapped.web.auth import COOKIE

CREDS = {"username": "admin", "password": "hunter2secret", "confirm": "hunter2secret"}


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.yaml"
    create_starter_config(path)
    return path


@pytest.fixture
def client(tmp_path, config_path):
    return TestClient(create_app(tmp_path / "stories", config_path=config_path))


@pytest.fixture
def signed_in(client):
    client.post("/setup", data=CREDS)
    return client


def test_first_run_redirects_to_setup(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/setup"


def test_setup_creates_account_and_signs_in(client):
    r = client.post("/setup", data=CREDS, follow_redirects=False)
    assert r.status_code == 303
    assert COOKIE in r.cookies
    assert client.get("/").status_code == 200


def test_setup_validates(client):
    bad = dict(CREDS, confirm="different-thing")
    assert client.post("/setup", data=bad).status_code == 400
    assert (
        client.post("/setup", data=dict(CREDS, password="short", confirm="short")).status_code
        == 400
    )
    assert client.post("/setup", data=dict(CREDS, username="no spaces!")).status_code == 400


def test_setup_only_runs_once(signed_in, tmp_path, config_path):
    fresh = TestClient(create_app(tmp_path / "stories", config_path=config_path))
    r = fresh.post("/setup", data=dict(CREDS, username="intruder"), follow_redirects=False)
    assert r.status_code == 303
    assert COOKIE not in r.cookies
    r = fresh.get("/login")
    assert r.status_code == 200  # login page, not a second setup


def test_login_wrong_password(signed_in, tmp_path, config_path):
    fresh = TestClient(create_app(tmp_path / "stories", config_path=config_path))
    r = fresh.post("/login", data={"username": "admin", "password": "wrong-password"})
    assert r.status_code == 401
    assert "Wrong username or password" in r.text


def test_login_and_logout(signed_in, tmp_path, config_path):
    fresh = TestClient(create_app(tmp_path / "stories", config_path=config_path))
    r = fresh.post(
        "/login", data={"username": "admin", "password": "hunter2secret"}, follow_redirects=False
    )
    assert r.status_code == 303 and COOKIE in r.cookies
    assert fresh.get("/").status_code == 200
    fresh.post("/logout")
    assert fresh.get("/", follow_redirects=False).status_code == 303


def test_static_and_api_behaviour_unauthenticated(client):
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/api/stories").status_code == 401
    assert client.get("/api/stories").json()["error"] == "not signed in"


def test_account_change_requires_current_password(signed_in):
    r = signed_in.post(
        "/account",
        data={
            "current_password": "wrong",
            "new_password": "n3w-password",
            "confirm": "n3w-password",
        },
        follow_redirects=False,
    )
    assert "err=" in r.headers["location"]


def test_password_change_invalidates_other_sessions(signed_in, tmp_path, config_path):
    other = TestClient(create_app(tmp_path / "stories", config_path=config_path))
    other.post("/login", data={"username": "admin", "password": "hunter2secret"})
    assert other.get("/").status_code == 200
    signed_in.post(
        "/account",
        data={
            "current_password": "hunter2secret",
            "new_password": "brand-new-pass",
            "confirm": "brand-new-pass",
        },
    )
    assert other.get("/", follow_redirects=False).status_code == 303  # kicked out
    assert signed_in.get("/").status_code == 200  # changer keeps a fresh session


def test_proxy_mode(tmp_path):
    config = tmp_path / "config.yaml"
    create_starter_config(config)
    config.write_text(config.read_text() + "\nauth: proxy\n")
    client = TestClient(create_app(tmp_path / "stories", config_path=config))
    assert client.get("/", follow_redirects=False).status_code == 401
    assert client.get("/", headers={"X-Auth-User": "scott"}).status_code == 200
    r = client.get("/login", headers={"X-Auth-User": "scott"}, follow_redirects=False)
    assert r.headers["location"] == "/"
    r = client.get("/settings", headers={"X-Auth-User": "scott"})
    assert "managed by your reverse proxy" in r.text


def test_no_config_means_no_auth(tmp_path):
    client = TestClient(create_app(tmp_path / "stories"))
    assert client.get("/").status_code == 200


def test_auth_json_is_private(signed_in, config_path):
    auth_file = Path(config_path).parent / "auth.json"
    assert auth_file.exists()
    assert (auth_file.stat().st_mode & 0o777) == 0o600
    assert "hunter2secret" not in auth_file.read_text()  # hashed, never plaintext
