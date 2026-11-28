"""Compile one location-independent public replica from the reviewed app registry."""

import argparse
import ipaddress
import json
import runpy
from pathlib import Path

import yaml

from services.public_entry.tls_issuance import _mapping

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "deploy/public-web/entrances.yaml"
VALUES = ROOT / "charts/traefik-edge/values.yaml"  # Legacy controller migration checks only.
ZONE = "alchemmist.xyz"
REPLICA_FIELDS = {"node", "publicIP"}
MAX_SERIAL = 2**32
MSG_REPLICA_INVENTORY_FIELDS = "Replica inventory may specify only node and publicIP"
MSG_EXPECTED_REPLICA_ADDRESS = "expected a textual or numeric replica address"
MSG_EXPECTED_UNSIGNED_SERIAL = "Expected an unsigned nonzero DNS serial"
MSG_MANAGED_OUTSIDE_ZONE = "Managed web host outside the authoritative zone"


def replica_values(
    catalog: dict[str, object], instance: dict[str, object], serial: int
) -> dict[str, object]:
    """Keep authority, mail and transport RRs; replace managed web A records only."""
    if set(instance) != REPLICA_FIELDS:
        raise ValueError(MSG_REPLICA_INVENTORY_FIELDS)
    address_value = instance["publicIP"]
    if not isinstance(address_value, (str, int)):
        raise TypeError(MSG_EXPECTED_REPLICA_ADDRESS)
    address = str(ipaddress.IPv4Address(address_value))
    if not 0 < serial < MAX_SERIAL:
        raise ValueError(MSG_EXPECTED_UNSIGNED_SERIAL)
    hosts = _mapping(catalog["hosts"])
    publications: dict[str, list[str]] = {}
    for ns, names_value in hosts.items():
        names = _mapping(names_value)
        published = sorted(
            host for host, plan in names.items() if _mapping(plan).get("route", "web") == "web"
        )
        if published:
            publications[ns] = published
    managed: set[str] = set()
    for ns, published in publications.items():
        for host in published:
            dns = _mapping(_mapping(hosts[ns])[host])["dns"]
            if isinstance(dns, str) and dns == "managed":
                managed.add(host)
    if any(host != ZONE and not host.endswith("." + ZONE) for host in managed):
        raise ValueError(MSG_MANAGED_OUTSIDE_ZONE)
    owners = {"@" if host == ZONE else host.removesuffix("." + ZONE) for host in managed}
    # Pure offline baseline. Never probe, write or invoke the live Knot publisher.
    home_up = True
    vps_up = True
    zone = runpy.run_path(str(ROOT / "ansible/scripts/public_dns_zone.py"))["render"](
        serial, home_up, vps_up, web_answers=dict.fromkeys(owners, address)
    )
    return {"instance": instance, "publications": publications, "zoneFile": zone}


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
