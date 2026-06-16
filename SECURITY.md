# Security Policy

## Reporting a vulnerability

Please report security issues privately via GitHub's
[private vulnerability reporting](https://github.com/jp1337/certbot-dns-nicmanager/security/advisories/new)
rather than a public issue. You'll get a response as soon as possible.

## Handling of credentials

- The plugin reads nicmanager API credentials from a certbot credentials INI
  file and sends them as HTTP Basic auth over TLS to `https://api.nicmanager.com`.
  Credentials are never logged.
- Use a dedicated, least-privilege **API-ACME account** (rights limited to
  managing the `_acme-challenge.<zone>` TXT record). A leaked credential then
  cannot affect anything beyond the challenge record.
- Protect the credentials file: `chmod 600`. Disable 2FA on the automation
  account (a rotating TOTP cannot be supplied unattended).

## Scope

This plugin performs DNS-01 validation only. It does not open listeners, and it
keeps service hostnames out of public Certificate Transparency logs by using
wildcard DNS-01 rather than per-host HTTP-01.
