"""Dedicated CA, distinct keys and client-only app certificates."""
import unittest
from test_argocd_gitops import load


class RedisPKITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.module = load("redis_pki")
        except ModuleNotFoundError:
            raise unittest.SkipTest("Install scripts/requirements-pki.txt")

    def test_app_cannot_present_a_server_certificate_and_leaves_have_distinct_keys(self):
        m = self.module
        ca_key, ca = m.new_ca()
        server_key, server = m.leaf(ca_key, ca, "redis.example.invalid")
        app_key, app = m.leaf(ca_key, ca)
        self.assertNotEqual(server_key.public_key().public_numbers(), app_key.public_key().public_numbers())
        self.assertIn(m.ExtendedKeyUsageOID.SERVER_AUTH, server.extensions.get_extension_for_class(m.x509.ExtendedKeyUsage).value)
        self.assertNotIn(m.ExtendedKeyUsageOID.SERVER_AUTH, app.extensions.get_extension_for_class(m.x509.ExtendedKeyUsage).value)
        self.assertFalse(app.extensions.get_extension_for_class(m.x509.BasicConstraints).value.ca)
        server.verify_directly_issued_by(ca)
        app.verify_directly_issued_by(ca)
        self.assertLessEqual((app.not_valid_after_utc - app.not_valid_before_utc).days, 90)

    def test_dns_injection_is_rejected_before_issuance(self):
        m = self.module
        key, ca = m.new_ca()
        with self.assertRaises(ValueError):
            m.leaf(key, ca, "bad\nidentity")
