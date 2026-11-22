"""Mac SSH must use narrow mesh routes, without SSH bastions or source masking."""

import shlex
import subprocess
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


def load(path) -> dict[str, object]:
    """Load a YAML inventory or role defaults mapping from the repository."""
    values: dict[str, object] = yaml.safe_load((ROOT / path).read_text())
    return values


def _mapping(value: object) -> dict[str, object]:
    """Return the assert-verified mapping view of a parsed YAML value."""
    assert isinstance(value, dict)
    result: dict[str, object] = value
    return result


def _documents(value: object) -> list[dict[str, object]]:
    """Return the assert-verified list-of-documents view of a parsed YAML value."""
    assert isinstance(value, list)
    documents: list[dict[str, object]] = value
    return documents


def _sequence(value: object) -> list[object]:
    """Return the assert-verified list view of a parsed YAML value."""
    assert isinstance(value, list)
    sequence: list[object] = value
    return sequence


def _text(value: object) -> str:
    """Return the assert-verified string view of a parsed YAML value."""
    assert isinstance(value, str)
    return value


def _mapping_path(document: dict[str, object], *keys: str) -> dict[str, object]:
    """Walk nested mappings of a parsed document and return the final mapping."""
    value: object = document
    for key in keys:
        value = _mapping(value)[key]
    return _mapping(value)


def test_four_nodes_have_unique_exact_client_host_routes() -> None:
    defaults = load("ansible/roles/wireguard_admin_client/defaults/main.yml")
    peers = _documents(defaults["wireguard_admin_peers"])
    routes = [
        route
        for p in peers
        for route in _sequence(p.get("allowed_ips", [_text(p["address"]) + "/32"]))
    ]
    assert len(peers) == 3
    assert len(routes) == len(set(routes)) == 4
    assert set(routes) == {
        "10.250.0.1/32",
        "10.250.0.2/32",
        "10.250.0.3/32",
        "10.250.0.5/32",
    }
    assert "10.250.0.5/32" in _sequence(peers[0]["allowed_ips"])
    assert peers[0]["name"] == "socrat-0"
    assert "default" not in routes and "0.0.0.0/0" not in routes


def test_worker_routes_mac_back_to_same_gateway_without_duplicate_peer() -> None:
    worker = load("ansible/inventory/host_vars/socrat-3.yml")
    extra = _mapping_path(worker, "wg_socrat_extra_allowed_peer_ips", "socrat-3")
    assert "10.250.0.4/32" in _sequence(extra["socrat-0"])
    assert worker["wg_socrat_admin_clients"] == {}


def render_firewall(rules) -> str:
    """Render the administered-mesh firewall profile from the chart defaults."""
    env = Environment()
    env.filters["quote"] = shlex.quote
    env.filters["bool"] = bool
    env.filters["dict2items"] = lambda d: [{"key": k, "value": v} for k, v in d.items()]
    defaults = load("ansible/roles/wireguard_admin_firewall/defaults/main.yml")
    defaults.update(
        wg_socrat_admin_clients={"mac": {"address": "10.250.0.4"}},
        wg_socrat_nodes={
            "socrat-0": {"address": "10.250.0.1"},
            "socrat-3": {"address": "10.250.0.5"},
        },
        inventory_hostname="socrat-0",
        wg_socrat_admin_forward_rules=rules,
    )
    template = (
        ROOT / "ansible/roles/wireguard_admin_firewall/templates/wg-socrat-admin-firewall.sh.j2"
    ).read_text()
    rendered = env.from_string(template).render(**defaults)
    subprocess.run(["sh", "-n"], input=rendered, text=True, check=True, capture_output=True)
    return rendered


def test_mac_only_forwards_worker_ssh_without_snat() -> None:
    host = load("ansible/inventory/host_vars/socrat-0.yml")
    rules = _documents(host["wg_socrat_admin_forward_rules"])
    rule = next(r for r in rules if r["client"] == "antonmoss-mac")
    assert rule == {
        "client": "antonmoss-mac",
        "destination": "socrat-3",
        "tcp_ports": [2222],
        "snat": False,
    }
    script = render_firewall([dict(rule, client="mac")])
    assert "-s 10.250.0.4/32 -d 10.250.0.5/32 -p tcp --dport 2222" in script
    assert "SNAT --to-source" not in script
    assert '-s "$client_address/32" -j REJECT' in script


def test_other_forwarding_rules_keep_legacy_snat_default() -> None:
    script = render_firewall([{"client": "mac", "destination": "socrat-3", "tcp_ports": [2222]}])
    assert "SNAT --to-source 10.250.0.1" in script


def test_rendered_profile_is_split_and_carries_worker_route() -> None:
    env = Environment()
    defaults = load("ansible/roles/wireguard_admin_client/defaults/main.yml")
    defaults.update(wireguard_admin_private_key="offline-private-placeholder")
    peers = _documents(defaults["wireguard_admin_peers"])
    defaults["wireguard_admin_peers"] = [
        dict(p, public_key="offline-public-placeholder") for p in peers
    ]
    template = (
        ROOT / "ansible/roles/wireguard_admin_client/templates/wg-socrat-admin.conf.j2"
    ).read_text()
    profile = env.from_string(template).render(**defaults)
    assert "AllowedIPs = 10.250.0.1/32, 10.250.0.5/32" in profile
    assert "Endpoint = 109.120.141.60:51830" in profile
    assert "0.0.0.0/0" not in profile
    assert "DNS =" not in profile
