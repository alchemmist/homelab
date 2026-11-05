import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('ingress', Path(__file__).resolve().parents[1] / 'scripts/check-public-ingress.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LoginRedirectTests(unittest.TestCase):
    def test_expected_lms_login(self):
        self.assertTrue(MODULE.redirect_matches('lms.alchemmist.xyz', 'Location: /auth/login\r\n'))

    def test_expected_panel_login(self):
        self.assertTrue(MODULE.redirect_matches('vpn.alchemmist.xyz', 'location: https://vpn.alchemmist.xyz/outpost.goauthentik.io/start?rd=test\r\n'))

    def test_unrelated_redirect_is_not_healthy(self):
        for value in ['https://example.com/auth/login', '//example.com/auth/login', '/error', 'http://lms.alchemmist.xyz/auth/login']:
            self.assertFalse(MODULE.redirect_matches('lms.alchemmist.xyz', 'Location: ' + value))

    def test_missing_or_duplicate_location_is_not_healthy(self):
        self.assertFalse(MODULE.redirect_matches('lms.alchemmist.xyz', ''))
        self.assertFalse(MODULE.redirect_matches('lms.alchemmist.xyz', 'Location: /auth/login\nLocation: /auth/login'))
