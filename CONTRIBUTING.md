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

Run the same checks CI runs — all four must pass:

```bash
pytest                          # tests + coverage
ruff check .                    # lint + import order
ruff format --check .           # formatting (`ruff format .` fixes it)
mypy certbot_dns_nicmanager     # type check
```

The tests use `requests-mock`, so they never touch the network or a real
nicmanager account.

Optionally install the git hooks so these checks run automatically on commit:

```bash
pip install pre-commit && pre-commit install
```

## Guidelines

- Keep the public surface small: only the `Authenticator` class and the plugin
  entry point are public. `_NicmanagerClient` and the `_internal` package are
  implementation details (leading underscore is intentional).
- Match the existing style; `ruff` enforces formatting and import order.
- Documentation goes where its reader is: `docs/` for people running the plugin
  (ships to PyPI), `docs-tech/` for maintainers (never published). A test
  enforces the boundary.
- Add or update tests for any behaviour change.
- Update `CHANGELOG.md` (under `[Unreleased]`) and, for design changes, add an
  ADR in `docs-tech/decisions/`.
- Understand the design first: [`docs-tech/`](docs-tech/README.md) has the
  architecture, the ADRs and the API behaviour the code relies on.

## Reporting bugs

Open an issue with: certbot version, plugin version, Python version, the exact
command, and the relevant log (with secrets redacted). For API authentication
failures, check [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) first — the `401`/`403` distinction
usually points straight at the cause.

## Releases

Maintainers only: [`docs-tech/RELEASING.md`](docs-tech/RELEASING.md).
