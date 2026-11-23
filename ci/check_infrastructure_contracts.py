#!/usr/bin/env python3
"""Offline contracts. Default checks; --write changes ONLY registered IP scalars.

Never contacts Kubernetes, runs workflows, reads credentials, or executes tools.
"""

import argparse
import ast
import configparser
import contextlib
import ipaddress
import json
from pathlib import Path
from typing import TypedDict

import yaml

ROOT = Path(__file__).resolve().parents[1]


class _MeshNode(TypedDict):
    address: str
    endpoint: str
    public_key: str


class _RelayContract(TypedDict):
    frontNode: str
    clientNode: str
    targetNode: str
    frontPort: int
    clientPort: int
    backendPort: int
    relayScript: str
    endpointScript: str
    frontHostVars: str
    targetHostVars: str
    serviceFile: str
    installPlaybook: str
    directRecoveryEndpoint: str


class _IssuerConsumer(TypedDict):
    file: str
    path: list[str]


class _IssuerRoute(TypedDict):
    hostname: str
    ip: str
    consumers: list[_IssuerConsumer]


def load(path):
    return yaml.safe_load(path.read_text())


def scalar_node(node, key):
    for k, value in node.value:
        if k.value == key:
            return value
    raise ValueError("Missing registered YAML field: " + key)


def _validate_mesh(
    mesh_path: Path, inventory_path: Path, ssh_from_public: list[str]
) -> dict[str, _MeshNode]:
    """Cross-check mesh registry membership, addresses and SSH endpoints."""
    mesh: dict[str, _MeshNode] = load(mesh_path)["wg_socrat_nodes"]
    hosts: dict[str, dict[str, object]] = load(inventory_path)["all"]["children"]["Socrat"]["hosts"]
    if set(mesh) != set(hosts):
        msg = "Inventory/mesh node membership drift"
        raise ValueError(msg)
    addresses = [str(ipaddress.ip_address(n["address"])) for n in mesh.values()]
    if len(set(addresses)) != len(addresses):
        msg = "Duplicate node mesh addresses"
        raise ValueError(msg)
    for name, node in mesh.items():
        expected = (
            node["endpoint"].rsplit(":", 1)[0] if name in ssh_from_public else node["address"]
        )
        if hosts[name]["ansible_host"] != expected:
            raise ValueError("Inventory endpoint drift: " + name)
    return mesh


def _assert_literals(path: Path) -> dict[str, object]:
    """Collect top-level constant assignments from a Python script."""
    result = {}
    for statement in ast.parse(path.read_text()).body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            with contextlib.suppress(ValueError, TypeError):
                result[statement.targets[0].id] = ast.literal_eval(statement.value)
    return result


def _relay_topology(
    root: Path, relay: _RelayContract, mesh: dict[str, _MeshNode]
) -> dict[str, tuple[str, int]]:
    """Derive the fixed relay five-hop topology from the mesh registry."""
    r = _assert_literals(root / relay["relayScript"])
    lan = load(root / relay["frontHostVars"])["homelab_ssh_private_host"]
    target_lan = load(root / relay["targetHostVars"])["homelab_ssh_private_host"]
    target_ip, target_port = mesh[relay["targetNode"]]["endpoint"].rsplit(":", 1)
    expected = {
        "FRONT": (mesh[relay["frontNode"]]["address"], relay["frontPort"]),
        "CLIENT": (mesh[relay["clientNode"]]["address"], relay["clientPort"]),
        "BACK": (lan, relay["backendPort"]),
        "TARGET": (target_ip, int(target_port)),
    }
    if target_lan != target_ip or any(r.get(k) != v for k, v in expected.items()):
        msg = "Fixed relay topology drift; requires reviewed network change"
        raise ValueError(msg)
    return expected


def _relay_updater(
    root: Path,
    relay: _RelayContract,
    mesh: dict[str, _MeshNode],
    expected: dict[str, tuple[str, int]],
) -> None:
    """Require the endpoint updater to embed only the registered identities."""
    e = _assert_literals(root / relay["endpointScript"])
    if (
        e.get("RELAY") != expected["FRONT"][0] + ":" + str(relay["frontPort"])
        or e.get("PEER") != mesh[relay["targetNode"]]["public_key"]
        or e.get("DIRECT") != relay["directRecoveryEndpoint"]
    ):
        msg = "Relay updater endpoint/peer identity drift"
        raise ValueError(msg)


def _relay_sandbox(root: Path, relay: _RelayContract, expected: dict[str, tuple[str, int]]) -> None:
    """Require the relay systemd unit to allow only registered endpoints."""
    unit = configparser.ConfigParser(interpolation=None)
    unit.read_string((root / relay["serviceFile"]).read_text())
    service = unit["Service"]
    allow = service["IPAddressAllow"].split()
    required = {expected["CLIENT"][0] + "/32", expected["TARGET"][0] + "/32"}
    if len(allow) != len(required) or set(allow) != required or service["IPAddressDeny"] != "any":
        msg = "Relay sandbox endpoint scope drift; no automatic network regeneration"
        raise ValueError(msg)
    for key, value in {
        "DynamicUser": "yes",
        "NoNewPrivileges": "yes",
        "CapabilityBoundingSet": "",
        "AmbientCapabilities": "",
    }.items():
        if service.get(key) != value:
            raise ValueError("Relay sandbox privilege drift: " + key)


