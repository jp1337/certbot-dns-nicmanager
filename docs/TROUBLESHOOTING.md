# Troubleshooting

Certbot writes everything the plugin logs to
`/var/log/letsencrypt/letsencrypt.log`; add `-v` for more detail on screen.

## API responses

| Response | Meaning | Fix |
| --- | --- | --- |
| `401 Authentication error` | Wrong username form or password | Username form must match the account's authentication method — see [Account](ACCOUNT.md#3-pick-the-right-username-form). A `#` in the password must be [quoted](CONFIGURATION.md#the--in-passwords) |
| `401 Missing 2FA token header (X-Auth-Token)` | Account has 2FA, no secret configured | Set `dns_nicmanager_totp_secret` |
| `403 Authorization error: API usage not allowed` | Login works, API access is off | Ask nicmanager support to enable API access |
| `401 Too many invalid attempts!` | Too many failed logins | **Stop** — see [lockout](#lockout-after-failed-logins) |
| no response at all, timeouts | Source IP blocked at network level | **Stop** — see [lockout](#lockout-after-failed-logins) |

`401` means the credentials are rejected; `403 "API usage not allowed"` means
they are **correct** and only the API permission is missing.

## Lockout after failed logins

nicmanager blocks the **source IP** after a handful of failed logins: first
`401 "Too many invalid attempts!"`, then the API stops answering. The block is
per IP and clears with time; the portal cannot lift it.

- Never loop over username or password variants.
- Check the account settings in the portal, then try once.
- With 2FA: check the clock (`timedatectl`). A skewed clock fails every code.

## Plugin messages

| Message | Meaning | Action |
| --- | --- | --- |
| `Could not create the ACME challenge record for … in any candidate zone` | Every candidate zone answered 403/404 | The account may not manage this domain, or set [`dns_nicmanager_zone`](CONFIGURATION.md#when-to-set-dns_nicmanager_zone) |
| `nicmanager API access is not enabled for this account` | 403 "API usage not allowed" | Ask support to enable API access |
| `dns_nicmanager_totp_secret is not a valid base32 TOTP secret` | Typo, or the secret is shorter than 16 characters | Copy the secret again from the portal |
| `dns_nicmanager_endpoint must be an https:// URL` | Plain-HTTP endpoint configured | Use `https://` or remove the line |
| `Error communicating with the nicmanager API` | Network error after three attempts | Check connectivity to `api.nicmanager.com` |
| `Could not delete TXT record … in zone … (id …)` | Cleanup failed; the certificate is fine | [Remove the record](#leftover-challenge-records) |
| `… nicmanager returned no id; automatic cleanup will not be possible` | Record created, id missing in the answer | [Remove the record](#leftover-challenge-records) after the run |
| `Retrying POST … a duplicate _acme-challenge TXT record may remain` | A create timed out and was retried | Check the zone for a second record after the run |
| `No stored record id for …; skipping cleanup` | The create had failed or returned no id | Nothing to clean up from this run |

## Leftover challenge records

A leftover `_acme-challenge` TXT record does no harm: its token is single-use
and Let's Encrypt ignores records it did not ask for. To tidy up, delete it in
the nicmanager portal under the zone's DNS records; the log line names zone and
record id.

## Validation fails although the record was created

`Incorrect TXT record` or `No TXT record found` after `Created TXT record` in
the log: the CA looked before the record reached all nameservers. Raise
`--dns-nicmanager-propagation-seconds`, e.g. to `120`.

## Certificates now, API access later

Until API access is enabled you can issue by hand:
`certbot certonly --manual --preferred-challenges dns -d example.com -d '*.example.com'`
and add the TXT records in the portal.

A certificate for `example.com` **and** `*.example.com` asks for **two** values
at the same name `_acme-challenge.example.com`. Both must exist at the same time
as two separate TXT records — add the second, do not replace the first.

Manual certificates do not renew automatically. Once API access works, issue
again with `--authenticator dns-nicmanager`.
