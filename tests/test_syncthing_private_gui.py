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
        assert "privateGui:" in VALUES
        assert "enabled: true" in VALUES
        assert "listenPort: 18443" in VALUES
        assert "healthPort: 18444" in VALUES
        assert "enabled: false" in VALUES[VALUES.index("ingress:") :]

    def test_backend_is_localhost_and_sidecar_selects_node_config(self) -> None:
        """Require a localhost backend and a node-selected nginx sidecar."""
        assert "http://127.0.0.1:%v" in DEPLOYMENT
        assert "/etc/nginx/nodes/${NODE_NAME}.conf" in DEPLOYMENT
        assert "fieldPath: spec.nodeName" in DEPLOYMENT
        assert "mountPath: /etc/nginx/tls" in DEPLOYMENT
        assert "mountPath: /etc/nginx/auth" in DEPLOYMENT
        assert "checksum/private-nginx" in DEPLOYMENT
        assert "trap cleanup TERM INT EXIT" in DEPLOYMENT

    def test_tls_listener_and_path_scope_are_private(self) -> None:
        """Require TLS on the WireGuard address and a /sync-only proxy."""
        assert "listen {{ .wgIP }}:{{ $.Values.privateGui.listenPort }} ssl;" in NGINX
        assert "location = /sync" in NGINX
        assert "return 301 /sync/;" in NGINX
        assert "absolute_redirect off;" in NGINX
        assert "location /sync/" in NGINX
        assert "proxy_pass http://127.0.0.1:{{ $.Values.service.guiPort }}/;" in NGINX
        assert "proxy_set_header Host $proxy_host;" in NGINX
        assert "proxy_set_header X-Forwarded-Host $host;" in NGINX
        assert "location / {" in NGINX
        assert "return 404;" in NGINX
        assert "listen 443" not in NGINX

    def test_health_listener_proxies_syncthing_health_only(self) -> None:
        """Require health listeners to proxy only the Syncthing health endpoint."""
        assert "listen {{ .wgIP }}:{{ $.Values.privateGui.healthPort }};" in NGINX
        assert "listen 127.0.0.1:{{ $.Values.privateGui.healthPort }};" in NGINX
        assert "location = /healthz" in NGINX
        assert "/rest/noauth/health;" in NGINX
        assert "proxy_read_timeout 5s;" in NGINX

    def test_certificate_is_shared_and_covers_all_private_hosts(self) -> None:
        """Require one certificate covering every private Syncthing host."""
        assert "secretName: {{ .Values.privateGui.tlsSecret }}" in CERTIFICATE
        assert "clusterIssuer: letsencrypt-http01" in VALUES
        assert "range .Values.privateGui.nodes" in CERTIFICATE
        assert "kind: ClusterIssuer" in CERTIFICATE

    def test_basic_auth_middleware_is_only_public_ingress_resource(self) -> None:
        """Require basic auth in the private GUI and ingress only when enabled."""
        assert "auth_basic_user_file /etc/nginx/auth/users;" in NGINX
        assert "privateGui requires basicAuth.enabled=true" in NGINX
        assert "privateGui requires hostNetwork=true" in NGINX
        assert "privateGui requires env.STGUIADDRESS" in NGINX
        assert "{{- if .Values.ingress.enabled }}" in AUTH

    def test_gui_service_is_only_kept_for_public_mode(self) -> None:
        """Require the GUI Service only when the private GUI is disabled."""
        assert "{{- if not .Values.privateGui.enabled }}" in SERVICE

    def test_traffic_light_inset_is_opt_in_and_dashboard_scoped(self) -> None:
        """Require the traffic-light inset to stay dashboard-scoped and opt-in."""
        assert "traffic-light-inset.js" in NGINX
        assert ".trafficLightInset" in NGINX
        script = (CHART / "files/traffic-light-inset.js").read_text()
        assert "/d/socrat-traffic-light" in script
        assert "padding:5px" in script
        assert "injectJsCode" not in script


if __name__ == "__main__":
    unittest.main()
