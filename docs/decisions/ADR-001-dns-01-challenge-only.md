# ADR-001: Support only the DNS-01 ACME challenge

**Date:** 2026-06-14
**Status:** Accepted

## Context

Certbot supports multiple ACME challenge types. The two most common are:

- **HTTP-01**: the ACME server fetches a token from
  `http://<domain>/.well-known/acme-challenge/<token>`. Works for any
  publicly-reachable web server but cannot issue wildcard certificates and
  requires inbound HTTP access.

- **DNS-01**: the ACME server looks up a TXT record at
  `_acme-challenge.<domain>`. The only challenge type that can issue **wildcard**
  certificates (`*.example.com`), and works without any inbound network
  reachability.

The primary reason to write a nicmanager-specific Certbot plugin is to automate
certificate issuance for infrastructure that uses nicmanager AnycastDNS. That
infrastructure commonly includes:

1. Servers behind firewalls or NAT where an inbound HTTP request on port 80
   cannot reliably reach the service being certified.
2. Wildcard certificates that cover entire domains (e.g. `*.wdkro.de`), which
   HTTP-01 cannot issue under any circumstances.
3. A preference for not listing every individual service hostname in the public
   Certificate Transparency logs. HTTP-01 requires a separate certificate per
   hostname; each issued certificate is logged publicly and permanently, leaking
   the server's full hostname inventory.

Implementing HTTP-01 would require either a standalone HTTP listener (which
conflicts with existing web servers) or integration with a running web server
(which creates a dependency on the server's configuration). Neither adds value
for the target use case.

## Decision

The plugin implements **only the `dns-01` challenge**. No HTTP-01 support is
planned or desired.

Practically, this is enforced implicitly: `Authenticator` extends
`certbot.plugins.dns_common.DNSAuthenticator`, which sets the challenge type to
DNS-01 in the base class. No extra code is needed to exclude other challenge
types.

## Consequences

- Wildcard certificates and non-HTTP-reachable hosts are first-class supported
  use cases.
- Individual service hostnames do not appear in Certificate Transparency logs
  when a wildcard certificate is used instead of per-host certificates.
- The account used for automation requires DNS API access, not HTTP access.
  Operators who have not yet obtained API access from nicmanager must fall back
  to manual `--manual --preferred-challenges dns` issuance in the interim (see
  [`docs/TROUBLESHOOTING.md`](../TROUBLESHOOTING.md#manual-fallback-while-the-api-is-unavailable)).
- Hosts where DNS is not managed through nicmanager cannot use this plugin, even
  if they could serve HTTP-01 challenges.
