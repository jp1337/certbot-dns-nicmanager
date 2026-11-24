# nicmanager API: what the plugin relies on

nicmanager documents the API only generically
([API reference](https://api.nicmanager.com/docs/v1/)). This page records the
behaviour the plugin depends on, as observed against the live API. Change the
code and this page together.

## Endpoints

| Operation | Request | Answer |
| --- | --- | --- |
| Create | `POST /v1/anycast/{zone}/records`, body `{"name", "type": "TXT", "value", "ttl"}` | `202` with `{"id": …}` |
| Delete | `DELETE /v1/anycast/{zone}/records/{id}` | `202`; `404` when already gone |

- `{zone}` takes the zone name (`example.com`) or its numeric id.
- `name` is the full node name (`_acme-challenge.example.com`), as in
  nicmanager's own create example.
- `ttl` accepts 900–2147483647; the plugin always sends 900.
- The `id` may arrive as a number or as a digit string; the plugin accepts both.

## Authentication

- HTTP Basic auth. lego's `nicmanager` provider authenticates the same way.
- The username form follows the account's active authentication method (email
  vs `login.username`); the wrong form is a plain `401 "Authentication error"`.
- 2FA accounts need a TOTP code in `X-Auth-Token` on every request; without it:
  `401 "Missing 2FA token header (X-Auth-Token)"`. A code may be reused within
  its 30-second window, so the plugin generates one per attempt and never waits.

## The restricted API-ACME account

- Cannot read zones: `GET /anycast/{zone}` returns 401/403. This is the reason
  for zone detection by create attempt ([ADR-002](decisions/ADR-002-zone-resolution-without-zone-reads.md)).
- Cannot list records, so a record whose id is lost cannot be found again
  ([ADR-003](decisions/ADR-003-basic-auth-username-and-cleanup-by-id.md)).
- Creating in a zone it does not manage: `403` or `404` — the signal to try the
  next candidate.

## Error answers

| Answer | Plugin reaction |
| --- | --- |
| `401` | Abort immediately; never retried (retries walk toward the IP block) |
| `403 "Authorization error: API usage not allowed"` | Abort immediately: account-wide, not a zone mismatch |
| other `403`, `404` on create | Next candidate zone |
| `429`, `503` | Retry; the request was not processed |
| `502`, `504`, timeouts | Retry; a create may have been applied → warning |
| `401 "Too many invalid attempts!"`, then no answer | IP block after failed logins; clears with time |
