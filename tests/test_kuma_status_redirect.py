"""Public status redirects must not expose the internal HTTP listener."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class KumaStatusRedirectTests(unittest.TestCase):
    """Nginx policy checks for the public Uptime Kuma status redirect."""

    def test_redirect_stays_on_public_origin(self) -> None:
        """Require the status redirect to stay on the public origin."""
        conf = (ROOT / "charts/uptime-kuma/files/kuma-policy.conf").read_text()
        assert "absolute_redirect off;" in conf
        assert "location = / { return 302 /status/socrat; }" in conf
        assert "proxy_set_header X-Forwarded-Proto https;" in conf
        assert "return 302 http://" not in conf

    def test_access_boundaries_preserved(self) -> None:
        """Require socket, method, and public HTTPS boundaries to stay."""
        conf = (ROOT / "charts/uptime-kuma/files/kuma-policy.conf").read_text()
        assert "location ^~ /socket.io { return 404; }" in conf
        assert "limit_except GET HEAD { deny all; }" in conf
        assert "return 302 https://kuma.socrat.alchemmist.xyz$request_uri;" in conf
