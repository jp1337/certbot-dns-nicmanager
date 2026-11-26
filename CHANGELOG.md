# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **The link test missed anchors on the repository front page.** 1.1.3 said
  every link and anchor is checked, but a link such as
  `https://github.com/jp1337/certbot-dns-nicmanager#compared-to-lego` was
  skipped: breaking that anchor passed the suite. Front-page links now resolve
  to `README.md` and their anchors are checked; issue, release and advisory
  URLs stay out of scope.
- ADR-003 still said records are keyed by name only and the entry is removed
  before the delete — the wildcard bug the same ADR warns about.
- The Renovate rule that holds runtime dependency updates for review matched
  nothing: it filtered on the `pep621` manager, but Renovate reads this
  `pyproject.toml` with its `poetry` manager. It now matches on the dependency
  type alone.

### Added
- A test that the challenge-flow diagram says the same in its drawn SVG and in
  its embedded draw.io model, so a hand edit to one cannot go unnoticed.

## [1.1.3] - 2026-11-24

### Fixed
- **An unquoted `#` in the password no longer walks into nicmanager's IP block.**
  Certbot's INI parser cuts the value at `#`, so `p#ss` was sent as `p`: a `401`
  on every renewal until the API blocked the host. The plugin now stops before
  the first request and says to quote the password. A `#` after a space is still
  read as a trailing comment, so existing files with comments keep working.
- The documentation said an unquoted `#` in the password makes Certbot report
  `dns_nicmanager_password is required`. That happens only when `#` is the
  first character; anywhere else the password is cut at the `#`, the API answers
  `401`, and repeated runs lock the IP. Now documented as measured.
- **The cleanup warning was untested.** When a delete fails, the warning naming
  zone and record id is the operator's only way to find the leftover record;
  demoting it to debug level passed every test. The test now asserts it.
- `CONTRIBUTING.md` said ruff enforces formatting, but CI never ran
  `ruff format` and three files were unformatted. CI and pre-commit now check it.
- `docs-tech/ARCHITECTURE.md` still described the pre-1.0.2 cleanup (entry
  removed before the delete), keyed records by name only, and omitted retries,
  2FA and the "API usage not allowed" abort.

### Added
- Operator documentation split by task: [account setup](docs/ACCOUNT.md),
  [configuration](docs/CONFIGURATION.md) (every key and argument, renewal,
  installing next to Certbot), and [troubleshooting](docs/TROUBLESHOOTING.md)
  with every plugin log message explained.
- README: sequence diagram of the challenge flow, comparison with lego, German
  summary.
- Maintainer documentation: API behaviour the code relies on, release and
  dependency process (`docs-tech/`).
- Tests: every Markdown link and anchor resolves (including this repository's
  absolute links in the README), and every doc page is linked from its index.

## [1.1.2] - 2026-11-24

Documentation and packaging only; the plugin code is unchanged.

### Fixed
- **Links on the PyPI page were dead.** The README used repository-relative
  links (`LICENSE.txt`, `docs/TROUBLESHOOTING.md`, …), which PyPI cannot
  resolve. All links are absolute now.

### Changed
- README reworked: quick start, feature list, badges.
- GitHub Actions are pinned to commit digests; pre-commit hooks updated
  (ruff 0.17, mypy 2.4, pre-commit-hooks 6).

### Added
- A test builds the sdist and fails if the maintainer documentation in
  `docs-tech/` would ship to PyPI, or if `docs/TROUBLESHOOTING.md` would not.

## [1.1.1] - 2026-11-24

### Fixed
- **2FA secrets were rejected with pyotp 2.12.** pyotp 2.12 (released
  2026-11-15) refuses TOTP secrets under 112 bits, so a fresh install rejected the
  common 80-bit (16-character) secret at startup: "Secrets must be at least 112
  bits after decoding". The secret is issued by nicmanager, not chosen by the
  operator, so the plugin now accepts secrets from 80 bits up; shorter ones are
  still rejected as a truncated paste. Requires `pyotp>=2.12.1` (2.12.0 has no way
  to lower the limit).
