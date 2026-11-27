"""List every public route's single-IP acceptance cases or check one client's DNS view."""

import argparse
import socket

import yaml

from ci.quality.public_web import CATALOG

ENTRIES = {
    name: item["publicIP"] for name, item in yaml.safe_load(CATALOG.read_text())["replicas"].items()
}


def cases(catalog: dict) -> dict[tuple[str, str, str], str]:
    """Retain namespace/path owners; policy and topology gaps are not passing tests."""
    rows = {}
    for ns, hosts in catalog["hosts"].items():
        for host, policy in hosts.items():
            for entry in catalog["replicas"]:
                if policy.get("route") == "reserved":
                    state = "reserved"
                elif policy.get("route") == "vpn-transit":
                    state = "dedicated VPN path"
                elif policy.get("route") == "fixed-relay":
                    state = "fixed relay"
                elif policy.get("dns") == "external":
                    state = "external DNS; not a self-IP case"
                else:
                    state = "unverified"
                rows[ns, host, entry] = state
    return rows


def dns_view(host: str) -> set[str]:
    """Use the client's ordinary address selection inputs, including any IPv6 answers."""
    return {str(item[4][0]) for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}


def main() -> int:
    """By default print an offline matrix; perform DNS lookup only on explicit request."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dns", nargs=3, metavar=("NAMESPACE", "HOST", "SURVIVOR"))
    args = parser.parse_args()
    rows = cases(yaml.safe_load(CATALOG.read_text()))
    if not args.dns:
        print("namespace\thost\thome only\tnl only\tmoscow only")
        for ns, host in sorted({(ns, host) for ns, host, _ in rows}):
            print("\t".join([ns, host, *(rows[ns, host, entry] for entry in ENTRIES)]))
        return 0
    ns, host, entry = args.dns
    if entry not in ENTRIES:
        parser.error(f"Unknown survivor {entry!r}; choose from {', '.join(ENTRIES)}")
    state = rows.get((ns, host, entry))
    if state is None:
        parser.error(f"Unknown matrix case: {ns}/{host} at {entry}")
    if state != "unverified":
        parser.error(
            f"Matrix case is not eligible for a DNS check: {state} ({ns}/{host} at {entry})"
        )
    try:
        actual = dns_view(host)
    except OSError as exc:
        print(f"DNS check failed: {type(exc).__name__}")
        return 1
    if actual != {ENTRIES[entry]}:
        print(f"DNS does not resolve exclusively to {entry}: {', '.join(sorted(actual))}")
        return 1
    print(f"Client DNS matches {entry}; TLS, application and outage independence are unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
