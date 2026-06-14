# certbot-dns-nicmanager

[![CI](https://github.com/jp1337/certbot-dns-nicmanager/actions/workflows/ci.yml/badge.svg)](https://github.com/jp1337/certbot-dns-nicmanager/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/certbot-dns-nicmanager.svg)](https://pypi.org/project/certbot-dns-nicmanager/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE.txt)

A [Certbot](https://certbot.eff.org/) DNS authenticator plugin for
[nicmanager](https://www.nicmanager.com/) **AnycastDNS**. It automates the
`dns-01` ACME challenge by creating, and then removing, the
`_acme-challenge` TXT record through the
[nicmanager API](https://api.nicmanager.com/docs/v1/) — which makes it possible
to issue **wildcard certificates** for domains hosted on nicmanager.

There was no Certbot plugin for the nicmanager API, and the `lego`-based
multi-provider plugins do not yet support nicmanager's current API. This plugin
fills that gap with a small, dependency-light, well-tested implementation.

## Why DNS-01 (and not HTTP-01)?

`dns-01` is the only ACME challenge type that can issue **wildcard**
certificates, and it does not require any inbound HTTP reachability. It also
keeps your individual service hostnames out of the public
[Certificate Transparency](https://certificate.transparency.dev/) logs that a
per-host `http-01` certificate would expose.

## Installation

```bash
pip install certbot-dns-nicmanager
```

> Install the plugin into the **same** Python environment as Certbot. If you
> installed Certbot via `snap`, install the plugin with
> `snap install certbot-dns-nicmanager` once it is published there, or run
> Certbot from a `pip` environment that contains both packages.

Verify it is registered:

```bash
certbot plugins
# ... should list:  * dns-nicmanager
```

## Credentials

This plugin authenticates against the nicmanager API with HTTP Basic auth.
The strongly recommended setup is a dedicated **API-ACME account**, which
nicmanager restricts to managing only the `_acme-challenge.<zone>` TXT record:

| Module           | Rights                                  |
| ---------------- | --------------------------------------- |
| Webfrontend      | –                                       |
| Account settings | –                                       |
| Domains          | –                                       |
| Nameserver       | View, Manage (create, edit, delete)     |
| Domainsecurity   | –                                       |
| Other modules    | –                                       |

Because such an account can touch nothing but the challenge record, a leaked
credential cannot be used to hijack other records, transfer domains, or read
account data. **Disable two-factor authentication** on the account used for
automation — the API would otherwise require a rotating TOTP code that cannot be
provided unattended.

Create an INI file, e.g. `~/.secrets/certbot/nicmanager.ini`:

```ini
# nicmanager API credentials used by Certbot
dns_nicmanager_username = mylogin.acmeuser
# Quote the password if it contains '#' — an unquoted '#' starts an INI comment.
dns_nicmanager_password = "0123456789abcdef0123456789abcdef"

# Optional. Defaults to https://api.nicmanager.com/v1
# dns_nicmanager_endpoint = https://api.nicmanager.com/v1

# Optional. Skip zone detection and always use this zone.
# dns_nicmanager_zone = example.com
```

The `username` is `login.username` (or the account email). Zone detection works
without any read access, so `dns_nicmanager_zone` is only needed in unusual
multi-zone-suffix setups.

The `username` is either `login.username` or the account email address, as
configured in nicmanager.

Protect this file:

```bash
chmod 600 ~/.secrets/certbot/nicmanager.ini
```

## Usage

```bash
# A single hostname
certbot certonly \
  --authenticator dns-nicmanager \
  --dns-nicmanager-credentials ~/.secrets/certbot/nicmanager.ini \
  -d example.com

# A wildcard (and the apex)
certbot certonly \
  --authenticator dns-nicmanager \
  --dns-nicmanager-credentials ~/.secrets/certbot/nicmanager.ini \
  -d 'example.com' -d '*.example.com'
```

### Command-line arguments

| Argument                                | Description                                                                 | Default |
| --------------------------------------- | --------------------------------------------------------------------------- | ------- |
| `--dns-nicmanager-credentials`          | Path to the nicmanager credentials INI file. **(required)**                 | –       |
| `--dns-nicmanager-propagation-seconds`  | Seconds to wait for DNS propagation before the ACME server checks the record. | `60`    |

## How it works

1. Certbot asks the plugin to create `_acme-challenge.<domain>` with the
   validation token.
2. The plugin determines the owning AnycastDNS zone **without reading it** — a
   restricted API-ACME account cannot read zones. It tries
   `POST /v1/anycast/<candidate>/records` against each candidate zone
   (most-specific first); a `403`/`404` skips to the next candidate, the first
   `2xx` wins. An explicit `dns_nicmanager_zone` short-circuits this. A `401`
   (genuine auth failure) is surfaced immediately.
3. nicmanager returns the new record's numeric `id`, which the plugin
   remembers.
4. After validation, the plugin removes the record via
   `DELETE /v1/anycast/<zone>/records/<id>`.

TTL is fixed at the API minimum of **900 seconds**.

> **Heads-up:** the API blocks the IP after too many failed logins. Make sure
> the password is correct (and any `#` in it is quoted in the INI, see below)
> before running at scale.

## Development

```bash
git clone https://github.com/jp1337/certbot-dns-nicmanager
cd certbot-dns-nicmanager
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test,dev]'

pytest          # run the test suite
ruff check .    # lint
mypy certbot_dns_nicmanager
```

## License

[Apache License 2.0](LICENSE.txt)

This is an independent, community-maintained plugin and is not affiliated with
or endorsed by InterNexum GmbH / nicmanager or the EFF / Certbot project.
