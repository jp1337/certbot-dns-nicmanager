"""DNS Authenticator for nicmanager AnycastDNS."""
import logging
from collections.abc import Callable
from typing import Any

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
        username = self.credentials.conf("username")
        password = self.credentials.conf("password")
        # Both are guaranteed present by _validate_credentials.
        assert username is not None and password is not None
        return _NicmanagerClient(
            username,
            password,
            self.credentials.conf("endpoint") or DEFAULT_ENDPOINT,
            self.credentials.conf("zone"),
        )


class _NicmanagerClient:
    """Encapsulates all communication with the nicmanager AnycastDNS API."""

    def __init__(
        self,
        username: str,
        password: str,
        endpoint: str = DEFAULT_ENDPOINT,
        zone: str | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.configured_zone = zone.rstrip(".") if zone else None
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(username, password)
        self.session.headers.update({"Accept": "application/json"})
        # Maps a fully-qualified record name to the (zone, record_id) tuple that
        # was created for it, so cleanup can delete it again by numeric id.
        self._created: dict[str, tuple[str, int]] = {}

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
        zone = self._find_zone(record_name)
        logger.debug("Creating TXT record %s in zone %s", record_name, zone)

        data = {
            "name": record_name.rstrip("."),
            "type": "TXT",
            "value": record_content,
            "ttl": max(ttl, TXT_RECORD_TTL),
        }
        response = self._request("POST", f"/anycast/{zone}/records", json=data)
        record_id = self._extract_record_id(response)
        if record_id is not None:
            self._created[record_name] = (zone, record_id)
        logger.info("Successfully added TXT record for %s", record_name)

    def del_txt_record(self, record_name: str, record_content: str) -> None:
        """Delete a TXT record using the supplied information.

        Failures are logged but not raised, so that a cleanup error does not
        mask a successful (or differently-failed) issuance.

        :param str record_name: The record name
            (typically ``_acme-challenge.<domain>``).
        :param str record_content: The record content (the validation token).
        """
        created = self._created.pop(record_name, None)
        if created is None:
            # We never recorded an id (e.g. the API did not return one). Fall
            # back to looking the record up so we can still clean it up.
            try:
                zone = self._find_zone(record_name)
                record_id = self._find_record_id(zone, record_name, record_content)
            except errors.PluginError as e:
                logger.warning("Could not determine TXT record to delete: %s", e)
                return
            if record_id is None:
                logger.warning(
                    "TXT record for %s not found; nothing to delete.", record_name
                )
                return
        else:
            zone, record_id = created

        try:
            self._request("DELETE", f"/anycast/{zone}/records/{record_id}")
            logger.info("Successfully deleted TXT record for %s", record_name)
        except errors.PluginError as e:
            logger.warning("Encountered error deleting TXT record: %s", e)

    # -- internals ----------------------------------------------------------

    def _find_zone(self, record_name: str) -> str:
        """Resolve the AnycastDNS zone that owns ``record_name``.

        An explicit ``dns_nicmanager_zone`` always wins. Otherwise the registrable
        zone is discovered by walking the labels of ``record_name`` from the most
        specific to the least specific and probing the API for the first zone the
        configured account can actually see.
        """
        if self.configured_zone:
            return self.configured_zone

        name = record_name.rstrip(".")
        if name.startswith(ACME_CHALLENGE_PREFIX):
            name = name[len(ACME_CHALLENGE_PREFIX):]

        for candidate in dns_common.base_domain_name_guesses(name):
            if self._zone_exists(candidate):
                return candidate

        raise errors.PluginError(
            f"Unable to determine the nicmanager zone for {record_name}. The "
            f"configured account may not have access to it, or you can set "
            f"dns_nicmanager_zone in the credentials file to override zone "
            f"detection."
        )

    def _zone_exists(self, zone: str) -> bool:
        try:
            self._request("GET", f"/anycast/{zone}")
            return True
        except _NotFoundError:
            return False
        except _ForbiddenError:
            # A restricted API-ACME account may be denied zone reads while still
            # being allowed to write the challenge record. Treat the most
            # specific guess as authoritative in that case.
            logger.debug(
                "Zone read for %s forbidden; assuming this is the target zone.", zone
            )
            return True

    def _find_record_id(
        self, zone: str, record_name: str, record_content: str
    ) -> int | None:
        """Look up the numeric id of a TXT record by name and content."""
        try:
            response = self._request("GET", f"/anycast/{zone}/records")
        except errors.PluginError:
            return None
        records = response if isinstance(response, list) else response.get("records", [])
        target = record_name.rstrip(".")
        for record in records:
            if (
                record.get("type") == "TXT"
                and record.get("name", "").rstrip(".") == target
                and self._unquote(record.get("content", record.get("value", "")))
                == record_content
            ):
                return record.get("id")
        return None

    @staticmethod
    def _extract_record_id(response: Any) -> int | None:
        if isinstance(response, dict):
            record_id = response.get("id")
            if isinstance(record_id, int):
                return record_id
        return None

    @staticmethod
    def _unquote(value: str) -> str:
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            return value[1:-1]
        return value

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.endpoint}{path}"
        try:
            response = self.session.request(method, url, timeout=30, **kwargs)
        except requests.exceptions.RequestException as e:
            raise errors.PluginError(
                f"Error communicating with the nicmanager API: {e}"
            ) from e

        self._raise_for_status(response, method, path)

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _raise_for_status(response: requests.Response, method: str, path: str) -> None:
        if response.ok:
            return

        detail = _NicmanagerClient._error_detail(response)
        status = response.status_code

        if status == 401:
            raise errors.PluginError(
                f"nicmanager API authentication failed (HTTP 401). Check "
                f"dns_nicmanager_username / dns_nicmanager_password, and make sure "
                f"two-factor authentication is disabled on the account. {detail}"
            )
        if status == 403:
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
