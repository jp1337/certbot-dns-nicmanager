# Troubleshooting & nicmanager API notes

nicmanager publishes no dedicated documentation for its ACME / DNS API beyond
the generic [API reference](https://api.nicmanager.com/docs/v1/). This page
captures real-world behaviour learned while building and operating this plugin,
so you don't have to rediscover it the hard way.

## HTTP status decoder

What the API actually returns, and what it means:

| Response | Meaning | What to do |
| --- | --- | --- |
| `202` | Record created/deleted | Success. |
| `401 {"message":"Authentication error"}` | Wrong **username form** (account auth-method mismatch) or wrong password | Use the username that matches the account's *active authentication method* — see [Authentication](#authentication). Verify the password. |
| `401 {"message":"Authorization error: Too many invalid attempts!"}` | Rate limit after several failed logins | **Stop.** Wait for it to clear. Do not keep trying. |
| `403 {"message":"Authorization error: API usage not allowed"}` | **Auth succeeded**, but API access is not enabled for the account | Contact nicmanager support and ask them to enable API access for the account. |
| `000` / no HTTP response (curl hangs/times out) | Source IP **firewall-blocked** at the network level after too many failed attempts | **Stop all attempts.** The block is per-IP and network-level; it clears with time. |

The `401` → `403` distinction is the key diagnostic: `403 "API usage not
allowed"` means your credentials are **correct** and you only need API access
switched on. `401` means the credentials/username form are being rejected.

## Authentication

- HTTP **Basic auth** against `https://api.nicmanager.com/v1`. Password is sent
  in plain text. (lego's `nicmanager` provider does exactly the same.)
- The basic-auth **username depends on the account's active authentication
  method** (nicmanager Security settings):
  - Method **"E-Mail + Passwort"** → username is the **email**
    (e.g. `acme@pylypiw.com`).
  - Method **login/username** → username is **`login.username`**
    (e.g. `PrivatPylypiw.acme`, login and username joined by a dot).
  - Using the *wrong* form returns `401 "Authentication error"` **even with the
    correct password**. This is the single most confusing failure mode — if
    `login.username` gives 401, try the email (or vice versa).
- **Two-factor authentication (TOTP) must be disabled** on the account used for
  automation. There is no way to supply a rotating code unattended. (lego can
  send a TOTP via the `X-Auth-Token` header from a stored OTP secret, but
  disabling 2FA on a dedicated automation account is simpler.)

## Do NOT brute-force credentials

nicmanager firewall-blocks the **source IP** after a handful of failed logins.
It escalates: first `401 "Too many invalid attempts"`, then a network-level
block where the API stops responding entirely (curl returns `000`). The block
is per-IP and time-based; you cannot clear it from the portal.

Practical consequence: **do not loop over username/password variants.** Make at
most one careful probe, then verify the account settings in the portal before
trying again. If you've locked yourself out, switch to a different source IP or
wait.

## The API-ACME (challenge-only) account

The recommended account type — "API-ACME-Account (Nur ACME-Challenge)" — is
restricted to managing the `_acme-challenge.<zone>` TXT record and nothing else:

| Module | Rights |
| --- | --- |
| Webfrontend | – |
| Account settings | – |
| Domains | – |
| Nameserver | View, Manage (create, edit, delete) |
| Domainsecurity | – |
| Other modules | – |

Crucially, **this account cannot read zones** — `GET /anycast/{zone}` returns
401/403. That is why this plugin never reads zones: it resolves the owning zone
by attempting the record *create* against each candidate (most-specific first)
and using the first that succeeds. See `add_txt_record` in
`certbot_dns_nicmanager/_internal/dns_nicmanager.py`.

## Credentials file gotcha: `#` in the password

certbot reads the INI with `configobj`, which treats an unquoted `#` as the
start of a comment. If your password contains `#`, **quote it**:

```ini
dns_nicmanager_password = "p#ssw0rd#with#hashes"
```

Symptom if you forget: certbot reports `dns_nicmanager_password is required`
even though the line is present.

## API endpoints used (AnycastDNS, v1)

| Operation | Request |
| --- | --- |
| Create | `POST /v1/anycast/{zone}/records` — body `{"name","type":"TXT","value","ttl"}` (ttl 900–2147483647) → `202` with `{"id",...}` |
| Delete | `DELETE /v1/anycast/{zone}/records/{id}` → `202` |

`{zone}` accepts the zone name (e.g. `example.com`) or its numeric id. The
record `name` is the full node name (e.g. `_acme-challenge.example.com`), as in
nicmanager's own create example. The create response's numeric `id` is what you
need to delete the record afterwards.

## Manual fallback while the API is unavailable

If API access isn't enabled yet but you need certs now, you can issue manually
with `certbot --manual --preferred-challenges dns` and add the TXT records by
hand in the nicmanager UI. One sharp edge:

> A `-d example.com -d *.example.com` certificate produces **two** challenges,
> both at `_acme-challenge.example.com` but with **different values**. Both
> values must exist **simultaneously** as two separate TXT records when Let's
> Encrypt validates. Add the second value as an additional record — do **not**
> replace the first.

(Let's Encrypt may reuse a recently-validated authorization, in which case only
one challenge appears — but don't rely on it.)

Manually issued certificates do **not** auto-renew; switch back to this plugin
once API access is enabled.
