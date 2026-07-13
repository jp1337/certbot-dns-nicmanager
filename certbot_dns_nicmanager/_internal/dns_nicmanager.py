"""DNS Authenticator for nicmanager AnycastDNS."""
import binascii
import logging
import time
from collections.abc import Callable
from typing import Any

import pyotp
import requests
from certbot import errors
from certbot.plugins import dns_common
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://api.nicmanager.com/v1"

# The ACME challenge label is never part of a zone name, so it is stripped
# before attempting to discover the owning zone.
ACME_CHALLENGE_PREFIX = "_acme-challenge."

# nicmanager rejects TTLs below 900 seconds. ACME challenge records are
# short-lived, so we keep them at the documented minimum.
TXT_RECORD_TTL = 900

ACCOUNT_URL = "https://cp.nicmanager.com/"
DOCS_URL = "https://api.nicmanager.com/docs/v1/"

# Transient HTTP statuses worth a bounded retry. 4xx (auth/zone) is NEVER
# retried — retrying 401/403 would just walk toward the API's firewall block.
RETRYABLE_STATUS = frozenset({429, 502, 503, 504})
MAX_REQUEST_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0
RETRY_BACKOFF_CAP_SECONDS = 30.0
RETRY_AFTER_CAP_SECONDS = 60.0

# When the account has 2FA enabled, nicmanager requires a rotating TOTP code in
# this header on every request; a request without it returns 401 "Missing 2FA
# token header (X-Auth-Token)".
TWO_FACTOR_HEADER = "X-Auth-Token"


def _normalize_totp_secret(secret: str) -> str:
    """Return the base32 TOTP secret without display whitespace, upper-cased.

    Authenticator apps and the nicmanager portal present the shared secret in
    space-separated, mixed-case groups (``abcd efgh …``); base32 decoding needs
    it contiguous and upper-case.
    """
    return secret.replace(" ", "").upper()


