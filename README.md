<!-- markdownlint-disable MD033 MD041 -->
<!-- Every link and image is absolute: PyPI renders this file too, and it cannot
     resolve a path relative to the repository. -->
<p align="center">
  <img src="https://raw.githubusercontent.com/jp1337/certbot-dns-nicmanager/main/.github/icon.svg" alt="" width="88" height="88">
</p>

<h1 align="center">certbot-dns-nicmanager</h1>

<p align="center"><em>Wildcard certificates for nicmanager domains. Issued and renewed without you.</em></p>

<!-- One badge service, so the set shares a shape, a typeface and a logo
     treatment. Every badge reads from the workflows, PyPI or the repository,
     so none of them can drift the way a hand-written version number could. -->
<!-- markdownlint-disable MD013 -->
<p align="center">
  <a href="https://github.com/jp1337/certbot-dns-nicmanager/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/jp1337/certbot-dns-nicmanager/ci.yml?branch=main&label=tests&logo=github&logoColor=white" alt="Tests"></a>
  <a href="https://github.com/jp1337/certbot-dns-nicmanager/actions/workflows/publish.yml"><img src="https://img.shields.io/github/actions/workflow/status/jp1337/certbot-dns-nicmanager/publish.yml?label=publish&logo=pypi&logoColor=white" alt="Publish"></a>
  <a href="https://pypi.org/project/certbot-dns-nicmanager/"><img src="https://img.shields.io/pypi/v/certbot-dns-nicmanager?logo=pypi&logoColor=white&label=pypi" alt="PyPI version"></a>
  <a href="https://pypistats.org/packages/certbot-dns-nicmanager"><img src="https://img.shields.io/pypi/dm/certbot-dns-nicmanager?logo=pypi&logoColor=white&label=downloads" alt="Downloads per month"></a>
</p>

<p align="center">
  <a href="https://github.com/jp1337/certbot-dns-nicmanager/releases/latest"><img src="https://img.shields.io/github/v/release/jp1337/certbot-dns-nicmanager?logo=github&logoColor=white&label=release" alt="Latest release"></a>
  <a href="https://pypi.org/project/certbot-dns-nicmanager/"><img src="https://img.shields.io/pypi/pyversions/certbot-dns-nicmanager?logo=python&logoColor=white&label=python" alt="Python versions"></a>
  <a href="https://www.apache.org/licenses/LICENSE-2.0"><img src="https://img.shields.io/github/license/jp1337/certbot-dns-nicmanager?logo=opensourceinitiative&logoColor=white&label=license&color=blue" alt="Apache-2.0"></a>
  <a href="https://ko-fi.com/jp1337"><img src="https://img.shields.io/badge/ko--fi-support-13C3FF?logo=kofi&logoColor=white" alt="Support on Ko-fi"></a>
</p>

<p align="center">
  <a href="https://pypi.org/project/certbot-dns-nicmanager/"><strong>PyPI</strong></a> ·
  <a href="https://github.com/jp1337/certbot-dns-nicmanager/blob/main/docs/TROUBLESHOOTING.md"><strong>Troubleshooting</strong></a> ·
  <a href="https://github.com/jp1337/certbot-dns-nicmanager/blob/main/CHANGELOG.md">Changelog</a>
</p>
<!-- markdownlint-enable MD013 -->

