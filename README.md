# Homelab Wrapped

Your homelab's year, wrapped. A self-hosted, privacy-first recap generator that pulls read-only stats from services you already run (Jellyfin, Immich, …) and turns them into a beautiful, shareable "Wrapped"-style story — yearly, monthly, or as a daily "On This Day" page.

> **Status: early development.** Not yet usable. Watch the repo for the v0.1.0 release.

## Why

- **Privacy-first, provable.** All data stays on your server. Zero outbound network calls by default — enforced by tests.
- **Read-only.** Least-privileged credentials; nothing is ever written to your services.
- **Lean.** Runs comfortably on a Raspberry Pi. One Docker image, one volume, one `config.yaml`.
- **Plugin-everything.** Connectors are tiny self-contained plugins — add your service without touching core.

## Planned for v0.1

- Connectors: Jellyfin, Immich, generic CSV/JSON
- Yearly Wrapped, monthly recaps, and On This Day
- Swipeable story player with client-side PNG export and per-stat privacy controls
- Optional email digests via your own SMTP

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) (coming with the first milestone).

## License

[AGPL-3.0](LICENSE)
