#!/usr/bin/env python3
"""Offline contracts. Default checks; --write changes ONLY registered IP scalars.
Never contacts Kubernetes, runs workflows, reads credentials, or executes tools.
"""

import argparse
import ast
import configparser
import ipaddress
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    """Document this public function."""
    return yaml.safe_load(path.read_text())


def scalar_node(node, key):
    """Document this public function."""
    for k, value in node.value:
        if k.value == key:
            return value
    raise ValueError("Missing registered YAML field: " + key)


def check(root=ROOT, write=False):
    """Document this public function."""
    c = json.loads((root / "deploy/contracts/infrastructure.json").read_text())
    if c["schemaVersion"] != 1:
        raise ValueError("Unsupported contract schema")
    mesh = load(root / c["meshRegistry"])["wg_socrat_nodes"]
    hosts = load(root / c["ansibleInventory"])["all"]["children"]["Socrat"]["hosts"]
    if set(mesh) != set(hosts):
        raise ValueError("Inventory/mesh node membership drift")
    addresses = [str(ipaddress.ip_address(n["address"])) for n in mesh.values()]
    if len(set(addresses)) != len(addresses):
        raise ValueError("Duplicate node mesh addresses")
    for name, node in mesh.items():
        expected = (
            node["endpoint"].rsplit(":", 1)[0]
            if name in c["sshEndpointFromPublicPeer"]
            else node["address"]
        )
        if hosts[name]["ansible_host"] != expected:
            raise ValueError("Inventory endpoint drift: " + name)
    relay = c["relayContract"]

    def literals(path):
        result = {}
        for statement in ast.parse((root / path).read_text()).body:
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                try:
                    result[statement.targets[0].id] = ast.literal_eval(statement.value)
                except (ValueError, TypeError):
                    pass
        return result

    r = literals(relay["relayScript"])
    e = literals(relay["endpointScript"])
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
        raise ValueError("Fixed relay topology drift; requires reviewed network change")
    if (
        e.get("RELAY") != expected["FRONT"][0] + ":" + str(relay["frontPort"])
        or e.get("PEER") != mesh[relay["targetNode"]]["public_key"]
        or e.get("DIRECT") != relay["directRecoveryEndpoint"]
    ):
        raise ValueError("Relay updater endpoint/peer identity drift")
    unit = configparser.ConfigParser(interpolation=None)
    unit.read_string((root / relay["serviceFile"]).read_text())
    service = unit["Service"]
    allow = service["IPAddressAllow"].split()
    required = {expected["CLIENT"][0] + "/32", target_ip + "/32"}
    if len(allow) != len(required) or set(allow) != required or service["IPAddressDeny"] != "any":
        raise ValueError("Relay sandbox endpoint scope drift; no automatic network regeneration")
    for key, value in {
        "DynamicUser": "yes",
        "NoNewPrivileges": "yes",
        "CapabilityBoundingSet": "",
        "AmbientCapabilities": "",
    }.items():
        if service.get(key) != value:
            raise ValueError("Relay sandbox privilege drift: " + key)
    playbook = load(root / relay["installPlaybook"])
    assertion = next(
        t["ansible.builtin.assert"]["that"]
        for t in playbook[0]["tasks"]
        if t.get("name") == "Validate relay mesh identity without reading WG keys"
    )
    if not any(
        "wg_socrat_nodes['" + relay["frontNode"] + "']['address']" in line for line in assertion
    ):
        raise ValueError("Relay preflight must derive the address from the mesh registry")
    route = c["issuerTransport"]
    ipaddress.ip_address(route["ip"])
    seen = set()
    pending = {}
    for consumer in route["consumers"]:
        file = consumer["file"]
        identity = (file, tuple(consumer["path"]))
        if identity in seen:
            raise ValueError("Duplicate registered consumer")
        seen.add(identity)
        target = root / file
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError("Consumer escapes repository")
        text = target.read_text()
        value, tree = yaml.safe_load(text), yaml.compose(text)
        for key in consumer["path"]:
            value, tree = value[key], scalar_node(tree, key)
        matches = [
            (entry, node)
            for entry, node in zip(value, tree.value)
            if route["hostname"] in entry.get("hostnames", [])
        ]
        if len(matches) != 1:
            raise ValueError("Missing/duplicate issuer alias: " + file)
        entry, node = matches[0]
        # The shared route must not accidentally redirect other hostnames.
        if entry["hostnames"] != [route["hostname"]]:
            raise ValueError("Issuer alias scope widened: " + file)
        ipaddress.ip_address(entry["ip"])
        if entry["ip"] != route["ip"]:
            if not write:
                raise ValueError("Issuer IP drift: " + file)
            scalar = scalar_node(node, "ip")
            original, edits = pending.setdefault(target, (text, []))
            if original != text:
                raise ValueError("Consumer changed during validation: " + file)
            edits.append((scalar.start_mark.index, scalar.end_mark.index, route["ip"]))
    # Validate every consumer before changing any file. A late scope error must
    # not leave a partly regenerated configuration behind.
    rendered = {}
    for target, (original, edits) in pending.items():
        previous = len(original) + 1
        result = original
        for start, end, replacement in sorted(edits, reverse=True):
            if end > previous:
                raise ValueError("Overlapping registered issuer scalars")
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
    return len(seen)


def main():
    """Document this public function."""
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
