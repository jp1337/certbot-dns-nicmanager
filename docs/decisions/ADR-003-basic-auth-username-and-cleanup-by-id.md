# ADR-003: Pass the username verbatim; delete records strictly by numeric id

**Date:** 2026-06-14
**Status:** Accepted

## Context

Two related implementation choices arose during initial development and a
subsequent real-world debugging session. They are documented together because
both stem from the same root constraint: the restricted API-ACME account cannot
read or list records, which forces specific design choices in both authentication
and cleanup.

---

### Part A: HTTP Basic-auth username form

The nicmanager API uses HTTP Basic authentication. The correct value for the
Basic-auth username is **not** fixed — it depends on the authentication method
the account has configured in the nicmanager Security settings:

- **"E-Mail + Passwort" accounts**: the username must be the account's **email
  address** (e.g. `acme@example.com`).
- **Login/username accounts**: the username must be `login.username`, the login
  and username joined by a dot (e.g. `PrivateLogin.acmeuser`).

Using the wrong form — for example, using `login.username` when the account is
configured for email auth, or vice versa — returns `HTTP 401 "Authentication
error"` even when the password is exactly correct. This is the most common
cause of unexplained 401 failures.

This distinction was confirmed empirically during a debugging session and is not
clearly documented in the nicmanager API reference. It is documented in detail
in [`docs/TROUBLESHOOTING.md`](../TROUBLESHOOTING.md#authentication).

The plugin provides no mechanism to detect or infer which form the account
requires, because the API gives no indication — both forms go through the same
endpoint and return the same 401 on mismatch.

**Alternatives considered:**

- **Try both forms automatically**: rejected. nicmanager firewall-blocks the
  source IP after a small number of failed login attempts, escalating from
  `401 "Too many invalid attempts"` to a network-level block where the API stops
  responding entirely. Automatically trying two username forms on every run
  doubles the failure rate if the configuration is wrong, and substantially
  increases the risk of triggering a lockout.

- **Validate the username form in the plugin**: rejected. The plugin has no way
  to distinguish an email from `login.username` reliably without either parsing
  the string (fragile) or making an additional API call (which would fail for
  the same reason if the form were wrong).

**Decision (Part A):** The `dns_nicmanager_username` INI value is passed
verbatim to `HTTPBasicAuth`. The operator is responsible for supplying the
correct form for their account's authentication method. The 401 error message
includes a reminder about the two possible forms to make diagnosis faster.

---

### Part B: Cleanup deletes strictly by numeric record id

After the challenge TXT record is created, Certbot calls `_cleanup` to remove
it. The most general approach would be to find the record by name and content
using a GET or list request, then delete it.

The restricted API-ACME account cannot list records. `GET /anycast/{zone}` and
any record-listing endpoint return 401/403 for this account type (this is also
what drives the zone-walk design in
[ADR-002](ADR-002-zone-resolution-without-zone-reads.md)).

The `POST /anycast/{zone}/records` response body includes the newly-created
record's numeric `id`. Because this is available immediately and requires no
additional API call, storing it is the natural cleanup strategy.

**Alternatives considered:**

- **Probe for the record by name/content at cleanup time**: rejected. Requires
  at least one GET or list call, which the API-ACME account cannot make.

- **Delete all TXT records matching the name**: rejected. Even if listing were
  possible, this would be dangerous when the same zone has multiple
  `_acme-challenge` TXT records (e.g. when certifying both the apex and the
  wildcard simultaneously, which ACME requires two values at the same name).

**Decision (Part B):** `_NicmanagerClient` stores a `(zone, record_id)` tuple
in `self._created` keyed by the fully-qualified record name at creation time.
Cleanup pops the entry and issues `DELETE /anycast/{zone}/records/{id}`.

If no id is stored — either because the create failed, or because the API
response body contained no `id` field — cleanup logs a warning and returns
without making any request. This is deliberate: a cleanup failure must never
mask a successful or differently-failed issuance. Certbot treats cleanup errors
as non-fatal warnings by convention, and this implementation matches that
expectation.

## Consequences

- Operators must supply the username in exactly the form their nicmanager
  account requires. The credentials INI comment and error messages call this
  out. The TROUBLESHOOTING document explains how to determine the correct form.
- Two-factor authentication (TOTP) initially had to be disabled on the automation
  account. **Superseded in v1.1.0:** the plugin now supplies the rotating code via
  the `X-Auth-Token` header from an optional `dns_nicmanager_totp_secret`, so 2FA
  can stay enabled. Reuse of a code within its 30-second window is accepted by the
  API, so no wait-for-next-window handling is required.
- Cleanup is strictly by id. A missed cleanup (no stored id) logs a warning but
  does not fail the issuance. The orphaned TXT record must be removed manually
  from the nicmanager UI if it matters.
- The `_created` dict is in-memory and per-client-instance. A `_NicmanagerClient`
  is constructed fresh for each `_get_client()` call; across a process restart
  or a Certbot invocation where `_perform` and `_cleanup` run in separate
  processes, stored ids would be lost. In practice Certbot runs `_perform` and
  `_cleanup` in the same process within the same renewal run, so this is not a
  problem in the current architecture.
