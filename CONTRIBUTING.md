# Contributing

Thanks for your interest in improving `certbot-dns-nicmanager`! Contributions —
bug reports, fixes, docs, and tests — are welcome.

## Development setup

```bash
git clone https://github.com/jp1337/certbot-dns-nicmanager
cd certbot-dns-nicmanager
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test,dev]'
```

## Before opening a pull request

Run the same checks CI runs — all three must pass:

```bash
pytest                          # tests + coverage
ruff check .                    # lint + import order
mypy certbot_dns_nicmanager     # type check
```

The tests use `requests-mock`, so they never touch the network or a real
nicmanager account.

## Guidelines

- Keep the public surface small: only the `Authenticator` class and the plugin
  entry point are public. `_NicmanagerClient` and the `_internal` package are
  implementation details (leading underscore is intentional).
- Match the existing style; `ruff` enforces formatting and import order.
- Add or update tests for any behaviour change.
- Update `CHANGELOG.md` (under `[Unreleased]`) and, for design changes, add an
  ADR in `docs/decisions/`.
- Understand the design first: see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
  and the [ADRs](docs/decisions/). API quirks are documented in
  [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

## Reporting bugs

Open an issue with: certbot version, plugin version, Python version, the exact
command, and the relevant log (with secrets redacted). For API authentication
failures, check `docs/TROUBLESHOOTING.md` first — the `401`/`403` distinction
usually points straight at the cause.

## Releases

Releases are cut by maintainers: bump the version in `pyproject.toml`, finalise
`CHANGELOG.md`, then push a `vX.Y.Z` tag. The `publish.yml` workflow builds,
tests, and publishes to PyPI via Trusted Publishing.
