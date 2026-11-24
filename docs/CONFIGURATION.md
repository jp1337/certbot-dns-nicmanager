# Configuration

## Credentials file

Certbot reads the credentials from an INI file, e.g.
`/etc/letsencrypt/nicmanager.ini`. Protect it: `chmod 600`.

| Key | Required | Meaning |
| --- | --- | --- |
| `dns_nicmanager_username` | yes | Email or `login.username`, depending on the account — see [Account](ACCOUNT.md#3-pick-the-right-username-form) |
| `dns_nicmanager_password` | yes | Account password. **Quote it if it contains `#`** |
| `dns_nicmanager_totp_secret` | only with 2FA | Base32 TOTP secret, ≥ 16 characters, spaces allowed |
| `dns_nicmanager_endpoint` | no | API base URL, must be `https://`. Default `https://api.nicmanager.com/v1` |
| `dns_nicmanager_zone` | no | Skip zone detection and always use this zone — for **every** domain of the certificate |

```ini
dns_nicmanager_username = mylogin.acmeuser
dns_nicmanager_password = "p#ssw0rd"
# dns_nicmanager_totp_secret = JBSW Y3DP EHPK 3PXP
```

A commented template: [`examples/nicmanager.ini`](../examples/nicmanager.ini).

### The `#` in passwords

Certbot parses the file with `configobj`, where an unquoted `#` starts a
comment and would cut the password short — a `401` on every run, until
nicmanager blocks the IP. The plugin therefore stops before sending anything:

| In the file | Result |
| --- | --- |
| `p#ss` or `#abc` | stops: "the password contains '#' … Quote it" |
| `"p#ss"` or `'p#ss'` | password `p#ss` |
| `secret  # note` | password `secret`; a `#` after a space is a comment |

Quote the value.

### When to set `dns_nicmanager_zone`

Almost never. Detection tries the candidate zones of each name, most specific
first (`sub.example.com`, then `example.com`), and takes the first one the API
accepts. Set it only if detection picks the wrong zone. It applies to all
domains of the certificate, so do not set it for a certificate that spans
several zones.

## Command-line arguments

| Argument | Default | Meaning |
| --- | --- | --- |
| `--authenticator dns-nicmanager` | – | Selects this plugin |
| `--dns-nicmanager-credentials` | – (required) | Path to the credentials file |
| `--dns-nicmanager-propagation-seconds` | `60` | Wait between creating the record and asking the CA to check it |

Raise the propagation time if validation fails with "incorrect TXT record" or
"no TXT record found" although the plugin logged the record as created.

## Renewal

Certbot stores the authenticator, the credentials path and every other option
you passed in `/etc/letsencrypt/renewal/<name>.conf`. `certbot renew` reuses
them, so:

- schedule `certbot renew`: distribution packages install a systemd timer or
  cron job, a `pip` install brings none;
- keep the credentials file at the same path, readable by the user that runs
  the renewal;
- test the whole chain without issuing a certificate:

```bash
certbot renew --dry-run
```

## Install next to Certbot

The plugin must live in the same Python environment as Certbot:

| Certbot installed via | Install the plugin with |
| --- | --- |
| `pip` / a virtualenv | `pip install certbot-dns-nicmanager` in that environment |
| your distribution's package | a virtualenv with both: `pip install certbot certbot-dns-nicmanager` |
| `snap` | not available as a snap; use a virtualenv as above |

`certbot plugins` lists `dns-nicmanager` when the install worked.
