"""Source contracts for the private WireGuard-only Syncthing GUI."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts/syncthing"
VALUES = (CHART / "values.yaml").read_text()
DEPLOYMENT = (CHART / "templates/deployment.yaml").read_text()
NGINX = (CHART / "templates/private-nginx.yaml").read_text()
CERTIFICATE = (CHART / "templates/certificate.yaml").read_text()
AUTH = (CHART / "templates/basic-auth.yaml").read_text()
SERVICE = (CHART / "templates/service.yaml").read_text()


class SyncthingPrivateGuiTests(unittest.TestCase):
    """Require the private GUI chart to stay off the public ingress path."""

    def test_private_gui_defaults_to_wireguard_only_mode(self) -> None:
        """Require WireGuard ports and a disabled public ingress by default."""
        self.assertIn("privateGui:", VALUES)
        self.assertIn("enabled: true", VALUES)
        self.assertIn("listenPort: 18443", VALUES)
        self.assertIn("healthPort: 18444", VALUES)
        self.assertIn("enabled: false", VALUES[VALUES.index("ingress:") :])

    def test_backend_is_localhost_and_sidecar_selects_node_config(self) -> None:
        """Require a localhost backend and a node-selected nginx sidecar."""
        self.assertIn("http://127.0.0.1:%v", DEPLOYMENT)
        self.assertIn("/etc/nginx/nodes/${NODE_NAME}.conf", DEPLOYMENT)
        self.assertIn("fieldPath: spec.nodeName", DEPLOYMENT)
        self.assertIn("mountPath: /etc/nginx/tls", DEPLOYMENT)
        self.assertIn("mountPath: /etc/nginx/auth", DEPLOYMENT)
        self.assertIn("checksum/private-nginx", DEPLOYMENT)
        self.assertIn("trap cleanup TERM INT EXIT", DEPLOYMENT)

    def test_tls_listener_and_path_scope_are_private(self) -> None:
        """Require TLS on the WireGuard address and a /sync-only proxy."""
        self.assertIn("listen {{ .wgIP }}:{{ $.Values.privateGui.listenPort }} ssl;", NGINX)
        self.assertIn("location = /sync", NGINX)
        self.assertIn("return 301 /sync/;", NGINX)
        self.assertIn("absolute_redirect off;", NGINX)
        self.assertIn("location /sync/", NGINX)
        self.assertIn("proxy_pass http://127.0.0.1:{{ $.Values.service.guiPort }}/;", NGINX)
        self.assertIn("proxy_set_header Host $proxy_host;", NGINX)
        self.assertIn("proxy_set_header X-Forwarded-Host $host;", NGINX)
        self.assertIn("location / {", NGINX)
        self.assertIn("return 404;", NGINX)
        self.assertNotIn("listen 443", NGINX)

    def test_health_listener_proxies_syncthing_health_only(self) -> None:
        """Require health listeners to proxy only the Syncthing health endpoint."""
        self.assertIn("listen {{ .wgIP }}:{{ $.Values.privateGui.healthPort }};", NGINX)
        self.assertIn("listen 127.0.0.1:{{ $.Values.privateGui.healthPort }};", NGINX)
        self.assertIn("location = /healthz", NGINX)
        self.assertIn("/rest/noauth/health;", NGINX)
        self.assertIn("proxy_read_timeout 5s;", NGINX)

    def test_certificate_is_shared_and_covers_all_private_hosts(self) -> None:
        """Require one certificate covering every private Syncthing host."""
        self.assertIn("secretName: {{ .Values.privateGui.tlsSecret }}", CERTIFICATE)
        self.assertIn("clusterIssuer: letsencrypt-http01", VALUES)
        self.assertIn("range .Values.privateGui.nodes", CERTIFICATE)
        self.assertIn("kind: ClusterIssuer", CERTIFICATE)

    def test_basic_auth_middleware_is_only_public_ingress_resource(self) -> None:
        """Require basic auth in the private GUI and ingress only when enabled."""
        self.assertIn("auth_basic_user_file /etc/nginx/auth/users;", NGINX)
        self.assertIn("privateGui requires basicAuth.enabled=true", NGINX)
        self.assertIn("privateGui requires hostNetwork=true", NGINX)
        self.assertIn("privateGui requires env.STGUIADDRESS", NGINX)
        self.assertIn("{{- if .Values.ingress.enabled }}", AUTH)

    def test_gui_service_is_only_kept_for_public_mode(self) -> None:
        """Require the GUI Service only when the private GUI is disabled."""
        self.assertIn("{{- if not .Values.privateGui.enabled }}", SERVICE)

    def test_traffic_light_inset_is_opt_in_and_dashboard_scoped(self) -> None:
        """Require the traffic-light inset to stay dashboard-scoped and opt-in."""
        self.assertIn("traffic-light-inset.js", NGINX)
        self.assertIn(".trafficLightInset", NGINX)
        script = (CHART / "files/traffic-light-inset.js").read_text()
        self.assertIn("/d/socrat-traffic-light", script)
        self.assertIn("padding:5px", script)
        self.assertNotIn("injectJsCode", script)


if __name__ == "__main__":
    unittest.main()