- **A retried create could leave a duplicate record behind without a word.** A
  `504`, read timeout or dropped connection can arrive after the API stored the
  record; the retry then creates a second one and only that one is cleaned up.
  The plugin now logs a warning naming the zone whenever it retries a create
  after such an ambiguous failure (not after `429`/`503`, which mean "not
  processed").
- `SECURITY.md` and the package docstring still told operators to disable 2FA.
- The publish workflow now refuses a tag that does not match the version in
  `pyproject.toml`; before, it built whatever version the file named.

### Changed
- Tested on Python 3.14 and 3.15.
- Package metadata uses an SPDX licence expression; the old TOML table stops
  building with setuptools after 2027-02-18.
- Dependency updates move from Dependabot to Renovate (GitHub Actions pinned to
  commit digests, pre-commit hooks covered). A weekly CI run against the newest
  dependency versions catches breaking upstream releases like the pyotp one.

## [1.1.0] - 2026-07-13

### Added
- **Two-factor authentication (TOTP) support.** A new optional credential,
  `dns_nicmanager_totp_secret` (base32), makes the plugin send a rotating code in
  the `X-Auth-Token` header on every request, as the API requires for 2FA-enabled
  accounts. A fresh code is minted per request attempt (so a retry crossing a
  30-second window still carries a valid code); the API accepts reuse within a
  window, so no wait-for-next-window logic is needed. The secret may be given in
  the portal's space-grouped form. Unset ⇒ unchanged behaviour for accounts
  without 2FA. Requires an accurate host clock (NTP): a skewed clock yields
  invalid codes, and repeated invalid codes get the account throttled.

### Changed
- The `401` error message now points at `dns_nicmanager_totp_secret` and clock
  sync instead of telling the operator to disable 2FA.
- New dependency `pyotp>=2.9.0`.

## [1.0.2] - 2026-06-17

Hardening release from a multi-level review (peer + security + reliability).

### Fixed
- **`403 "API usage not allowed"` is no longer swallowed by the zone walk.** This
  account-wide condition was treated as "wrong zone" and retried against every
  candidate, masking the cause and burning requests. It now aborts immediately
  with a clear "enable API access" message; an ordinary 403 still walks.
- **Cleanup is durable.** `del_txt_record` no longer removes the stored record id
  *before* the DELETE — on a transient failure the id is kept (logged with
  zone + id) so the record isn't silently lost; a `404` (already gone) counts as
  cleaned up.
- Accept a string-typed record `id` in the create response (coerced to int;
  `bool` rejected), so cleanup still works if the API serializes the id as a
  string.
- The "Created TXT record" info log now fires only on actual success.

### Added
- **Bounded retry with backoff** for transient failures (connection errors,
  timeouts, `429`, `502/503/504`). `429` honours `Retry-After`. Auth/zone
  responses (`401/403/404`) are **never** retried, so retries can't amplify
  toward the API's failed-login firewall block.

### Changed
- Dependency floor `requests>=2.32.0` (hygiene).

### Notes
- DNS propagation uses certbot's standard fixed wait
  (`--dns-nicmanager-propagation-seconds`, default 60), as with other certbot
  DNS plugins; active authoritative-NS polling was considered and deferred to
  avoid a `dnspython` dependency for marginal gain.

## [1.0.1] - 2026-06-16

### Fixed
- **Cleanup never removed the challenge record.** `_get_client()` built a new API
  client on every `_perform`/`_cleanup` call, so the record id captured at
  creation was discarded before cleanup ran — every issuance/renewal left an
  orphan `_acme-challenge` TXT record. The client is now cached on the
  authenticator. (Issuance itself was unaffected.)
- **Wildcard certificates left one orphan TXT record.** For `-d domain -d
  *.domain` the base and wildcard challenges share a single
  `_acme-challenge.<domain>` name but use different values (two distinct TXT
  records); the id map was keyed by name only, so the second create overwrote
  the first and cleanup could delete only one. The map is now keyed by
  `(name, value)`.

### Added
- Credential validation now rejects a plaintext `http://`
  `dns_nicmanager_endpoint` (credentials are HTTP Basic auth and must use HTTPS).
- `.pre-commit-config.yaml` (ruff, mypy, basic hygiene hooks) and Dependabot
  config (GitHub Actions + pip).
- CI coverage gate: `pytest` fails under 85 % coverage.
- Expanded edge-case tests (now 93 % coverage): TTL clamping to the API minimum,
  a `202` create response with no `id`, network errors mapped to `PluginError`,
  zone-walk control semantics (a `5xx` aborts immediately and does **not** walk to
  the parent zone; a `401` after a `404` stops the walk), `_candidate_zones`
  generation (prefix strip, ordering, single-label drop, configured-zone
  short-circuit), and rejection of malformed credentials.

### Changed
- CI / publish workflows use `actions/checkout@v6` and `actions/setup-python@v6`
  (Node 24 runtime); artifact actions bumped to v7/v8.
- `ci.yml` declares least-privilege `permissions: contents: read` (resolves the
  CodeQL `actions/missing-workflow-permissions` alerts).

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

[Unreleased]: https://github.com/jp1337/certbot-dns-nicmanager/compare/v1.1.3...HEAD
[1.1.3]: https://github.com/jp1337/certbot-dns-nicmanager/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/jp1337/certbot-dns-nicmanager/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/jp1337/certbot-dns-nicmanager/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/jp1337/certbot-dns-nicmanager/compare/v1.0.2...v1.1.0
[1.0.2]: https://github.com/jp1337/certbot-dns-nicmanager/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/jp1337/certbot-dns-nicmanager/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/jp1337/certbot-dns-nicmanager/compare/v0.2.0...v1.0.0
[0.2.0]: https://github.com/jp1337/certbot-dns-nicmanager/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jp1337/certbot-dns-nicmanager/releases/tag/v0.1.0