def _relay_hardening(root: Path, relay: _RelayContract) -> None:
    """Require the relay playbook to preflight against the mesh registry."""
    playbook = load(root / relay["installPlaybook"])
    assertion = next(
        t["ansible.builtin.assert"]["that"]
        for t in playbook[0]["tasks"]
        if t.get("name") == "Validate relay mesh identity without reading WG keys"
    )
    if not any(
        "wg_socrat_nodes['" + relay["frontNode"] + "']['address']" in line for line in assertion
    ):
        msg = "Relay preflight must derive the address from the mesh registry"
        raise ValueError(msg)


def _check_consumer(
    root: Path, route: _IssuerRoute, consumer: _IssuerConsumer, *, write: bool
) -> tuple[Path, str, tuple[int, int, str]] | None:
    """Validate one registered consumer; return the scalar edit to be rendered."""
    target = root / consumer["file"]
    if not target.resolve().is_relative_to(root.resolve()):
        msg = "Consumer escapes repository"
        raise ValueError(msg)
    text = target.read_text()
    value, tree = yaml.safe_load(text), yaml.compose(text)
    for key in consumer["path"]:
        value, tree = value[key], scalar_node(tree, key)
    matches = [
        (entry, node)
        for entry, node in zip(value, tree.value, strict=False)
        if route["hostname"] in entry.get("hostnames", [])
    ]
    if len(matches) != 1:
        raise ValueError("Missing/duplicate issuer alias: " + consumer["file"])
    entry, node = matches[0]
    # The shared route must not accidentally redirect other hostnames.
    if entry["hostnames"] != [route["hostname"]]:
        raise ValueError("Issuer alias scope widened: " + consumer["file"])
    ipaddress.ip_address(entry["ip"])
    if entry["ip"] != route["ip"]:
        if not write:
            raise ValueError("Issuer IP drift: " + consumer["file"])
        scalar = scalar_node(node, "ip")
        return target, text, (scalar.start_mark.index, scalar.end_mark.index, route["ip"])
    return None


def _apply_renders(root: Path, pending: dict[Path, tuple[str, list[tuple[int, int, str]]]]) -> None:
    """Render and write every pending scalar replacement after all validation passes."""
    rendered = {}
    for target, (original, edits) in pending.items():
        previous = len(original) + 1
        result = original
        for start, end, replacement in sorted(edits, reverse=True):
            if end > previous:
                msg = "Overlapping registered issuer scalars"
                raise ValueError(msg)
            result = result[:start] + replacement + result[end:]
            previous = start
        rendered[target] = result
    for target, (original, _) in pending.items():
        if target.read_text() != original:
            raise ValueError(
                "Consumer changed before regeneration: " + str(target.relative_to(root))
            )
    for target, result in rendered.items():
        target.write_text(result)


def _issuer_aliases(root: Path, route: _IssuerRoute, *, write: bool) -> int:
    """Validate (and optionally regenerate) registered issuer transport consumers."""
    ipaddress.ip_address(route["ip"])
    seen = set()
    pending: dict[Path, tuple[str, list[tuple[int, int, str]]]] = {}
    for consumer in route["consumers"]:
        identity = (consumer["file"], tuple(consumer["path"]))
        if identity in seen:
            msg = "Duplicate registered consumer"
            raise ValueError(msg)
        seen.add(identity)
        # Validate every consumer before changing any file. A late scope error
        # must not leave a partly regenerated configuration behind.
        replacement = _check_consumer(root, route, consumer, write=write)
        if replacement is not None:
            target, text, edit = replacement
            original, edits = pending.setdefault(target, (text, []))
            if original != text:
                raise ValueError("Consumer changed during validation: " + consumer["file"])
            edits.append(edit)
    _apply_renders(root, pending)
    return len(seen)


def _validate_relay(root: Path, relay: _RelayContract, mesh: dict[str, _MeshNode]) -> None:
    """Validate the relay topology, updater identity, sandbox and playbook."""
    expected = _relay_topology(root, relay, mesh)
    _relay_updater(root, relay, mesh, expected)
    _relay_sandbox(root, relay, expected)
    _relay_hardening(root, relay)


def check(root=ROOT, write=False):
    c = json.loads((root / "deploy/contracts/infrastructure.json").read_text())
    if c["schemaVersion"] != 1:
        msg = "Unsupported contract schema"
        raise ValueError(msg)
    mesh = _validate_mesh(
        root / c["meshRegistry"],
        root / c["ansibleInventory"],
        c["sshEndpointFromPublicPeer"],
    )
    _validate_relay(root, c["relayContract"], mesh)
    return _issuer_aliases(root, c["issuerTransport"], write=write)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Regenerate registered IP scalars from the canonical route; review diff before commit",
    )
    args = parser.parse_args()
    count = check(write=args.write)
    print(
        f"Infrastructure contracts OK: mesh inventory, fixed relay and {count} scoped issuer consumers"
    )


if __name__ == "__main__":
    main()
