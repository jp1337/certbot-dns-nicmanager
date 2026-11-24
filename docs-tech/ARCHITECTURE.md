# Architecture

This document describes the design of `certbot-dns-nicmanager` for maintainers
and contributors. For operational troubleshooting, see
the [operator documentation](../docs/README.md).

---

## Purpose

`certbot-dns-nicmanager` is a Certbot `dns-01` authenticator plugin. It
automates the ACME DNS-01 challenge by creating and deleting the
`_acme-challenge.<domain>` TXT record through the nicmanager AnycastDNS v1 API.
Because DNS-01 is the only ACME challenge type that can issue wildcard
certificates, this is the sole supported challenge mode. See
[ADR-001](decisions/ADR-001-dns-01-challenge-only.md) for the rationale.

---

## Component Overview

The plugin consists of two classes in
`certbot_dns_nicmanager/_internal/dns_nicmanager.py`:

```
certbot (CLI / renewal daemon)
        |
        |  dns-01 challenge lifecycle
        v
  Authenticator                          (certbot.plugins.dns_common.DNSAuthenticator)
        |
        |  add_txt_record / del_txt_record
        v
  _NicmanagerClient                      (requests.Session wrapper)
        |
        |  POST / DELETE (HTTP Basic auth)
        v
  api.nicmanager.com/v1/anycast/...
```

### `Authenticator`

Registered in the `certbot.plugins` entry-point group under the name
`dns-nicmanager` (see `pyproject.toml`). Certbot discovers it at runtime via
`importlib.metadata` and makes it available as `--authenticator dns-nicmanager`.

Responsibilities:

- Parses and validates the credentials INI file
  (`--dns-nicmanager-credentials`), rejecting missing username or password with
  a clear `PluginError`.
- Bridges Certbot's `_perform` / `_cleanup` lifecycle hooks to
  `_NicmanagerClient.add_txt_record` and `del_txt_record`.
- Lazily creates and **caches** a single `_NicmanagerClient` in `_get_client`
  (built from the INI's username, password, optional endpoint, and optional
  zone). Caching is required: the record ids captured during `_perform` live on
  the client and must survive until `_cleanup`.

Key certbot base-class features used:

| Base-class feature | How it is used |
|--------------------|----------------|
| `_configure_credentials` | Reads and validates the INI, stores the `CredentialsConfiguration` object. |
| `add_parser_arguments` | Adds `--dns-nicmanager-credentials`; inherits `--dns-nicmanager-propagation-seconds` (default: 60 s). |
| `dns_common.base_domain_name_guesses` | Generates ordered zone candidates for zone-walk resolution (delegated to `_NicmanagerClient._candidate_zones`). |

### `_NicmanagerClient`

A private HTTP client. Not part of any public API — the leading underscore is
intentional and should be preserved.

Responsibilities:

- Maintains a `requests.Session` with HTTP Basic auth configured from username
  and password, and `Accept: application/json`. With 2FA configured, every
  request attempt carries a freshly generated TOTP code in `X-Auth-Token`.
- Retries `429`/`502`/`503`/`504`, timeouts and connection errors up to three
  attempts (exponential backoff, `Retry-After` honoured). A retried `POST` after
  an ambiguous failure (anything but `429`/`503`/connect timeout) logs a warning:
  the first attempt may have created a record that cleanup never sees.
- Implements zone-walk zone resolution (see below).
- Stores `(zone, record_id)` tuples in `self._created` keyed by
  `(record name, record value)`, so cleanup can delete by numeric id without any
  GET request. The value is part of the key because a wildcard certificate
  (`-d example.com -d '*.example.com'`) creates two records with the same name.
- Classifies API error responses into `_ForbiddenError` (403),
  `_NotFoundError` (404), and `errors.PluginError` (all others), enabling the
  zone walk to distinguish "wrong zone" from "auth failure".

The two sentinel exception subclasses, `_ForbiddenError` and `_NotFoundError`,
are defined at module level and are only used internally to control the walk
loop. They are never raised to Certbot callers directly.

---

## Challenge Flow

