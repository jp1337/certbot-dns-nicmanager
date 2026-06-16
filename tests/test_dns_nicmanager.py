"""Tests for certbot_dns_nicmanager._internal.dns_nicmanager."""
import sys
import unittest
from unittest import mock

import pytest
import requests
import requests_mock
from certbot import errors
from certbot.compat import os
from certbot.plugins import dns_test_common
from certbot.plugins.dns_test_common import DOMAIN
from certbot.tests import util as test_util

USERNAME = "mylogin.acmeuser"
PASSWORD = "secret-token"
ENDPOINT = "https://api.nicmanager.com/v1"

# certbot passes the full challenge record name and token through to the plugin.
RECORD_NAME = "_acme-challenge." + DOMAIN
SUB_RECORD = "_acme-challenge.sub." + DOMAIN
RECORD_CONTENT = "token-validation-value"
RECORD_ID = 16420


class AuthenticatorTest(
    test_util.TempDirTestCase, dns_test_common.BaseAuthenticatorTest
):
    def setUp(self):
        super().setUp()

        from certbot_dns_nicmanager._internal.dns_nicmanager import Authenticator

        path = os.path.join(self.tempdir, "credentials.ini")
        dns_test_common.write(
            {
                "nicmanager_username": USERNAME,
                "nicmanager_password": PASSWORD,
            },
            path,
        )

        self.config = mock.MagicMock(
            nicmanager_credentials=path,
            nicmanager_propagation_seconds=0,  # don't wait during tests
        )

        self.auth = Authenticator(self.config, "nicmanager")

        # Certbot's display service is not configured in unit tests, so silence
        # the "waiting for propagation" notification emitted by perform().
        notify_patcher = mock.patch(
            "certbot.plugins.dns_common.display_util.notify"
        )
        notify_patcher.start()
        self.addCleanup(notify_patcher.stop)

        self.mock_client = mock.MagicMock()
        # _get_client is what the perform/cleanup hooks call; mocking it means
        # these tests exercise the plugin wiring without hitting the network.
        self.auth._get_client = mock.MagicMock(return_value=self.mock_client)  # noqa: SLF001

    def test_perform(self):
        self.auth.perform([self.achall])
        expected = [
            mock.call.add_txt_record(RECORD_NAME, mock.ANY, mock.ANY)
        ]
        self.assertEqual(expected, self.mock_client.mock_calls)

    def test_cleanup(self):
        self.auth._attempt_cleanup = True  # noqa: SLF001
        self.auth.cleanup([self.achall])
        expected = [mock.call.del_txt_record(RECORD_NAME, mock.ANY)]
        self.assertEqual(expected, self.mock_client.mock_calls)

    def test_setup_credentials_rejects_plaintext_endpoint(self):
        bad = os.path.join(self.tempdir, "bad.ini")
        dns_test_common.write(
            {
                "nicmanager_username": USERNAME,
                "nicmanager_password": PASSWORD,
                "nicmanager_endpoint": "http://api.nicmanager.com/v1",
            },
            bad,
        )
        self.config.nicmanager_credentials = bad
        with pytest.raises(errors.PluginError):
            self.auth._setup_credentials()  # noqa: SLF001

    def test_setup_credentials_rejects_missing_password(self):
        bad = os.path.join(self.tempdir, "nopw.ini")
        dns_test_common.write({"nicmanager_username": USERNAME}, bad)
        self.config.nicmanager_credentials = bad
        with pytest.raises(errors.PluginError):
            self.auth._setup_credentials()  # noqa: SLF001

    def test_setup_credentials_rejects_missing_username(self):
        bad = os.path.join(self.tempdir, "nouser.ini")
        dns_test_common.write({"nicmanager_password": PASSWORD}, bad)
        self.config.nicmanager_credentials = bad
        with pytest.raises(errors.PluginError):
            self.auth._setup_credentials()  # noqa: SLF001

    def test_setup_credentials_accepts_https_endpoint(self):
        good = os.path.join(self.tempdir, "good.ini")
        dns_test_common.write(
            {
                "nicmanager_username": USERNAME,
                "nicmanager_password": PASSWORD,
                "nicmanager_endpoint": "https://api.nicmanager.com/v1",
            },
            good,
        )
        self.config.nicmanager_credentials = good
        self.auth._setup_credentials()  # noqa: SLF001  (must not raise)


