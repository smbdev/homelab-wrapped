# Contributing

Thanks for helping make Homelab Wrapped better. The most valuable contribution is a **connector for a service you run** — see the [connector guide](docs/connector-guide.md).

## Dev setup

```bash
git clone https://github.com/smbdev/homelab-wrapped
cd homelab-wrapped
uv sync                              # Python ≥3.13; installs dev deps into .venv
uv run playwright install chromium   # once, for the browser smoke tests
uv run pre-commit install            # lint + tests before every commit
uv run pytest                        # everything should be green before you start
```

Try it end to end with the test fixtures:

```bash
cat > config.yaml <<'YAML'
database: data/events.db
connectors:
  demo:
    type: generic_csv
    path: tests/fixtures/events.csv
YAML
uv run wrapped sync && uv run wrapped build --year 2026 && uv run wrapped serve
```

## Ground rules

- **Privacy is the product.** No telemetry, no external calls beyond a connector's configured base URL, no new-dependency CDN assets. The network-allowlist test fixture enforces this — don't fight it.
- **Lean.** Prefer the standard library. A new runtime dependency needs a strong case (budget: ≤6 total).
- **Read-only.** Connectors never write to source services.

## Branches, commits, PRs

- Branch from `main` with a descriptive name: `feat/navidrome-connector`, `fix/heatmap-timezone`, `docs/...`.
- One logical change per commit, imperative messages ("Add Navidrome connector", not "added stuff").
- Behaviour changes come with tests in the same PR. Bug fixes start with a failing regression test.
- Keep PRs reviewable (aim for under ~500 lines) and describe what changed, why, and how to test it.
- CI (ruff + pytest + Playwright smoke on Python 3.13/3.14) must be green before merge.

## Tests

- Unit tests live in `tests/`, browser smoke tests in `tests/e2e/`.
- Connector tests run against committed fixtures in `tests/fixtures/` — never live services.
- `uv run pytest` runs everything; the pre-commit hook runs it for you on commit.
