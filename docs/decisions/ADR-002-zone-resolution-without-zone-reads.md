# ADR-002: Resolve the owning zone by attempting the record CREATE, not by reading zones

**Date:** 2026-06-14
**Status:** Accepted

## Context

To create the `_acme-challenge` TXT record via the nicmanager API, the plugin
must first determine which zone owns the domain being certified. For example,
when certifying `sub.example.com`, the owning zone might be `sub.example.com`
itself or `example.com`, depending on the DNS delegation.

The obvious approach is to read the list of zones from the API, match the
domain against them, and then POST the record into the correct zone. The
nicmanager API exposes `GET /anycast/{zone}` (and a zone-list endpoint) for
this purpose.

However, the nicmanager **API-ACME account** — the restricted account type that
nicmanager specifically recommends for automation — cannot read zones. A GET
against any zone endpoint returns `401` or `403` for this account type. This is
by design: the account is scoped to managing only `_acme-challenge.<zone>` TXT
records and nothing else.

The plugin is designed with the API-ACME account as its primary target. Falling
back to a privileged account solely to enable zone reads would undermine the
security model the recommended account type provides.

### Alternatives considered

**GET-based longest-suffix match**

Query `GET /anycast/{candidate}` for each suffix of the domain (most-specific
first) and use the first that returns 200. This is the conventional approach
used by other Certbot DNS plugins.

Rejected: returns 401/403 for the API-ACME account on every candidate, making
the zone undiscoverable for the exact account type this plugin is built for.

**Require an explicit `dns_nicmanager_zone` in the INI**

Make the operator declare the zone name; perform no automatic resolution at all.

Rejected as the default: it creates unnecessary friction for the common case
where the domain being certified maps directly to a zone (e.g. `example.com` is
both the zone and the domain). Accepted as an optional override
(`dns_nicmanager_zone`) for unusual multi-zone-suffix setups where the walk
would produce ambiguous candidates.

## Decision

The plugin resolves the owning zone by **attempting the record CREATE**
(`POST /anycast/{zone}/records`) against each candidate zone, most-specific
first, and using the first that succeeds:

1. The `_acme-challenge.` prefix is stripped from the validation name (it is
   never part of a zone name).
2. `dns_common.base_domain_name_guesses` generates an ordered list of
   registrable-domain candidates from the remaining name (the same helper used
   by other Certbot DNS plugins for GET-based zone walks).
3. Single-label results are dropped; they are never a usable zone in this API.
4. If `dns_nicmanager_zone` is set in the INI, the list is replaced by that
   single value, skipping all of the above.
5. For each candidate a POST is attempted:
   - **2xx** — the zone is the owner. The record id from the response body is
     stored for cleanup and the walk terminates.
   - **403 or 404** — treated as "this is not the right zone"; the walk
     continues to the next candidate. These are the responses the API returns
     when the zone does not exist or the scoped account does not own it.
   - **401** — genuine authentication failure (wrong credentials, not a zone
     mismatch). Never swallowed; raised immediately as a `PluginError`.
   - Any other error — raised immediately.
6. If all candidates are exhausted, a `PluginError` is raised with the list of
   candidates tried.

This approach requires no read permissions on the API-ACME account.

## Consequences

- The plugin works correctly with the API-ACME account, which is the minimal-
  privilege setup nicmanager recommends.
- For deep subdomains (e.g. `a.b.c.example.com`), a small number of extra POST
  attempts are made against non-owner zones before the correct one is found.
  These POST attempts are expected to return 403/404 quickly and add negligible
  latency in practice.
- Cleanup must delete the record by the numeric id captured at creation. Because
  the account cannot list records, there is no fallback if the id was never
  stored (e.g. the create response contained no `id` field). In that case
  cleanup logs a warning and returns without making any request (see
  [ADR-003](ADR-003-basic-auth-username-and-cleanup-by-id.md)).
- `dns_nicmanager_zone` provides an escape hatch for setups where zone-walk
  ambiguity is a concern or where the walk consistently reaches the wrong
  candidate.
