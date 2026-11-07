"""Public status redirects must not expose the internal HTTP listener."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class KumaStatusRedirectTests(unittest.TestCase):
    def test_redirect_stays_on_public_origin(self):
        conf = (ROOT / "charts/uptime-kuma/files/kuma-policy.conf").read_text()
        self.assertIn("absolute_redirect off;", conf)
        self.assertIn("location = / { return 302 /status/socrat; }", conf)
        self.assertIn("proxy_set_header X-Forwarded-Proto https;", conf)
        self.assertNotIn("return 302 http://", conf)

    def test_access_boundaries_preserved(self):
        conf = (ROOT / "charts/uptime-kuma/files/kuma-policy.conf").read_text()
        self.assertIn("location ^~ /socket.io { return 404; }", conf)
        self.assertIn("limit_except GET HEAD { deny all; }", conf)
        self.assertIn("return 302 https://kuma.socrat.alchemmist.xyz$request_uri;", conf)
