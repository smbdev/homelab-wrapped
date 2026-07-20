"""Docker-stats connector: sampling, restart-safe deltas, and the facts they feed."""

from datetime import UTC, datetime

import pytest

import wrapped.connectors.docker_stats as ds
from wrapped.core.events import Event, EventStore
from wrapped.facts import (
    FactContext,
    _network_by_service,
    _network_total,
    _system_containers,
    _system_oldest_container,
)

UNTIL = datetime(2026, 6, 1, tzinfo=UTC)

JAN_2026 = 1_767_225_600  # 2026-01-01T00:00:00Z, as Docker's Created stamp
JUN_2026 = 1_780_272_000  # 2026-06-01T00:00:00Z

CONTAINERS = [
    # compose-managed: the service label wins over the generated name
    {
        "Id": "aaa",
        "Names": ["/jellyfin-jellyfin-1"],
        "Labels": {"com.docker.compose.service": "jellyfin"},
        "Created": JAN_2026,
    },
    # plain `docker run --name immich`: no labels, name is the fallback
    {"Id": "bbb", "Names": ["/immich"], "Created": JUN_2026},
]
STATS = {
    "aaa": {
        "networks": {"eth0": {"rx_bytes": 1000, "tx_bytes": 2000}},
        "cpu_stats": {"cpu_usage": {"total_usage": 7_200_000_000_000}},  # 2 hours
        "memory_stats": {"usage": 500_000_000},
    },
    "bbb": {
        "networks": {
            "eth0": {"rx_bytes": 50, "tx_bytes": 50},
            "eth1": {"rx_bytes": 10, "tx_bytes": 0},
        },
        "cpu_stats": {"cpu_usage": {"total_usage": 3_600_000_000_000}},  # 1 hour
        "memory_stats": {"usage": 250_000_000},
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


def test_collect_emits_four_samples_per_container_plus_count(fake_docker):
    events = list(ds.CONNECTOR.collect({}, UNTIL, UNTIL))
    per_container = ["net.sample", "system.cpu", "system.memory", "system.container_started"]
    assert [e.kind for e in events] == per_container * 2 + ["system.containers"]

    jf = events[0]
    assert jf.entity == "Jellyfin" and jf.value == 3000 and jf.meta == {"rx": 1000, "tx": 2000}
    assert events[1].value == 7_200_000_000_000  # raw ns counter, not a percentage
    assert events[2].value == 500_000_000
    assert events[3].value == JAN_2026
    assert events[4].value == 110  # immich, both interfaces summed
    assert events[-1].value == 2  # container count


def test_runtime_without_cpu_or_memory_still_yields_network(fake_docker, monkeypatch):
    """Podman and older daemons omit these; the sample must not become an error."""

    def bare(path, socket_path=ds.DEFAULT_SOCKET):
        if path == "/containers/json":
            return [{"Id": "aaa", "Names": ["/x"]}]  # no Created either
        return {"networks": {"eth0": {"rx_bytes": 5, "tx_bytes": 5}}}

    monkeypatch.setattr(ds, "docker_get", bare)
    events = list(ds.CONNECTOR.collect({}, UNTIL, UNTIL))
    assert [e.kind for e in events] == ["net.sample", "system.containers"]


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


def _gauge(kind, name, ts, value):
    return Event(source="docker", kind=kind, ts=ts, entity=name, value=float(value))


def test_containers_card_orbits_cpu_time_and_memory():
    day = lambda n: datetime(2026, 1, n, tzinfo=UTC)  # noqa: E731
    hour_ns = 3_600_000_000_000
    store = EventStore(":memory:")
    store.add_events(
        [
            Event(source="docker", kind="system.containers", ts=day(2), value=30),
            # cumulative CPU counters: jellyfin burns 4h, immich 2h
            _gauge("system.cpu", "jellyfin", day(1), 0),
            _gauge("system.cpu", "jellyfin", day(2), 4 * hour_ns),
            _gauge("system.cpu", "immich", day(1), 0),
            _gauge("system.cpu", "immich", day(2), 2 * hour_ns),
            # memory is a gauge — only the newest sample per container counts
            _gauge("system.memory", "jellyfin", day(1), 100_000_000),
            _gauge("system.memory", "jellyfin", day(2), 700_000_000),
            _gauge("system.memory", "immich", day(2), 300_000_000),
        ]
    )
    card = _system_containers(_ctx(store))
    assert card["value"] == 30
    assert card["sats"] == [
        {"k": "cpu time burned", "v": "6 hours"},
        {"k": "memory in use", "v": "1 GB"},  # 700 MB + 300 MB, newest samples only
    ]


def test_containers_card_has_no_satellites_without_stats():
    store = EventStore(":memory:")
    store.add_events([Event(source="docker", kind="system.containers", ts=UNTIL, value=12)])
    card = _system_containers(_ctx(store))
    assert "sats" not in card


def test_cpu_satellite_survives_a_counter_reset():
    day = lambda n: datetime(2026, 1, n, tzinfo=UTC)  # noqa: E731
    hour_ns = 3_600_000_000_000
    store = EventStore(":memory:")
    store.add_events(
        [
            Event(source="docker", kind="system.containers", ts=day(3), value=1),
            _gauge("system.cpu", "x", day(1), 0),
            _gauge("system.cpu", "x", day(2), 5 * hour_ns),
            _gauge("system.cpu", "x", day(3), 2 * hour_ns),  # restart: +2h, not -3h
        ]
    )
    card = _system_containers(_ctx(store))
    assert card["sats"][0] == {"k": "cpu time burned", "v": "7 hours"}


def test_oldest_container_reports_the_earliest_creation():
    store = EventStore(":memory:")
    store.add_events(
        [
            _gauge("system.container_started", "Caddy", UNTIL, JAN_2026),
            _gauge("system.container_started", "Immich", UNTIL, JUN_2026),
        ]
    )
    card = _system_oldest_container(_ctx(store))
    assert card["value"] == 151  # 1 Jan to the 1 Jun sample, not to the window end
    assert card["headline"] == "151 days old"
    assert "Caddy" in card["sub"] and "1 January 2026" in card["sub"]


def test_age_is_measured_to_the_sample_not_the_window_end():
    """A recap for the current year runs to 31 December — measuring against
    that would report the age a container is going to reach, not its age."""
    sampled = datetime(2026, 7, 20, tzinfo=UTC)
    ten_days_earlier = int(datetime(2026, 7, 10, tzinfo=UTC).timestamp())
    store = EventStore(":memory:")
    store.add_events([_gauge("system.container_started", "Portainer", sampled, ten_days_earlier)])

    card = _system_oldest_container(_ctx(store))  # window ends 2027-01-01
    assert card["value"] == 10, "should be its real age, not 174 days"


def test_oldest_container_needs_a_full_day():
    """A container created an hour before the window closes isn't a story."""
    an_hour_before_window_end = int(datetime(2027, 1, 1, tzinfo=UTC).timestamp()) - 3600
    store = EventStore(":memory:")
    store.add_events([_gauge("system.container_started", "New", UNTIL, an_hour_before_window_end)])
    assert _system_oldest_container(_ctx(store)) is None


def test_oldest_container_absent_without_samples():
    assert _system_oldest_container(_ctx(EventStore(":memory:"))) is None


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
