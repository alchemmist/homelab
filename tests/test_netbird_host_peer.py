"""Tests for the NetBird host peer provisioning scripts."""

import importlib.util
import struct
import types
import unittest
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name) -> types.ModuleType:
    """Load an offline netbird runtime module from the scripts directory."""
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), ROOT / "scripts" / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


peer = load("netbird-host-peer")
stun = load("netbird-stun")
probe = load("netbird-stun-check")


class HostPeerTest(unittest.TestCase):
    """Check NetBird host peer group rendering and peers."""

    def groups(self) -> list[dict[str, object]]:
        """Build the reviewed claimable groups for the preflight tests."""
        result: list[dict[str, object]] = [
            {"id": str(i), "name": n, "issued": "jwt", "peers": [], "resources": []}
            for i, n in enumerate(peer.SOURCES)
        ]
        return result

    def test_live_gate_no_default_and_real_jwt_only(self) -> None:
        """The live gate requires JWT groups, known peers and memory headroom."""
        assert peer.preflight([], self.groups(), [], 600 * 1024) == ["0", "1"]
        for policies, groups, peers, mem in [
            ([{"name": "Default"}], self.groups(), [], 600 * 1024),
            ([], [], [], 600 * 1024),
            ([], [dict(g, issued="api") for g in self.groups()], [], 600 * 1024),
            ([], self.groups(), [{"id": "unplanned"}], 600 * 1024),
            ([], self.groups(), [], 400 * 1024),
            ([], [dict(g, peers=["unplanned"]) for g in self.groups()], [], 600 * 1024),
        ]:
            with pytest.raises(ValueError):
                peer.preflight(policies, groups, peers, mem)

    def test_machine_not_router_no_credentials_or_host_root(self) -> None:
        """The machine peer is not a router and holds no credentials or host root."""
        for host in peer.HOSTS:
            docs = peer.peer(host)
            deployment = docs[1]
            assert deployment["spec"]["replicas"] == 0
            spec = deployment["spec"]["template"]["spec"]
            container = spec["containers"][0]
            assert spec["hostNetwork"]
            assert not spec["automountServiceAccountToken"]
            assert "hostPID" not in spec
            assert "privileged" not in container["securityContext"]
            assert container["securityContext"]["capabilities"]["add"] == [
                "NET_ADMIN",
                "NET_RAW",
                "BPF",
            ]
            assert [v["hostPath"]["path"] for v in spec["volumes"] if "hostPath" in v] == [
                "/dev/net/tun"
            ]
            env = {e["name"]: e for e in container["env"]}
            for name in [
                "NB_DISABLE_CLIENT_ROUTES",
                "NB_DISABLE_SERVER_ROUTES",
                "NB_DISABLE_DNS",
            ]:
                assert env[name]["value"] == "true"
            assert env["NB_DISABLE_FIREWALL"]["value"] == "false"
            assert "value" not in env["NB_SETUP_KEY"]
            assert "@sha256:" in container["image"]
            assert container["resources"]["limits"]["memory"] == "96Mi"
            blob = yaml.safe_dump(docs)
            for forbidden in [
                "wg-socrat",
                "/etc/wireguard",
                "/etc/ssh",
                "docker.sock",
                "10.250.0.2/32",
                "iptables -F",
            ]:
                assert forbidden not in blob

    def test_single_use_native_key_body(self) -> None:
        """Setup keys are one-off, groupless and short-lived."""
        for host in peer.HOSTS:
            key = peer.setup_key_body(host)
            assert key["type"] == "one-off"
            assert key["auto_groups"] == []
            assert key["usage_limit"] == 1
            assert key["expires_in"] <= 600
        with pytest.raises(ValueError):
            peer.setup_key_body("new-vm")

    def test_only_directed_tcp_ports_dedicated_groups(self) -> None:
        """Policies use dedicated groups with directed TCP ports."""
        bodies = peer.policies(["jwt-grafana", "jwt-ssh"], ["machine-grafana", "machine-ssh"])
        for body, port in zip(bodies, ["8443", "2222"], strict=True):
            rule = body["rules"][0]
            assert rule["protocol"] == "tcp"
            assert rule["ports"] == [port]
            assert not rule["bidirectional"]
            assert "All" not in str(rule)
        with pytest.raises(ValueError):
            peer.policies(["same", "same"], ["d1", "d2"])

    def test_overlay_only_tls_host_sni_verified_upstream(self) -> None:
        """The frontend is overlay-only TLS with SNI-verified upstream."""
        cfg = peer.frontend_config("100.96.1.2")
        static = yaml.safe_load(cfg["static.yaml"])
        dynamic = yaml.safe_load(cfg["dynamic.yaml"])
        assert static["entryPoints"]["grafana"]["address"] == "100.96.1.2:8443"
        assert "api" not in static
        assert dynamic["tls"]["options"]["strict"]["sniStrict"]
        http = dynamic["http"]
        assert http["routers"]["grafana"]["rule"] == "Host(`grafana.socrat.alchemmist.xyz`)"
        assert (
            http["middlewares"]["fixed-upstream-host"]["headers"]["customRequestHeaders"]["Host"]
            == peer.GRAFANA
        )
        assert not http["serversTransports"]["verified"]["insecureSkipVerify"]
        assert http["serversTransports"]["verified"]["serverName"] == peer.GRAFANA
        assert http["services"]["grafana"]["loadBalancer"]["servers"] == [
            {"url": "https://10.250.0.3:443"}
        ]
        for address in ["0.0.0.0", "109.120.141.60", "10.250.0.2", "100.96.1.2;evil"]:
            with pytest.raises(ValueError):
                peer.frontend_config(address)
        deployment = peer.frontend("socrat-0", "100.96.1.2")[1]
        assert deployment["spec"]["replicas"] == 0
        guard = peer.frontend_guard()
        assert 'iifname != "nb-host" tcp dport 8443 counter drop' in guard
        for forbidden in ["2222", "51830", "flush", "forward", "masquerade"]:
            assert forbidden not in guard