A [Certbot](https://certbot.eff.org/) plugin for
[nicmanager](https://www.nicmanager.com/) **AnycastDNS**. It answers the `dns-01`
challenge through the [nicmanager API](https://api.nicmanager.com/docs/v1/):
**`*.example.com` certificates, with an account that can touch nothing but the
challenge record.**

## Quick start

```bash
pip install certbot-dns-nicmanager      # into the same environment as Certbot
certbot certonly --authenticator dns-nicmanager \
  --dns-nicmanager-credentials ~/.secrets/certbot/nicmanager.ini \
  -d 'example.com' -d '*.example.com'
```

`certbot plugins` should list `dns-nicmanager`. There is no `snap` package: if your
Certbot came from `snap`, run Certbot from a `pip` environment with both packages.

## ✨ Features

- **Wildcard certificates** — `dns-01` is the only ACME challenge that issues them,
  and it needs no inbound port
- **Least privilege** — works with nicmanager's restricted API-ACME account; it does
  not even need to read the zone
- **Two-factor authentication** — a fresh TOTP code with every request
- **Cleanup by id** — the challenge record is deleted by the id the API returned; if
  that fails, zone and id are logged for manual removal
- **Fewer hostnames in public logs** — one wildcard instead of a certificate per
  host keeps service names out of
  [Certificate Transparency](https://certificate.transparency.dev/)
- **Small and tested** — three runtime dependencies, typed, ~95 % test coverage,
  Python 3.10 to 3.15, in production since June 2026

## Credentials

Create a dedicated **API-ACME account** in nicmanager with only these rights:

| Module | Rights |
| --- | --- |
| Nameserver | View, Manage (create, edit, delete) |
| everything else | – |

A leaked credential then cannot touch other records, transfer domains or read
account data.

`~/.secrets/certbot/nicmanager.ini`, then `chmod 600` it:

```ini
# login.username — or the email, if the account logs in with "E-Mail + Passwort"
dns_nicmanager_username = mylogin.acmeuser
# Quote the password if it contains '#': unquoted, '#' starts a comment.
dns_nicmanager_password = "0123456789abcdef0123456789abcdef"

# Optional: only if the account has 2FA. Needs an accurate clock (NTP).
# dns_nicmanager_totp_secret = JBSWY3DPEHPK3PXP

# Optional: defaults to https://api.nicmanager.com/v1
# dns_nicmanager_endpoint = https://api.nicmanager.com/v1

# Optional: skip zone detection. Applies to every domain of the certificate.
# dns_nicmanager_zone = example.com
```

| Argument | Default |
| --- | --- |
| `--dns-nicmanager-credentials` — path to the INI file | required |
| `--dns-nicmanager-propagation-seconds` — wait before the ACME server checks | `60` |

## How it works

1. Certbot hands over `_acme-challenge.<domain>` and the token.
2. The plugin finds the zone **without reading it**: it tries
   `POST /anycast/<zone>/records` from the most specific candidate up. `403`/`404`
   moves on, the first success wins, a `401` stops at once.
3. nicmanager returns the record id; TTL is the API minimum of 900 seconds.
4. After validation: `DELETE /anycast/<zone>/records/<id>`.

## Troubleshooting

| Response | Fix |
| --- | --- |
| `401 Authentication error` | Wrong username form: **email** for "E-Mail + Passwort" accounts, `login.username` otherwise |
| `401 Missing 2FA token header` | Set `dns_nicmanager_totp_secret` |
| `403 API usage not allowed` | Ask nicmanager support to enable API access |
| `401 Too many invalid attempts`, or no response | IP blocked after failed logins: **stop and wait**, never loop over credential variants; with 2FA check the clock |

Everything else:
[docs/TROUBLESHOOTING.md](https://github.com/jp1337/certbot-dns-nicmanager/blob/main/docs/TROUBLESHOOTING.md).

## Contributing

Issues and pull requests are welcome; see
[CONTRIBUTING.md](https://github.com/jp1337/certbot-dns-nicmanager/blob/main/CONTRIBUTING.md).
Security issues go through
[private vulnerability reporting](https://github.com/jp1337/certbot-dns-nicmanager/security/advisories/new).
The design and its decisions are in
[docs-tech/](https://github.com/jp1337/certbot-dns-nicmanager/tree/main/docs-tech).

```bash
pip install -e '.[test,dev]' && pytest && ruff check . && mypy certbot_dns_nicmanager
```

## License

[Apache License 2.0](https://github.com/jp1337/certbot-dns-nicmanager/blob/main/LICENSE.txt).
An independent plugin, not affiliated with or endorsed by InterNexum GmbH /
nicmanager or the EFF / Certbot project.
