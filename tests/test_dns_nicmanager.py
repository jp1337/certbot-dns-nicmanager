"""Tests for certbot_dns_nicmanager._internal.dns_nicmanager."""
import sys
import unittest
from unittest import mock

import pytest
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
        # The created id is remembered for cleanup.
        self.assertEqual(self.client._created[RECORD_NAME], (DOMAIN, RECORD_ID))

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
        self.assertEqual(self.client._created["_acme-challenge.sub." + DOMAIN][0], DOMAIN)

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

    # -- del_txt_record -----------------------------------------------------

    @requests_mock.Mocker()
    def test_del_txt_record_by_remembered_id(self, m):
        self.client._created[RECORD_NAME] = (DOMAIN, RECORD_ID)
        delete = m.delete(
            f"{ENDPOINT}/anycast/{DOMAIN}/records/{RECORD_ID}", status_code=202
        )
        self.client.del_txt_record(RECORD_NAME, RECORD_CONTENT)
        self.assertTrue(delete.called)
        self.assertNotIn(RECORD_NAME, self.client._created)

    @requests_mock.Mocker()
    def test_del_txt_record_without_stored_id_makes_no_request(self, m):
        # The restricted account cannot list records, so with nothing remembered
        # cleanup must do nothing rather than fail or probe.
        self.client.del_txt_record(RECORD_NAME, RECORD_CONTENT)
        self.assertEqual(m.call_count, 0)

    @requests_mock.Mocker()
    def test_del_txt_record_delete_error_is_swallowed(self, m):
        self.client._created[RECORD_NAME] = (DOMAIN, RECORD_ID)
        m.delete(
            f"{ENDPOINT}/anycast/{DOMAIN}/records/{RECORD_ID}",
            status_code=500,
            json={"message": "boom"},
        )
        # Must not raise — cleanup errors should never mask issuance.
        self.client.del_txt_record(RECORD_NAME, RECORD_CONTENT)


if __name__ == "__main__":
    sys.exit(pytest.main(sys.argv[1:] + [__file__]))  # pragma: no cover