class AuthenticatorLifecycleTest(
    test_util.TempDirTestCase, dns_test_common.BaseAuthenticatorTest
):
    """Drive perform() -> cleanup() through the REAL client (HTTP mocked).

    This catches lifecycle bugs that the mocked-client tests above cannot: in
    particular, that the record created during perform() is actually deleted
    during cleanup() — which requires the created record id to survive between
    the two calls.
    """

    def setUp(self):
        super().setUp()
        from certbot_dns_nicmanager._internal.dns_nicmanager import Authenticator

        path = os.path.join(self.tempdir, "credentials.ini")
        dns_test_common.write(
            {"nicmanager_username": USERNAME, "nicmanager_password": PASSWORD}, path
        )
        self.config = mock.MagicMock(
            nicmanager_credentials=path, nicmanager_propagation_seconds=0
        )
        self.auth = Authenticator(self.config, "nicmanager")
        notify_patcher = mock.patch("certbot.plugins.dns_common.display_util.notify")
        notify_patcher.start()
        self.addCleanup(notify_patcher.stop)
        self.auth._setup_credentials()  # noqa: SLF001

    @requests_mock.Mocker()
    def test_cleanup_deletes_record_created_by_perform(self, m):
        create = m.post(
            f"{ENDPOINT}/anycast/{DOMAIN}/records",
            status_code=202,
            json={"id": RECORD_ID},
        )
        delete = m.delete(
            f"{ENDPOINT}/anycast/{DOMAIN}/records/{RECORD_ID}", status_code=202
        )

        self.auth.perform([self.achall])
        self.auth._attempt_cleanup = True  # noqa: SLF001
        self.auth.cleanup([self.achall])

        self.assertTrue(create.called, "perform() must create the TXT record")
        self.assertTrue(
            delete.called,
            "cleanup() must delete the record perform() created "
            "(the created id has to survive between perform and cleanup)",
        )


