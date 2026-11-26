"""Compile one location-independent public replica from the reviewed app registry."""

import argparse
import ipaddress
import json
import runpy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "deploy/public-web/entrances.yaml"
VALUES = ROOT / "charts/traefik-edge/values.yaml"  # Legacy controller migration checks only.
ZONE = "alchemmist.xyz"


def replica_values(catalog: dict, instance: dict, serial: int) -> dict:
    """Keep authority, mail and transport RRs; replace managed web A records only."""
    if set(instance) != {"node", "publicIP"}:
        raise ValueError("Replica inventory may specify only node and publicIP")
    address = str(ipaddress.IPv4Address(instance["publicIP"]))
    if not 0 < serial < 2**32:
        raise ValueError("Expected an unsigned nonzero DNS serial")
    hosts = catalog["hosts"]
    publications = {
        ns: sorted(h for h, p in names.items() if p.get("route", "web") == "web")
        for ns, names in hosts.items()
    }
    publications = {ns: names for ns, names in publications.items() if names}
    managed = {
        host
        for ns, names in publications.items()
        for host in names
        if hosts[ns][host]["dns"] == "managed"
    }
    if any(host != ZONE and not host.endswith("." + ZONE) for host in managed):
        raise ValueError("Managed web host outside the authoritative zone")
    owners = {"@" if host == ZONE else host.removesuffix("." + ZONE) for host in managed}
    # Pure offline baseline. Never probe, write or invoke the live Knot publisher.
    baseline = runpy.run_path(str(ROOT / "ansible/scripts/public_dns_zone.py"))["render"](
        serial, True, True
    )
    lines = []
    for line in baseline.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] in owners and parts[1:3] == ["IN", "A"]:
            continue
        lines.append(line)
    lines.extend(f"{owner} IN A {address}" for owner in sorted(owners))
    return {"instance": instance, "publications": publications, "zoneFile": "\n".join(lines) + "\n"}


def main() -> None:
    """Print private-stage Helm values for one inventory entry; never change production."""
    catalog = yaml.safe_load(CATALOG.read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replica", choices=catalog["replicas"])
    parser.add_argument("--serial", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(replica_values(catalog, catalog["replicas"][args.replica], args.serial)))


if __name__ == "__main__":
    main()