class StunTest(unittest.TestCase):
    """Validate the bounded STUN-only manifest without service SNAT."""

    def test_bounded_stun_only_no_service_snat(self) -> None:
        """STUN is bounded, dedicated and without service SNAT."""
        docs = stun.manifests()
        assert len(docs) == 1
        spec = docs[0]["spec"]["template"]["spec"]
        c = spec["containers"][0]
        assert spec["hostNetwork"]
        assert spec["nodeSelector"]["kubernetes.io/hostname"] == "socrat-2"
        assert c["resources"]["limits"] == {"memory": "32Mi", "cpu": "100m"}
        for flag in [
            "--stun-only",
            "--no-tcp",
            "--no-tls",
            "--no-dtls",
            "--no-cli",
            "--listening-ip=109.120.141.60",
        ]:
            assert flag in c["args"]
        assert "hostPath" not in yaml.safe_dump(spec)
        assert "privileged" not in yaml.safe_dump(spec)
        assert c["securityContext"]["capabilities"]["add"] == ["NET_BIND_SERVICE"]
        assert "@sha256:" in c["image"]

    def binding(self) -> tuple[bytes, bytes]:
        """Build a STUN request and its expected binding response."""
        packet: bytes = probe.request(1)
        port = 12345 ^ 0x2112
        addr = bytes(
            a ^ b
            for a, b in zip(
                bytes([109, 173, 40, 247]), struct.pack("!I", probe.COOKIE), strict=True
            )
        )
        val = b"\x00\x01" + struct.pack("!H", port) + addr
        response = b"\x01\x01\x00\x0c" + packet[4:20] + b"\x00\x20\x00\x08" + val
        return packet, response

    def test_binding_exact_transaction_and_source(self) -> None:
        """Bindings parse only the exact transaction and source."""
        packet, response = self.binding()
        assert probe.parse_binding(packet, response) == {
            "address": "109.173.40.247",
            "port": 12345,
        }
        for bad in [
            response[:-1],
            response[:8] + b"x" * 12 + response[20:],
            b"\x01\x03" + response[2:],
            response + b"bad",
        ]:
            with pytest.raises(ValueError):
                probe.parse_binding(packet, bad)


if __name__ == "__main__":
    unittest.main()
