"""Docker-stats connector: sampling, restart-safe deltas, and the facts they feed."""

from datetime import UTC, datetime

import pytest

import wrapped.connectors.docker_stats as ds
from wrapped.core.events import Event, EventStore
from wrapped.facts import FactContext, _network_by_service, _network_total, _system_containers

UNTIL = datetime(2026, 6, 1, tzinfo=UTC)

CONTAINERS = [
    # compose-managed: the service label wins over the generated name
    {
        "Id": "aaa",
        "Names": ["/jellyfin-jellyfin-1"],
        "Labels": {"com.docker.compose.service": "jellyfin"},
    },
    # plain `docker run --name immich`: no labels, name is the fallback
    {"Id": "bbb", "Names": ["/immich"]},
]
STATS = {
    "aaa": {"networks": {"eth0": {"rx_bytes": 1000, "tx_bytes": 2000}}},
    "bbb": {
        "networks": {
            "eth0": {"rx_bytes": 50, "tx_bytes": 50},
            "eth1": {"rx_bytes": 10, "tx_bytes": 0},
        }
    },
}


@pytest.fixture
def fake_docker(monkeypatch):
    def fake_get(path, socket_path=ds.DEFAULT_SOCKET):
        if path == "/containers/json":
            return CONTAINERS
        for cid, stats in STATS.items():
            if cid in path:
                return stats
        raise OSError(path)

    monkeypatch.setattr(ds, "docker_get", fake_get)


def test_collect_emits_one_sample_per_container_plus_count(fake_docker):
    events = list(ds.CONNECTOR.collect({}, UNTIL, UNTIL))
    kinds = [e.kind for e in events]
    assert kinds == ["net.sample", "net.sample", "system.containers"]
    jf = events[0]
    assert jf.entity == "Jellyfin" and jf.value == 3000 and jf.meta == {"rx": 1000, "tx": 2000}
    assert events[1].value == 110  # both interfaces summed
    assert events[2].value == 2


def test_vanished_container_does_not_kill_collect(fake_docker, monkeypatch):
    def flaky(path, socket_path=ds.DEFAULT_SOCKET):
        if path == "/containers/json":
            return CONTAINERS
        if "aaa" in path:
            raise OSError("gone")
        return STATS["bbb"]

    monkeypatch.setattr(ds, "docker_get", flaky)
    events = list(ds.CONNECTOR.collect({}, UNTIL, UNTIL))
    assert [e.entity for e in events if e.kind == "net.sample"] == ["Immich"]


def _store_with_samples(samples, split=None):
    """Samples are ``(name, ts, total)``; ``split`` optionally gives (rx, tx) per row."""
    store = EventStore(":memory:")
    store.add_events(
        Event(
            source="docker",
            kind="net.sample",
            ts=ts,
            entity=name,
            value=float(v),
            meta=({"rx": split[i][0], "tx": split[i][1]} if split else {}),
        )
        for i, (name, ts, v) in enumerate(samples)
    )
    return store


def _ctx(store):
    return FactContext(
        store=store,
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=datetime(2027, 1, 1, tzinfo=UTC),
        tz=UTC,
    )


def test_network_total_sums_deltas_and_survives_counter_reset():
    day = lambda n: datetime(2026, 1, n, tzinfo=UTC)  # noqa: E731
    store = _store_with_samples(
        [
            ("jellyfin", day(1), 0),
            ("jellyfin", day(2), 2e12),  # +2 TB
            ("jellyfin", day(3), 1e11),  # counter reset (restart): +0.1 TB, not -1.9
            ("jellyfin", day(4), 4e11),  # +0.3 TB
        ]
    )
    card = _network_total(_ctx(store))
    assert card["value"] == 2.4
    assert card["headline"].startswith("2.4 TB")


def test_network_total_splits_down_and_up_into_satellites():
    day = lambda n: datetime(2026, 1, n, tzinfo=UTC)  # noqa: E731
    store = _store_with_samples(
        [("jellyfin", day(1), 0), ("jellyfin", day(2), 5e12)],
        split=[(0, 0), (4e12, 1e12)],  # 4 TB down, 1 TB up
    )
    card = _network_total(_ctx(store))
    assert card["sats"] == [
        {"k": "downloaded", "v": "4.0 TB"},
        {"k": "uploaded", "v": "1.0 TB"},
    ]


def test_direction_satellites_survive_a_counter_reset():
    """Restarts must not make a direction negative, same as the total."""
    day = lambda n: datetime(2026, 1, n, tzinfo=UTC)  # noqa: E731
    store = _store_with_samples(
        [("a", day(1), 0), ("a", day(2), 3e12), ("a", day(3), 1e12)],
        split=[(0, 0), (2e12, 1e12), (5e11, 5e11)],  # restart on day 3
    )
    card = _network_total(_ctx(store))
    assert card["sats"] == [
        {"k": "downloaded", "v": "2.5 TB"},  # 2 TB + 0.5 TB, not 2 TB - 1.5 TB
        {"k": "uploaded", "v": "1.5 TB"},
    ]


def test_no_direction_satellites_without_the_meta_split():
    """An event cache written before rx/tx existed degrades to no satellites."""
    day = lambda n: datetime(2026, 1, n, tzinfo=UTC)  # noqa: E731
    store = _store_with_samples([("a", day(1), 0), ("a", day(2), 5e12)])
    card = _network_total(_ctx(store))
    assert "sats" not in card
    assert card["value"] == 5.0  # the hero number still works


def test_network_total_needs_at_least_a_gigabyte():
    store = _store_with_samples([("x", UNTIL, 0), ("x", datetime(2026, 6, 2, tzinfo=UTC), 5e8)])
    assert _network_total(_ctx(store)) is None


def test_network_by_service_ranks_containers():
    day = lambda n: datetime(2026, 1, n, tzinfo=UTC)  # noqa: E731
    store = _store_with_samples(
        [
            ("jellyfin", day(1), 0),
            ("jellyfin", day(2), 3e9),
            ("immich", day(1), 0),
            ("immich", day(2), 9e9),
        ]
    )
    card = _network_by_service(_ctx(store))
    assert [i["label"] for i in card["items"]] == ["immich", "jellyfin"]
    assert card["items"][0]["raw"] == 9_000_000_000


def test_container_count_uses_latest_sample():
    store = EventStore(":memory:")
    store.add_events(
        [
            Event(
                source="docker",
                kind="system.containers",
                ts=datetime(2026, 1, 1, tzinfo=UTC),
                value=20,
            ),
            Event(
                source="docker",
                kind="system.containers",
                ts=datetime(2026, 6, 1, tzinfo=UTC),
                value=24,
            ),
        ]
    )
    card = _system_containers(_ctx(store))
    assert card["value"] == 24


def test_samples_do_not_fake_activity_streaks():
    from wrapped.facts import _activity_heatmap, _activity_streak

    store = _store_with_samples(
        [("x", datetime(2026, 1, n, tzinfo=UTC), n * 1e9) for n in range(1, 20)]
    )
    ctx = _ctx(store)
    assert _activity_streak(ctx) is None  # daily sampling is not a streak
    assert _activity_heatmap(ctx) is None


def test_test_reports_missing_socket():
    result = ds.CONNECTOR.test({"socket_path": "/nonexistent.sock"})
    assert result.ok is False
    assert "mount it read-only" in result.message.lower() or "No Docker socket" in result.message