class Authenticator(dns_common.DNSAuthenticator):
    """DNS Authenticator for nicmanager AnycastDNS.

    This Authenticator uses the nicmanager AnycastDNS API to fulfil a
    ``dns-01`` challenge.
    """

    description = (
        "Obtain certificates using a DNS TXT record (if you are using nicmanager "
        "for DNS)."
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.credentials: dns_common.CredentialsConfiguration | None = None
        # Cached so the record ids captured during _perform survive until
        # _cleanup (both run on this same Authenticator instance).
        self._client: _NicmanagerClient | None = None

    @classmethod
    def add_parser_arguments(
        cls, add: Callable[..., None], default_propagation_seconds: int = 60
    ) -> None:
        super().add_parser_arguments(
            add, default_propagation_seconds=default_propagation_seconds
        )
        add("credentials", help="nicmanager credentials INI file.")

    def more_info(self) -> str:
        return (
            "This plugin configures a DNS TXT record to respond to a dns-01 "
            "challenge using the nicmanager AnycastDNS API."
        )

    def _validate_credentials(
        self, credentials: dns_common.CredentialsConfiguration
    ) -> None:
        username = credentials.conf("username")
        password = credentials.conf("password")
        if not username:
            raise errors.PluginError(
                f"{credentials.confobj.filename}: dns_nicmanager_username is required."
            )
        if not password:
            raise errors.PluginError(
                f"{credentials.confobj.filename}: dns_nicmanager_password is required."
            )
        endpoint = credentials.conf("endpoint")
        if endpoint and not endpoint.lower().startswith("https://"):
            raise errors.PluginError(
                f"{credentials.confobj.filename}: dns_nicmanager_endpoint must be an "
                f"https:// URL (got {endpoint!r}). Credentials are sent as HTTP Basic "
                f"auth and must never go over plaintext HTTP."
            )
        totp_secret = credentials.conf("totp_secret")
        if totp_secret:
            try:
                pyotp.TOTP(_normalize_totp_secret(totp_secret)).now()
            except (binascii.Error, ValueError) as e:
                raise errors.PluginError(
                    f"{credentials.confobj.filename}: dns_nicmanager_totp_secret is "
                    f"not a valid base32 TOTP secret: {e}"
                ) from e

    def _setup_credentials(self) -> None:
        self.credentials = self._configure_credentials(
            "credentials",
            "nicmanager credentials INI file",
            None,
            self._validate_credentials,
        )

    def _perform(self, domain: str, validation_name: str, validation: str) -> None:
        self._get_client().add_txt_record(validation_name, validation, TXT_RECORD_TTL)

    def _cleanup(self, domain: str, validation_name: str, validation: str) -> None:
        self._get_client().del_txt_record(validation_name, validation)

    def _get_client(self) -> "_NicmanagerClient":
        if self.credentials is None:  # pragma: no cover
            raise errors.Error("Plugin has not been prepared.")
        if self._client is None:
            username = self.credentials.conf("username")
            password = self.credentials.conf("password")
            # Both are guaranteed present by _validate_credentials.
            assert username is not None and password is not None
            self._client = _NicmanagerClient(
                username,
                password,
                self.credentials.conf("endpoint") or DEFAULT_ENDPOINT,
                self.credentials.conf("zone"),
                self.credentials.conf("totp_secret"),
            )
        return self._client


class _NicmanagerClient:
    """Encapsulates all communication with the nicmanager AnycastDNS API."""

    def __init__(
        self,
        username: str,
        password: str,
        endpoint: str = DEFAULT_ENDPOINT,
        zone: str | None = None,
        totp_secret: str | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.configured_zone = zone.rstrip(".") if zone else None
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(username, password)
        self.session.headers.update({"Accept": "application/json"})
        # When 2FA is enabled the API requires a fresh TOTP code per request
        # (see _request). None means the account has no 2FA.
        self._totp = (
            pyotp.TOTP(_normalize_totp_secret(totp_secret)) if totp_secret else None
        )
        # Maps a (record name, record value) pair to the (zone, record_id) tuple
        # that was created for it, so cleanup can delete it again by numeric id.
        # Keying on the value too is required for wildcard certs, where the base
        # and wildcard challenges share one _acme-challenge.<domain> name but use
        # different values (two distinct TXT records).
        self._created: dict[tuple[str, str], tuple[str, int]] = {}

    # -- public API ---------------------------------------------------------

    def add_txt_record(self, record_name: str, record_content: str, ttl: int) -> None:
        """Add a TXT record using the supplied information.

        :param str record_name: The record name
            (typically ``_acme-challenge.<domain>``).
        :param str record_content: The record content (the validation token).
        :param int ttl: The record TTL (number of seconds that the record may
            be cached).
        :raises certbot.errors.PluginError: if an error occurs communicating
            with the nicmanager API.
        """
        data = {
            "name": record_name.rstrip("."),
            "type": "TXT",
            "value": record_content,
            "ttl": max(ttl, TXT_RECORD_TTL),
        }

        # The restricted API-ACME account cannot read zones (zone reads return
        # 401/403), so the owning zone is discovered by attempting the create
        # against each candidate, most-specific first, and using the first that
        # succeeds. A wrong candidate yields 403/404 and we move on; a 401
        # (genuine auth failure) is never swallowed.
        candidates = self._candidate_zones(record_name)
        last_error: errors.PluginError | None = None
        for zone in candidates:
            logger.debug("Trying TXT record %s in zone %s", record_name, zone)
            try:
                response = self._request("POST", f"/anycast/{zone}/records", json=data)
            except (_ForbiddenError, _NotFoundError) as e:
                last_error = e
                continue
            record_id = self._extract_record_id(response)
            if record_id is not None:
                self._created[(record_name, record_content)] = (zone, record_id)
                logger.info("Created TXT record %s in zone %s", record_name, zone)
            else:
                logger.warning(
                    "Created TXT record %s in zone %s, but nicmanager returned no "
                    "id; automatic cleanup will not be possible.",
                    record_name,
                    zone,
                )
            return

        raise errors.PluginError(
            f"Could not create the ACME challenge record for {record_name} in any "
            f"candidate zone ({', '.join(candidates)}). The API-ACME account may "
            f"not manage this domain; set dns_nicmanager_zone in the credentials "
            f"file to override zone detection. Last error: {last_error}"
        )

    def del_txt_record(self, record_name: str, record_content: str) -> None:
        """Delete a TXT record using the supplied information.

        Failures are logged but not raised, so that a cleanup error does not
        mask a successful (or differently-failed) issuance.

        :param str record_name: The record name
            (typically ``_acme-challenge.<domain>``).
        :param str record_content: The record content (the validation token).
        """
        key = (record_name, record_content)
        created = self._created.get(key)
        if created is None:
            # No stored id (creation failed, or the API returned none). The
            # restricted API-ACME account cannot list records to find it, so
            # there is nothing safe to do here.
            logger.warning(
                "No stored record id for %s; skipping cleanup.", record_name
            )
            return

        zone, record_id = created
        try:
            self._request("DELETE", f"/anycast/{zone}/records/{record_id}")
        except _NotFoundError:
            # Already gone (double cleanup / removed elsewhere) — treat as done.
            logger.info("TXT record %s (id %s) was already gone.", record_name, record_id)
        except errors.PluginError as e:
            # Keep the id so a later attempt can still find it, and log enough
            # (zone + id) to locate the orphan for manual removal.
            logger.warning(
                "Could not delete TXT record %s in zone %s (id %s): %s — it may "
                "need manual removal.",
                record_name,
                zone,
                record_id,
                e,
            )
            return
        else:
            logger.info("Deleted TXT record %s (id %s).", record_name, record_id)
        # Remove from the map only once we know it is gone.
        self._created.pop(key, None)

    # -- internals ----------------------------------------------------------

    def _candidate_zones(self, record_name: str) -> list[str]:
        """Return the zones to attempt for ``record_name``, most-specific first.

        An explicit ``dns_nicmanager_zone`` short-circuits this. Otherwise the
        ACME label is stripped and the registrable-domain guesses are returned;
        single-label public-suffix guesses (no dot) are dropped, as they are
        never a usable zone here. No API call is made — the restricted API-ACME
        account cannot read zones, so the owning zone is found by attempting the
        create against each candidate (see :meth:`add_txt_record`).
        """
        if self.configured_zone:
            return [self.configured_zone]

        name = record_name.rstrip(".")
        if name.startswith(ACME_CHALLENGE_PREFIX):
            name = name[len(ACME_CHALLENGE_PREFIX):]

        return [g for g in dns_common.base_domain_name_guesses(name) if "." in g]

    @staticmethod
    def _extract_record_id(response: Any) -> int | None:
        if not isinstance(response, dict):
            return None
        record_id = response.get("id")
        # bool is a subclass of int — reject it explicitly.
        if isinstance(record_id, bool):
            return None
        if isinstance(record_id, int):
            return record_id
        # Some APIs serialize numeric ids as strings; accept digit-only strings.
        if isinstance(record_id, str) and record_id.isdigit():
            return int(record_id)
        return None

    def _totp_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Merge a freshly generated TOTP header into the request kwargs.

        A new code is minted for every attempt (not cached on the session), so a
        retry that crosses a 30-second window still carries a valid code. Reuse
        of the same code within a window is accepted by the API, so no
        wait-for-next-window logic is needed. Returns kwargs unchanged when the
        account has no 2FA.
        """
        if self._totp is None:
            return kwargs
        merged = dict(kwargs)
        headers = dict(merged.get("headers") or {})
        headers[TWO_FACTOR_HEADER] = self._totp.now()
        merged["headers"] = headers
        return merged

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.endpoint}{path}"
        response = None
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                response = self.session.request(
                    method, url, timeout=30, **self._totp_kwargs(kwargs)
                )
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as e:
                # Transient network error — retry a few times, then give up.
                if attempt < MAX_REQUEST_ATTEMPTS:
                    self._backoff(attempt)
                    continue
                raise errors.PluginError(
                    f"Error communicating with the nicmanager API: {e}"
                ) from e
            except requests.exceptions.RequestException as e:
                raise errors.PluginError(
                    f"Error communicating with the nicmanager API: {e}"
                ) from e

            # Retry transient server/throttle responses; never retry 4xx.
            if (
                response.status_code in RETRYABLE_STATUS
                and attempt < MAX_REQUEST_ATTEMPTS
            ):
                self._backoff(attempt, response)
                continue
            break

        assert response is not None  # the loop always assigns or raises
        self._raise_for_status(response, method, path)

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _backoff(attempt: int, response: requests.Response | None = None) -> None:
        """Sleep before a retry: honour Retry-After on 429, else exponential."""
        delay = min(
            RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)), RETRY_BACKOFF_CAP_SECONDS
        )
        if response is not None:
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                delay = min(float(retry_after), RETRY_AFTER_CAP_SECONDS)
        logger.debug(
            "Retrying nicmanager API request in %.1fs (attempt %d)", delay, attempt
        )
        time.sleep(delay)

    @staticmethod
    def _raise_for_status(response: requests.Response, method: str, path: str) -> None:
        if response.ok:
            return

        detail = _NicmanagerClient._error_detail(response)
        status = response.status_code

        if status == 401:
            raise errors.PluginError(
                f"nicmanager API authentication failed (HTTP 401). Check "
                f"dns_nicmanager_username / dns_nicmanager_password. If the account "
                f"has 2FA enabled, set dns_nicmanager_totp_secret (base32) and keep "
                f"the host clock in sync (NTP) — a skewed clock yields an invalid "
                f"TOTP, and repeated invalid codes get the account throttled. {detail}"
            )
        if status == 403:
            # A 403 means either "this account does not own this zone" (a
            # legitimate zone-walk skip) OR "API access is not enabled for the
            # account at all". The latter is account-wide, not zone-specific, so
            # it must abort immediately rather than be retried against every
            # candidate zone (which masks the cause and burns requests).
            if "usage not allowed" in detail.lower():
                raise errors.PluginError(
                    f"nicmanager API access is not enabled for this account "
                    f"(HTTP 403: {detail}). Enable API usage in the nicmanager "
                    f"portal ({ACCOUNT_URL}) or contact support; see {DOCS_URL}."
                )
            raise _ForbiddenError(
                f"nicmanager API denied the request (HTTP 403): {detail} The "
                f"account must be permitted to manage the _acme-challenge TXT "
                f"record of the zone. See {DOCS_URL} and create an API-ACME "
                f"account at {ACCOUNT_URL} if you have not already."
            )
        if status == 404:
            raise _NotFoundError(f"nicmanager API returned HTTP 404: {detail}")

        raise errors.PluginError(
            f"Unexpected response from the nicmanager API on {method} {path}: "
            f"HTTP {status}. {detail}"
        )

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            text = response.text.strip()
            return text[:200] if text else ""
        if isinstance(body, dict):
            for key in ("message", "error", "detail", "title"):
                if body.get(key):
                    return str(body[key])
        return str(body)[:200]


class _ForbiddenError(errors.PluginError):
    """The API returned HTTP 403."""


class _NotFoundError(errors.PluginError):
    """The API returned HTTP 404."""