class NicmanagerClientTest(unittest.TestCase):
    def setUp(self):
        from certbot_dns_nicmanager._internal.dns_nicmanager import _NicmanagerClient

        self.client = _NicmanagerClient(USERNAME, PASSWORD, ENDPOINT)

    # -- add_txt_record -----------------------------------------------------

    @requests_mock.Mocker()
    def test_add_txt_record(self, m):
        # No zone read — the create goes straight to the candidate zone.
        create = m.post(
            f"{ENDPOINT}/anycast/{DOMAIN}/records",
            status_code=202,
            json={"id": RECORD_ID, "name": RECORD_NAME, "type": "TXT"},
        )

        self.client.add_txt_record(RECORD_NAME, RECORD_CONTENT, 900)

        self.assertTrue(create.called)
        # Only the create call was made — no GET zone probing.
        self.assertEqual(m.call_count, 1)
        body = create.last_request.json()
        self.assertEqual(body["name"], RECORD_NAME)
        self.assertEqual(body["type"], "TXT")
        self.assertEqual(body["value"], RECORD_CONTENT)
        self.assertGreaterEqual(body["ttl"], 900)
        # The created id is remembered for cleanup, keyed by (name, value).
        self.assertEqual(
            self.client._created[(RECORD_NAME, RECORD_CONTENT)], (DOMAIN, RECORD_ID)
        )

    @requests_mock.Mocker()
    def test_add_txt_record_zone_walk(self, m):
        # The most-specific candidate is not a zone (404); the registrable
        # domain is. The create is retried against the next candidate.
        miss = m.post(
            f"{ENDPOINT}/anycast/sub.{DOMAIN}/records", status_code=404, json={}
        )
        create = m.post(
            f"{ENDPOINT}/anycast/{DOMAIN}/records",
            status_code=202,
            json={"id": RECORD_ID},
        )

        self.client.add_txt_record("_acme-challenge.sub." + DOMAIN, RECORD_CONTENT, 900)
        self.assertTrue(miss.called)
        self.assertTrue(create.called)
        self.assertEqual(self.client._created[(SUB_RECORD, RECORD_CONTENT)][0], DOMAIN)

    @requests_mock.Mocker()
    def test_add_txt_record_forbidden_candidate_is_skipped(self, m):
        # A scoped account gets 403 on a zone it does not own; we try the next.
        forbidden = m.post(
            f"{ENDPOINT}/anycast/sub.{DOMAIN}/records",
            status_code=403,
            json={"message": "not your zone"},
        )
        create = m.post(
            f"{ENDPOINT}/anycast/{DOMAIN}/records",
            status_code=202,
            json={"id": RECORD_ID},
        )
        self.client.add_txt_record("_acme-challenge.sub." + DOMAIN, RECORD_CONTENT, 900)
        self.assertTrue(forbidden.called)
        self.assertTrue(create.called)

    @requests_mock.Mocker()
    def test_add_txt_record_uses_configured_zone(self, m):
        from certbot_dns_nicmanager._internal.dns_nicmanager import _NicmanagerClient

        client = _NicmanagerClient(USERNAME, PASSWORD, ENDPOINT, zone=DOMAIN)
        create = m.post(
            f"{ENDPOINT}/anycast/{DOMAIN}/records",
            status_code=202,
            json={"id": RECORD_ID},
        )
        client.add_txt_record(RECORD_NAME, RECORD_CONTENT, 900)
        # Exactly one call: straight to the configured zone, no walking.
        self.assertEqual(create.call_count, 1)
        self.assertEqual(m.call_count, 1)

    @requests_mock.Mocker()
    def test_add_txt_record_auth_error_is_not_swallowed(self, m):
        # 401 (e.g. bad creds or lockout) must propagate, not trigger a walk.
        m.post(
            f"{ENDPOINT}/anycast/{DOMAIN}/records",
            status_code=401,
            json={"message": "Authorization error"},
        )
        with pytest.raises(errors.PluginError):
            self.client.add_txt_record(RECORD_NAME, RECORD_CONTENT, 900)

    @requests_mock.Mocker()
    def test_add_txt_record_all_candidates_fail(self, m):
        # Every candidate returns 403/404 -> a clear PluginError is raised.
        m.post(f"{ENDPOINT}/anycast/{DOMAIN}/records", status_code=403, json={})
        with pytest.raises(errors.PluginError):
            self.client.add_txt_record(RECORD_NAME, RECORD_CONTENT, 900)

    # -- edge cases ---------------------------------------------------------

    @requests_mock.Mocker()
    def test_add_txt_record_clamps_ttl_to_api_minimum(self, m):
        # nicmanager rejects TTL < 900; a smaller request value is clamped up.
        create = m.post(
            f"{ENDPOINT}/anycast/{DOMAIN}/records",
            status_code=202,
            json={"id": RECORD_ID},
        )
        self.client.add_txt_record(RECORD_NAME, RECORD_CONTENT, 60)
        self.assertEqual(create.last_request.json()["ttl"], 900)

    @requests_mock.Mocker()
    def test_add_txt_record_succeeds_without_id_but_stores_nothing(self, m):
        # 202 with no id in the body: creation counts as done, but nothing is
        # stored (cleanup will then no-op), and a warning is logged.
        m.post(
            f"{ENDPOINT}/anycast/{DOMAIN}/records",
            status_code=202,
            json={"name": RECORD_NAME, "type": "TXT"},
        )
        with self.assertLogs(
            "certbot_dns_nicmanager._internal.dns_nicmanager", level="WARNING"
        ):
            self.client.add_txt_record(RECORD_NAME, RECORD_CONTENT, 900)
        self.assertEqual(self.client._created, {})

    @requests_mock.Mocker()
    def test_add_txt_record_network_error_becomes_plugin_error(self, m):
        m.post(
            f"{ENDPOINT}/anycast/{DOMAIN}/records",
            exc=requests.exceptions.ConnectionError("boom"),
        )
        with pytest.raises(errors.PluginError):
            self.client.add_txt_record(RECORD_NAME, RECORD_CONTENT, 900)

    @requests_mock.Mocker()
    def test_add_txt_record_5xx_aborts_and_does_not_walk(self, m):
        # Only 403/404 mean "wrong zone, try next". A 5xx must abort immediately
        # and NOT fall through to the parent zone.
        first = m.post(
            f"{ENDPOINT}/anycast/sub.{DOMAIN}/records",
            status_code=500,
            json={"message": "server error"},
        )
        second = m.post(
            f"{ENDPOINT}/anycast/{DOMAIN}/records",
            status_code=202,
            json={"id": RECORD_ID},
        )
        with pytest.raises(errors.PluginError):
            self.client.add_txt_record(SUB_RECORD, RECORD_CONTENT, 900)
        self.assertTrue(first.called)
        self.assertFalse(second.called)

    @requests_mock.Mocker()
    def test_add_txt_record_401_after_404_stops_the_walk(self, m):
        # A 404 continues the walk; a subsequent 401 (auth failure) must abort it.
        first = m.post(
            f"{ENDPOINT}/anycast/sub.{DOMAIN}/records", status_code=404, json={}
        )
        second = m.post(
            f"{ENDPOINT}/anycast/{DOMAIN}/records",
            status_code=401,
            json={"message": "auth"},
        )
        with pytest.raises(errors.PluginError):
            self.client.add_txt_record(SUB_RECORD, RECORD_CONTENT, 900)
        self.assertTrue(first.called)
        self.assertTrue(second.called)

    def test_candidate_zones_strips_prefix_orders_and_drops_single_label(self):
        # Most-specific first; _acme-challenge stripped; bare TLD dropped.
        self.assertEqual(
            self.client._candidate_zones("_acme-challenge.a.b." + DOMAIN),
            ["a.b." + DOMAIN, "b." + DOMAIN, DOMAIN],
        )

    def test_candidate_zones_tolerates_trailing_dot(self):
        self.assertEqual(
            self.client._candidate_zones("_acme-challenge." + DOMAIN + "."), [DOMAIN]
        )

    def test_candidate_zones_configured_zone_short_circuits(self):
        from certbot_dns_nicmanager._internal.dns_nicmanager import _NicmanagerClient

        client = _NicmanagerClient(USERNAME, PASSWORD, ENDPOINT, zone="fixed.example")
        self.assertEqual(
            client._candidate_zones("_acme-challenge.anything.else.com"),
            ["fixed.example"],
        )

    # -- del_txt_record -----------------------------------------------------

    @requests_mock.Mocker()
    def test_two_records_same_name_are_both_cleaned_up(self, m):
        # Wildcard cert: `-d domain -d *.domain` produces two challenges at the
        # SAME _acme-challenge.<domain> name but with DIFFERENT values -> two
        # separate TXT records. Both must be deleted on cleanup.
        m.post(
            f"{ENDPOINT}/anycast/{DOMAIN}/records",
            [
                {"status_code": 202, "json": {"id": 111}},
                {"status_code": 202, "json": {"id": 222}},
            ],
        )
        d1 = m.delete(f"{ENDPOINT}/anycast/{DOMAIN}/records/111", status_code=202)
        d2 = m.delete(f"{ENDPOINT}/anycast/{DOMAIN}/records/222", status_code=202)

        self.client.add_txt_record(RECORD_NAME, "value-one", 900)
        self.client.add_txt_record(RECORD_NAME, "value-two", 900)
        self.client.del_txt_record(RECORD_NAME, "value-one")
        self.client.del_txt_record(RECORD_NAME, "value-two")

        self.assertTrue(d1.called, "first record (value-one) must be deleted")
        self.assertTrue(d2.called, "second record (value-two) must be deleted")

    @requests_mock.Mocker()
    def test_del_txt_record_by_remembered_id(self, m):
        self.client._created[(RECORD_NAME, RECORD_CONTENT)] = (DOMAIN, RECORD_ID)
        delete = m.delete(
            f"{ENDPOINT}/anycast/{DOMAIN}/records/{RECORD_ID}", status_code=202
        )
        self.client.del_txt_record(RECORD_NAME, RECORD_CONTENT)
        self.assertTrue(delete.called)
        self.assertNotIn((RECORD_NAME, RECORD_CONTENT), self.client._created)

    @requests_mock.Mocker()
    def test_del_txt_record_without_stored_id_makes_no_request(self, m):
        # The restricted account cannot list records, so with nothing remembered
        # cleanup must do nothing rather than fail or probe.
        self.client.del_txt_record(RECORD_NAME, RECORD_CONTENT)
        self.assertEqual(m.call_count, 0)

    @requests_mock.Mocker()
    def test_del_txt_record_delete_error_is_swallowed(self, m):
        self.client._created[(RECORD_NAME, RECORD_CONTENT)] = (DOMAIN, RECORD_ID)
        m.delete(
            f"{ENDPOINT}/anycast/{DOMAIN}/records/{RECORD_ID}",
            status_code=500,
            json={"message": "boom"},
        )
        # Must not raise — cleanup errors should never mask issuance.
        self.client.del_txt_record(RECORD_NAME, RECORD_CONTENT)


if __name__ == "__main__":
    sys.exit(pytest.main(sys.argv[1:] + [__file__]))  # pragma: no cover
