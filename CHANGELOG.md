# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-06-16

First stable release. The plugin has been validated in production against the
live nicmanager AnycastDNS API (wildcard issuance for 8 domains, with automatic
renewal via certbot's systemd timer).

### Added
- `docs/ARCHITECTURE.md` and Architecture Decision Records
  (`docs/decisions/ADR-001..003`) documenting the design.
- `docs/TROUBLESHOOTING.md` with the real-world nicmanager API status decoder
  (401 vs 403 vs rate-limit vs firewall block) and authentication notes.
- Automated PyPI publishing via GitHub Actions Trusted Publishing (OIDC).

### Notes
- The basic-auth **username must match the account's active authentication
  method**: the account **email** for "E-Mail + Passwort" accounts, or
  `login.username` otherwise. The wrong form returns `401` even with the correct
  password. 2FA must be disabled on the automation account.

## [0.2.0] - 2026-06-14

### Changed
- **Zone detection no longer reads zones.** A restricted API-ACME account cannot
  read zone metadata (`GET /anycast/{zone}` returns 401/403), so the owning zone
  is now found by attempting the record *create* against each candidate zone
  (most-specific first) and using the first that succeeds. A `403`/`404` skips to
  the next candidate; a `401` (genuine auth failure) is never swallowed.
- Cleanup now deletes strictly by the record id captured at creation and makes no
  `GET` request when no id is stored (the restricted account cannot list records).

### Notes
- If the credentials password contains `#`, quote it in the INI
  (`dns_nicmanager_password = "..."`) — the INI parser treats an unquoted `#` as
  a comment.

## [0.1.0] - 2026-06-14

### Added
- Initial release.
- Certbot `dns-01` authenticator (`dns-nicmanager`) for the nicmanager AnycastDNS
  API.
- Automatic zone detection with an optional `dns_nicmanager_zone` override.
- Tolerates locked-down API-ACME accounts that cannot read zone metadata.
- Cleanup deletes the challenge record by the numeric id returned at creation,
  with a name/content lookup fallback.
- Test suite covering create, delete, zone walking, and API error handling.

[Unreleased]: https://github.com/jp1337/certbot-dns-nicmanager/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/jp1337/certbot-dns-nicmanager/compare/v0.2.0...v1.0.0
[0.2.0]: https://github.com/jp1337/certbot-dns-nicmanager/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jp1337/certbot-dns-nicmanager/releases/tag/v0.1.0
