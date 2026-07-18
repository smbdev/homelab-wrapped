"""Docker-socket service discovery — against recorded container listings."""

import pytest

import wrapped.web.discover as discover

CONTAINERS = [
    {
        "Names": ["/jellyfin"],
        "Image": "lscr.io/linuxserver/jellyfin:latest",
        "Ports": [{"PrivatePort": 8096, "PublicPort": 8096}],
        "Mounts": [
            {"Source": "/srv/jellyfin/config", "Destination": "/config"},
            {"Source": "/srv/media", "Destination": "/media"},
        ],
    },
    {
        "Names": ["/immich_server"],
        "Image": "ghcr.io/immich-app/immich-server:release",
        "Ports": [{"PrivatePort": 2283, "PublicPort": 2283}],
        "Mounts": [],
    },
    {
        "Names": ["/immich_postgres"],
        "Image": "tensorchord/pgvecto-rs:pg14",
        "Ports": [{"PrivatePort": 5432}],
        "Mounts": [],
    },
    {
        "Names": ["/pihole"],
        "Image": "pihole/pihole:latest",
        "Ports": [],
        "Mounts": [],
    },
]


@pytest.fixture
def fake_docker(monkeypatch):
    monkeypatch.setattr(discover, "docker_get", lambda path: CONTAINERS)


def test_scan_recognises_known_services(fake_docker):
    result = discover.scan()
    # docker_stats ("this server") always leads; postgres/pihole have no connector
    assert [s["type"] for s in result["found"]] == ["docker_stats", "jellyfin", "immich"]
    assert result["unknown"] == ["immich_postgres", "pihole"]


def test_scan_this_server_is_one_click(fake_docker):
    me = discover.scan()["found"][0]
    assert me["ready"] is True
    assert me["fields"] == {}


def test_jellyfin_suggestion_explains_mount(fake_docker):
    jf = discover.scan()["found"][1]
    assert jf["name"] == "jellyfin"
    assert jf["fields"]["db_path"] == "/jellyfin-data/data/playback_reporting.db"
    assert jf["ready"] is False  # db not mounted into this container
    assert "-v /srv/jellyfin/config:/jellyfin-data:ro" in jf["note"]


def test_jellyfin_ready_when_db_mounted(fake_docker, monkeypatch, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "playback_reporting.db").touch()
    monkeypatch.setattr(discover, "_JELLYFIN_MOUNT_TARGET", str(tmp_path))
    jf = discover.scan()["found"][1]
    assert jf["ready"] is True
    assert "ready to add" in jf["note"]


def test_immich_suggestion_carries_published_port(fake_docker):
    im = discover.scan()["found"][2]
    assert im["port"] == 2283
    assert im["ready"] is True
    assert "API key" in im["note"]


def test_docker_available_false_without_socket(monkeypatch):
    monkeypatch.setattr(discover, "SOCKET_PATH", "/nonexistent/docker.sock")
    assert discover.docker_available() is False