```
certbot calls _perform(domain, validation_name, validation)
    |
    +-- _NicmanagerClient.add_txt_record(validation_name, validation, ttl=900)
            |
            +-- _candidate_zones(validation_name)
            |       strips "_acme-challenge." prefix
            |       calls dns_common.base_domain_name_guesses(name)
            |       drops single-label results (no dot)
            |       returns ordered list, most-specific first
            |       (or [configured_zone] if dns_nicmanager_zone is set)
            |
            +-- for each candidate zone:
                    POST /anycast/{zone}/records
                      body: {name, type:"TXT", value, ttl}
                    |
                    +-- 2xx  -> extract id from response body
                    |           store (zone, id) in self._created[(name, value)]
                    |           return (done)
                    |
                    +-- 403 "API usage not allowed" -> raise PluginError
                    |           immediately (account-wide, not zone-specific)
                    |
                    +-- other 403, 404 -> store as last_error, next candidate
                    |
                    +-- 401  -> raise PluginError immediately (do not swallow)
                    |
                    +-- other -> raise PluginError immediately

    [ACME server validates the TXT record]

certbot calls _cleanup(domain, validation_name, validation)
    |
    +-- _NicmanagerClient.del_txt_record(validation_name, validation)
            |
            +-- look up (zone, id) in self._created[(name, value)]
            |
            +-- DELETE /anycast/{zone}/records/{id}
            |       2xx -> log success, drop the entry
            |       404 -> already gone: log, drop the entry
            |       error -> log warning with zone + id for manual removal
            |                (never raise; cleanup must not mask issuance)
            |
            +-- if no stored id: log warning, return (cannot list records)
```

TTL is fixed at `TXT_RECORD_TTL = 900` (the API-documented minimum). Any value
passed in below 900 is silently clamped up.

---

## Zone Resolution Without Zone Reads

The plugin resolves the owning zone by attempting the record CREATE against
candidate zones, not by reading zone metadata. This is a deliberate design
decision driven by the capabilities of the restricted API-ACME account type:
that account cannot perform `GET /anycast/{zone}` and returns 401/403 on zone
reads.

The algorithm is described in full in
[ADR-002](decisions/ADR-002-zone-resolution-without-zone-reads.md).

---

## API, credentials, packaging

Not repeated here, so they cannot drift:

| Topic | Source of truth |
| --- | --- |
| Endpoints, error answers, account limits | [NICMANAGER-API.md](NICMANAGER-API.md) |
| Credentials keys and CLI arguments | [docs/CONFIGURATION.md](../docs/CONFIGURATION.md) |
| Dependencies, Python range, entry point | [`pyproject.toml`](../pyproject.toml) |
| CI matrix, release, dependency updates | [RELEASING.md](RELEASING.md) |

---

## Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Plugin base class | `certbot.plugins.dns_common.DNSAuthenticator` | Provides credential loading, propagation wait, and the `_perform`/`_cleanup` lifecycle; avoids reimplementing certbot's plugin protocol. |
| HTTP client | `requests` + `requests.Session` | Session reuse keeps the Basic-auth header and connection pool across the calls of one run. |
| 2FA | `pyotp` (`_ProviderTOTP`, floor lowered to 80 bits) | The provider issues the secret; pyotp's own 112-bit floor would reject common secrets. |
| Zone candidate generation | `certbot.plugins.dns_common.base_domain_name_guesses` | Reuses certbot's registrable-domain logic; no bundled public-suffix list. |
| Lint, format, types | `ruff check`, `ruff format`, `mypy` | Run in CI and as pre-commit hooks. |
| Tests | `pytest` + `requests-mock` | Intercepts `requests.Session` calls; no network, no real account. |

---

## Test Structure

| File | Covers |
| --- | --- |
| `tests/test_dns_nicmanager.py` · `AuthenticatorTest` | Credential validation, `_perform`/`_cleanup` wiring (client mocked) |
| `tests/test_dns_nicmanager.py` · `NicmanagerClientTest` | The HTTP client against `requests_mock`: zone walk, 401/403/404 handling, retries and their warnings, TOTP header, cleanup by id |
| `tests/test_docs_boundary.py` | Builds the sdist: `docs/` ships, `docs-tech/` does not; Markdown links resolve |

Coverage is measured with `pytest-cov`; below 85 % fails the run.
