"""Keep the accepted 11 November transport workaround and security boundary."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_moscow_management_uses_live_mesh_not_broken_public_reconnect():
    config = json.loads((ROOT / "deploy/vpn-hardening/moscow-management.json").read_text())
    forwards = {x["port"]: x["settings"] for x in config["inbounds"]}
    assert set(forwards) == {51832, 51840}
    assert forwards[51832]["rewriteAddress"] == "10.250.0.2"
    assert forwards[51832]["rewritePort"] == 51830
    assert forwards[51832]["allowedNetwork"] == "udp"
    assert forwards[51840]["rewriteAddress"] == "10.250.0.2"
    assert forwards[51840]["rewritePort"] == 51840
    assert forwards[51840]["allowedNetwork"] == "tcp"


def test_gost_private_ingress_keeps_auth_tls_and_fixed_loopback_forwarder():
    text = (ROOT / "ansible/roles/wireguard_tcp_transport/templates/server.yaml.j2").read_text()
    assert "addr: '0.0.0.0:{{ wg_tcp_port }}'" in text
    assert "type: relay" in text and "auth:" in text
    assert "username:" in text and "password:" in text
    assert "type: tls" in text and "minVersion: VersionTLS12" in text
    assert "bind: false" in text
    assert "addr: '127.0.0.1:{{ wg_socrat_port }}'" in text
