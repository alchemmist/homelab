#!/usr/bin/env python3
"""Offline staged four-node NetBird data-plane redundancy, not control-plane HA.

Every routing peer must have native admin INPUT ACL for its own WG address and
resource FORWARD ACL for remote WG addresses. No WG configuration/AllowedIPs edits.
"""

import importlib.util
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HOSTS = ("socrat-0", "socrat-1", "socrat-2", "socrat-3")
NODE_ADDRESSES = {
    "socrat-0": "10.250.0.1/32",
    "socrat-1": "10.250.0.3/32",
    "socrat-2": "10.250.0.2/32",
    "socrat-3": "10.250.0.5/32",
}
DESTINATION_GROUP = "netbird-node-agents"
ADMIN_SOURCE = "netbird-internal-admins"


def peer(host: str) -> list[dict[str, object]]:
    if host not in HOSTS:
        raise ValueError("existing reviewed node required")
    spec = importlib.util.spec_from_file_location(
        "node_peer", ROOT / "scripts/netbird-host-peer.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    docs: list[dict[str, object]] = module.peer(host, admin_mesh=True)
    containers = as_list(
        as_record(as_record(as_record(docs[1]["spec"])["template"])["spec"])["containers"]
    )
    for entry in [as_record(x) for x in as_list(as_record(containers[0])["env"])]:
        if entry.get("name") == "NB_DISABLE_SERVER_ROUTES":
            entry["value"] = "false"
    return docs


def as_record(value: object) -> dict[str, object]:
    """Return a mapping-shaped JSON value, failing loudly on malformed structure."""
    if not isinstance(value, dict):
        error = "structured JSON record required"
        raise TypeError(error)
    return value


def as_list(value: object) -> list[object]:
    """Return a list-shaped JSON value, failing loudly on malformed structure."""
    if not isinstance(value, list):
        error = "structured JSON array required"
        raise TypeError(error)
    return value


def reviewed_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9_-]+", value) is not None
        and value.lower() not in ("all", "default")
    )


def router_body(node_group: str) -> dict[str, object]:
    if not reviewed_id(node_group):
        raise ValueError("dedicated API group containing exact node agents required")
    return {"peer_groups": [node_group], "enabled": True, "masquerade": True, "metric": 80}


def admin_input_policy(jwt_group: str, node_group: str) -> dict[str, object]:
    if not reviewed_id(jwt_group) or not reviewed_id(node_group) or jwt_group == node_group:
        raise ValueError("separate genuine admin JWT and exact node destinations required")
    return {
        "name": "admin-nodes-local-input",
        "enabled": True,
        "description": "Own-node INPUT is distinct from remote resource FORWARD",
        "rules": [
            {
                "name": "admin-node-local-input",
                "enabled": True,
                "action": "accept",
                "protocol": "all",
                "bidirectional": False,
                "sources": [jwt_group],
                "destinations": [node_group],
            }
        ],
    }


def pilot_input_policy(jwt_group: str, node2_destination: str) -> dict[str, object]:
    if (
        not reviewed_id(jwt_group)
        or not reviewed_id(node2_destination)
        or jwt_group == node2_destination
    ):
        raise ValueError("separate genuine pilot JWT and exact node2 destination required")
    return {
        "name": "pilot-local-ssh-socrat-2",
        "enabled": True,
        "description": "Preserve pilot SSH when selected routing peer is destination host itself",
        "rules": [
            {
                "name": "pilot-native-ssh-input",
                "enabled": True,
                "action": "accept",
                "protocol": "tcp",
                "bidirectional": False,
                "sources": [jwt_group],
                "destinations": [node2_destination],
                "ports": ["2222"],
            }
        ],
    }


def manifests() -> list[dict[str, object]]:
    return [doc for host in HOSTS for doc in peer(host)]


if __name__ == "__main__":
    import sys

    yaml.safe_dump_all(manifests(), sys.stdout, sort_keys=False)
