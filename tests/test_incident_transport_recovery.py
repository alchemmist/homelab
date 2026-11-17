"""Keep the accepted 11 November transport workaround and security boundary."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Accepted 11 November Moscow management ports: UDP ingress rewrites onto the live
# mesh port; the TCP ingress keeps its own port. Values are the contract, not labels.
MANAGEMENT_UDP_INBOUND_PORT = 51832
LIVE_MESH_UDP_PORT = 51830
MANAGEMENT_TCP_PORT = 51840


def test_moscow_management_uses_live_mesh_not_broken_public_reconnect() -> None:
    """Require Moscow management forwards to use the live mesh, not public reconnect."""
    config = json.loads((ROOT / "deploy/vpn-hardening/moscow-management.json").read_text())
    forwards = {x["port"]: x["settings"] for x in config["inbounds"]}
    assert set(forwards) == {MANAGEMENT_UDP_INBOUND_PORT, MANAGEMENT_TCP_PORT}
    assert forwards[MANAGEMENT_UDP_INBOUND_PORT]["rewriteAddress"] == "10.250.0.2"
    assert forwards[MANAGEMENT_UDP_INBOUND_PORT]["rewritePort"] == LIVE_MESH_UDP_PORT
    assert forwards[MANAGEMENT_UDP_INBOUND_PORT]["allowedNetwork"] == "udp"
    assert forwards[MANAGEMENT_TCP_PORT]["rewriteAddress"] == "10.250.0.2"
    assert forwards[MANAGEMENT_TCP_PORT]["rewritePort"] == MANAGEMENT_TCP_PORT
    assert forwards[MANAGEMENT_TCP_PORT]["allowedNetwork"] == "tcp"


def test_gost_private_ingress_keeps_auth_tls_and_fixed_loopback_forwarder() -> None:
    """Require private GOST ingress to keep auth, TLS 1.2, and the loopback forwarder."""
    text = (ROOT / "ansible/roles/wireguard_tcp_transport/templates/server.yaml.j2").read_text()
    assert "addr: '0.0.0.0:{{ wg_tcp_port }}'" in text
    assert "type: relay" in text
    assert "auth:" in text
    assert "username:" in text
    assert "password:" in text
    assert "type: tls" in text
    assert "minVersion: VersionTLS12" in text
    assert "bind: false" in text
    assert "addr: '127.0.0.1:{{ wg_socrat_port }}'" in text
