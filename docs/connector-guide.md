# Writing a connector

Connectors are how Homelab Wrapped grows. One Python file, three methods, no core changes — this guide walks through the whole thing using the generic CSV connector as the worked example.

## The contract

A connector is a module in `wrapped/connectors/` exposing a module-level `CONNECTOR` instance with:

```python
class Connector(Protocol):
    id: str                    # "jellyfin" — used in config.yaml as `type:`
    name: str                  # "Jellyfin" — shown to humans
    schema: list[ConfigField]  # the config.yaml keys you need

    def test(self, cfg) -> ConnectionResult: ...
    def collect(self, cfg, since, until) -> Iterator[Event]: ...
    def facts(self) -> list[FactSpec]: ...
```

Drop the file in the package and it's discovered automatically — `all_connectors()` imports every module here that has a `CONNECTOR` attribute.

## The rules (non-negotiable)

1. **Read-only.** Use the least-privileged access the service supports: a read-only API key, a SQLite file opened with `mode=ro`, a data export. Never write to the source.
2. **No network beyond your configured base URL.** The test suite runs under a network-allowlist fixture that fails any test opening an unexpected socket. Your tests run against fixtures, so they make no network calls at all.
3. **Don't import other connectors.** Each one is self-contained.
4. **Tests against fixtures, never live services.** Record a real API response once, commit it under `tests/fixtures/`, test against that.

## Walkthrough: the CSV connector

The reference implementation is [`wrapped/connectors/generic_csv.py`](../wrapped/connectors/generic_csv.py) — read it side by side with this guide.

### 1. Declare your config schema

```python
class GenericCsvConnector:
    id = "generic_csv"
    name = "Generic CSV/JSON"
    schema = [
        ConfigField("path", "Path to a .csv (with header row) or .json (list of objects) file"),
        ConfigField("timezone", "IANA timezone applied to naive timestamps", required=False),
    ]
```

Each `ConfigField` is a key the user can set in their `config.yaml` under your connector's block:

```yaml
connectors:
  my_media:            # instance name — becomes Event.source
    type: generic_csv  # your `id`
    path: /data/media.csv
```

Required keys are validated before `collect()` is called; you can assume they exist.

### 2. Implement `collect()`

`collect(cfg, since, until)` yields **normalised `Event`s** for a half-open window `since <= ts < until`. The engine handles incremental sync: `since` is the last successful sync (so re-runs are cheap), and the instance name replaces your `source` when events are stored.

```python
def collect(self, cfg, since, until):
    for row in read_your_source(cfg):
        ts = parse_timestamp(row)          # must be timezone-aware
        if not (since <= ts < until):
            continue
        yield Event(
            source=self.id,
            kind="media.play",             # dotted kind — see vocabulary below
            ts=ts,
            entity="The Bear S03E01",      # the specific thing
            entity_group="The Bear",       # its grouping (show, album, city…)
            value=28.0,                    # magnitude: minutes, bytes, or 1
        )
```

**Kind vocabulary.** Facts key off event kinds, so reusing an existing kind lights up existing recap cards for free:

| kind | value means | feeds |
|---|---|---|
| `media.play` | minutes watched | total hours, top shows |
| `media.listen` | minutes listened | (top artists, planned) |
| `photo.taken` | 1 per photo | photo totals, busiest day |
| `doc.added` | 1 per document | on-this-day summaries |

Anything else (e.g. `backup.completed`) still works — it appears in streaks, heatmaps, and on-this-day counts. Invent `yourservice.thing` kinds freely; dots namespace them.

**Timestamps must be timezone-aware** — `Event` raises on naive datetimes. If your source stores naive local times, take a `timezone` config key and localise (both CSV and Jellyfin connectors show this pattern).

**Bad data policy:** broken rows in a file the user controls should raise (loud beats silent corruption); broken rows in append-only service history should be skipped (the user can't fix them). CSV raises; Jellyfin and Immich skip.

### 3. Implement `test()`

`test(cfg)` is what users run first to check their config. Be specific in both directions:

```python
def test(self, cfg):
    try:
        count = sum(1 for _ in self.collect(cfg, FOREVER_AGO, FOREVER))
    except FileNotFoundError:
        return ConnectionResult(False, f"File not found: {cfg.get('path')}")
    return ConnectionResult(True, f"OK — {count} events in {cfg.get('path')}")
```

A good failure message names the thing that's wrong and where it was looked for.

### 4. Declare `facts()`

List the recap facts your connector can feed, so capability discovery doesn't hardcode services:

```python
def facts(self):
    return [FactSpec("media.total_hours", "Total hours watched")]
```

### 5. Write the tests

Every public method, against committed fixtures, in `tests/test_<yourid>.py`:

- `collect()` filters the window correctly (include an out-of-window row in the fixture)
- normalisation is right (kind, value units, entity_group)
- `test()` succeeds on good config and fails helpfully on bad
- your bad-data policy actually happens

For API connectors, record responses into a JSON fixture and monkeypatch your HTTP helper — see `tests/test_immich.py`. For file/db connectors, build the fixture in the test — see `tests/test_jellyfin.py`.

### 6. Checklist before the PR

- [ ] One module in `wrapped/connectors/`, `CONNECTOR` instance at module level
- [ ] Read-only credentials/access documented in the schema descriptions
- [ ] Timezone-aware timestamps
- [ ] Tests against fixtures; `uv run pytest` green (network allowlist included)
- [ ] `uv run ruff check .` and `uv run ruff format --check .` clean
- [ ] A short entry in the README connector list
