# Architecture

This document describes the design of `certbot-dns-nicmanager` for maintainers
and contributors. For operational troubleshooting, see
[`docs/TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

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
  and password, and `Accept: application/json`.
- Implements zone-walk zone resolution (see below).
- Stores `(zone, record_id)` tuples in `self._created` keyed by record name, so
  cleanup can delete by numeric id without any GET request.
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
                    |           store (zone, id) in self._created[record_name]
                    |           return (done)
                    |
                    +-- 403/404 -> store as last_error, continue to next candidate
                    |
                    +-- 401  -> raise PluginError immediately (do not swallow)
                    |
                    +-- other -> raise PluginError immediately

    [ACME server validates the TXT record]

certbot calls _cleanup(domain, validation_name, validation)
    |
    +-- _NicmanagerClient.del_txt_record(validation_name, validation)
            |
            +-- pop (zone, id) from self._created
            |
            +-- DELETE /anycast/{zone}/records/{id}
            |       202 -> log success
            |       error -> log warning (never raise; cleanup must not mask issuance)
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

## API Endpoints Used

Base URL: `https://api.nicmanager.com/v1` (overridable via `dns_nicmanager_endpoint`).

| Operation | Method + Path | Request body | Success response |
|-----------|--------------|--------------|-----------------|
| Create TXT record | `POST /anycast/{zone}/records` | `{"name": str, "type": "TXT", "value": str, "ttl": int}` | `202` with `{"id": int, ...}` |
| Delete TXT record | `DELETE /anycast/{zone}/records/{id}` | — | `202` |

`{zone}` is the zone name (e.g. `example.com`). The `name` field is the full
record node (e.g. `_acme-challenge.example.com`). The numeric `id` from the
create response is the only safe way to delete the record; the restricted
account cannot list records to find it after the fact.

Authentication is HTTP Basic. The username form must match the nicmanager
account's active authentication method: the account email for "E-Mail + Passwort"
accounts, or `login.username` otherwise. See
[ADR-003](decisions/ADR-003-basic-auth-username-and-cleanup-by-id.md) and
[`docs/TROUBLESHOOTING.md`](TROUBLESHOOTING.md#authentication) for the exact
rules.

---

## Credentials INI

The INI file is read by Certbot's `_configure_credentials` /
`CredentialsConfiguration` machinery (using `configobj` under the hood).

| Key | Required | Default | Notes |
|-----|----------|---------|-------|
| `dns_nicmanager_username` | Yes | — | Must match the account's active auth method. |
| `dns_nicmanager_password` | Yes | — | Quote with `"..."` if it contains `#`. |
| `dns_nicmanager_endpoint` | No | `https://api.nicmanager.com/v1` | Override for testing or staging. |
| `dns_nicmanager_zone` | No | — | Short-circuits zone-walk; use for unusual multi-suffix setups. |

---

## Packaging

| Aspect | Detail |
|--------|--------|
| Build backend | `setuptools>=64`, PEP 517 |
| Entry point group | `certbot.plugins` → `dns-nicmanager` |
| Entry point target | `certbot_dns_nicmanager._internal.dns_nicmanager:Authenticator` |
| Python requirement | `>=3.10` |
| Runtime dependencies | `certbot>=2.0.0`, `requests>=2.20.0` |
| Packages | `certbot_dns_nicmanager`, `certbot_dns_nicmanager._internal` |
| Type stubs | `py.typed` marker present; `types-requests` used for mypy |
| Distribution | Release tarball; not yet on PyPI |

---

## Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Plugin base class | `certbot.plugins.dns_common.DNSAuthenticator` | Provides credential loading, propagation wait, and the `_perform`/`_cleanup` lifecycle; avoids reimplementing certbot's plugin protocol. |
| HTTP client | `requests` + `requests.Session` | Standard, well-tested; session reuse keeps the Basic-auth header and connection pool across multiple calls in the same run. |
| Zone candidate generation | `certbot.plugins.dns_common.base_domain_name_guesses` | Reuses certbot's public-suffix-aware registrable-domain logic; avoids bundling a PSL or rolling a custom suffix splitter. |
| Linting | `ruff` (rules E, F, W, I, UP, B) | Fast; enforces import ordering and modern-Python upgrades in one pass. |
| Type checking | `mypy` (strict equality, no redundant casts) | Catches wrong-type bugs at CI time; `py.typed` lets downstream type-checkers see the stubs. |
| Test framework | `pytest` + `requests-mock` | `requests-mock` intercepts `requests.Session` calls without patching at the socket level, keeping tests fast and deterministic. |
| CI matrix | Python 3.10–3.13 | Covers the full declared support range. |

---

## Test Structure

`tests/test_dns_nicmanager.py` contains two test classes:

- `AuthenticatorTest` — extends `dns_test_common.BaseAuthenticatorTest`; mocks
  `_get_client` to verify that `_perform` and `_cleanup` call the correct client
  methods with the correct arguments, without hitting the network.

- `NicmanagerClientTest` — tests `_NicmanagerClient` in isolation using
  `requests_mock.Mocker()`. Covers: successful create, zone-walk on 404, zone-
  walk on 403, configured-zone short-circuit, 401 propagation, all-candidates-
  fail error, delete by remembered id, delete with no stored id (no-op), and
  delete error swallowing.

Coverage is measured with `pytest-cov` and reported on every run.
