# Setting up the nicmanager account

The plugin needs one nicmanager login that may create and delete the
`_acme-challenge` TXT record of your zones. Use a dedicated one.

## 1. Create an API-ACME account

In the nicmanager portal, create an account of type **"API-ACME-Account (Nur
ACME-Challenge)"**. nicmanager restricts it to the challenge record:

| Module | Rights |
| --- | --- |
| Nameserver | View, Manage (create, edit, delete) |
| Webfrontend, Account settings, Domains, Domainsecurity, other modules | – |

A leaked password for this account cannot change other records, transfer
domains or read account data. It also **cannot read zones**, which is why the
plugin never tries to: it finds the zone by attempting the create.

## 2. Make sure API access is enabled

If the first run fails with `403 "Authorization error: API usage not allowed"`,
the login works but the account may not use the API. Ask nicmanager support to
enable API access for it.

## 3. Pick the right username form

The username depends on the account's **active authentication method**
(nicmanager security settings):

| Authentication method | `dns_nicmanager_username` |
| --- | --- |
| "E-Mail + Passwort" | the email, e.g. `acme@example.com` |
| login / username | `login.username`, e.g. `mylogin.acmeuser` |

The wrong form returns `401 "Authentication error"` **even with the correct
password**. Check the method in the portal; do not try both forms in a loop —
see [lockout](TROUBLESHOOTING.md#lockout-after-failed-logins).

## 4. Two-factor authentication (optional)

With 2FA enabled, every API request needs a current TOTP code. Put the
account's base32 secret into `dns_nicmanager_totp_secret`; the plugin generates
the code for each request.

- Spaces in the secret are fine (`ABCD EFGH …` as the portal shows it).
- 16 characters (80 bits) or more; shorter secrets are rejected as truncated.
- The host clock must be accurate (NTP). A skewed clock makes every code
  invalid, and invalid codes count toward the lockout.
- The secret file then holds both factors: protect it with `chmod 600`.

Next: [Configuration](CONFIGURATION.md).
