"""The `~certbot_dns_nicmanager._internal.dns_nicmanager` plugin automates the
process of completing a ``dns-01`` challenge (`~acme.challenges.DNS01`) by
creating, and subsequently removing, TXT records using the `nicmanager
AnycastDNS API <https://api.nicmanager.com/docs/v1/>`_.

Named Arguments
---------------

==========================================  =====================================
``--dns-nicmanager-credentials``            nicmanager credentials_ INI file.
                                            (Required)
``--dns-nicmanager-propagation-seconds``    The number of seconds to wait for DNS
                                            to propagate before asking the ACME
                                            server to verify the DNS record.
                                            (Default: 60)
==========================================  =====================================


Credentials
-----------

Use of this plugin requires a nicmanager account that is permitted to manage the
``_acme-challenge`` TXT record of the relevant zone(s). The recommended setup is
a dedicated **API-ACME account**, which is restricted to exactly that operation
and nothing else:

==========================  ================================================
Module                      Rights
==========================  ================================================
Webfrontend                 –
Account settings            –
Domains                     –
Nameserver                  View, Manage (create, edit, delete)
Domainsecurity              –
Other modules               –
==========================  ================================================

Such an account can only touch the ``_acme-challenge.<zone>`` TXT record, so a
leaked credential cannot be used to hijack other DNS records, transfer domains,
or read account data. Two-factor authentication (TOTP) must be **disabled** on
the account used for automation, as the API would otherwise require a rotating
token that cannot be supplied unattended.

.. code-block:: ini
   :name: credentials.ini
   :caption: Example credentials file:

   # nicmanager API credentials used by Certbot
   dns_nicmanager_username = mylogin.acmeuser
   # Quote the password if it contains '#' (otherwise read as an INI comment).
   dns_nicmanager_password = "0123456789abcdef0123456789abcdef"

The path to this file can be provided interactively or using the
``--dns-nicmanager-credentials`` command-line argument. Certbot records the path
to this file for use during renewal, but does not store the file's contents.

.. caution::
   You should protect these API credentials as you would the password to your
   nicmanager account. Users who can read this file can use these credentials to
   create and delete the ``_acme-challenge`` records of your zones (and, if a
   privileged account is used instead of an API-ACME account, potentially much
   more). All Certbot files are stored with restrictive permissions, but you are
   encouraged to set ``chmod 600`` on the credentials file regardless.


Examples
--------

.. code-block:: bash
   :caption: To acquire a single certificate for ``example.com``

   certbot certonly \\
     --authenticator dns-nicmanager \\
     --dns-nicmanager-credentials ~/.secrets/certbot/nicmanager.ini \\
     -d example.com

.. code-block:: bash
   :caption: To acquire a wildcard certificate for ``*.example.com``

   certbot certonly \\
     --authenticator dns-nicmanager \\
     --dns-nicmanager-credentials ~/.secrets/certbot/nicmanager.ini \\
     -d '*.example.com'

.. code-block:: bash
   :caption: To acquire a certificate, waiting 120 seconds for DNS propagation

   certbot certonly \\
     --authenticator dns-nicmanager \\
     --dns-nicmanager-credentials ~/.secrets/certbot/nicmanager.ini \\
     --dns-nicmanager-propagation-seconds 120 \\
     -d example.com

"""
