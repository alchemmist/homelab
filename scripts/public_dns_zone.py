#!/usr/bin/env python3
"""Render the alchemmist.xyz zone from static records and ingress health."""

import argparse
import socket
from pathlib import Path

HOME = "109.173.40.247"
VPS = "109.120.141.60"
TTL = 60

# Names that currently publish both public entrances and can follow health.
FAILOVER = [
    "@",
    "www",
    "0.socrat",
    "1.socrat",
    "2.socrat",
    "3.socrat",
    "argocd.socrat",
    "auth.socrat",
    "bot.socrat",
    "cats",
    "chat",
    "fq",
    "grafana-mcp.socrat",
    "grafana.socrat",
    "harbor.socrat",
    "img",
    "kuma.socrat",
    "litellm.socrat",
    "llm",
    "llm.socrat",
    "lms",
    "monori",
    "n8n.socrat",
    "netbird.socrat",
    "pr-agent.socrat",
    "rancher.socrat",
    "remark42",
    "rustfs.socrat",
    "search.socrat",
    "socrat",
    "spi-evidence.socrat",
    "sso.socrat",
    "status",
    "umami",
    "vpn",
    "wiki.socrat",
]

# Names that have a single published address and must not move.
STATIC_A = {
    "netbird-relay-vps.socrat": [VPS],
    "devsyringe": [HOME],
    "mail": [HOME],
    "rooms": [HOME],
    "sync": [HOME],
    "sync-0": [HOME],
    "sync-1": [HOME],
}

TXT = [
    "google-site-verification=TEJ0Yt1fy0WpksDJwAjEiNlsHQjVbdYUlEWfsAYxlRk",
    "v=spf1 mx ~all",
    "yandex-verification: 44929ed931452fe4",
]


def healthy_addresses(home_up, vps_up):
    chosen = []
    if home_up:
        chosen.append(HOME)
    if vps_up:
        chosen.append(VPS)
    if not chosen:
        return [HOME, VPS]
    return chosen


def render(serial, home_up, vps_up):
    addresses = healthy_addresses(home_up, vps_up)
    lines = [
        "$ORIGIN alchemmist.xyz.",
        "$TTL %d" % TTL,
        "@ IN SOA ns1.alchemmist.xyz. hostmaster.alchemmist.xyz. (%d 60 30 604800 60)" % serial,
        "@ IN NS ns1.alchemmist.xyz.",
        "@ IN NS ns2.alchemmist.xyz.",
        "ns1 IN A %s" % HOME,
        "ns2 IN A %s" % VPS,
        "@ IN MX 10 mail.alchemmist.xyz.",
    ]
    for value in TXT:
        lines.append('@ IN TXT "%s"' % value)
    for name in FAILOVER:
        for address in addresses:
            lines.append("%s IN A %s" % (name, address))
    for name in sorted(STATIC_A):
        for address in STATIC_A[name]:
            lines.append("%s IN A %s" % (name, address))
    lines.append("")
    return "\n".join(lines)


def probe(address, port, timeout):
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect((address, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--home-target", default=HOME)
    parser.add_argument("--vps-target", default=VPS)
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--timeout", type=float, default=3)
    parser.add_argument("--assume-home", choices=("probe", "up", "down"), default="probe")
    parser.add_argument("--assume-vps", choices=("probe", "up", "down"), default="probe")
    args = parser.parse_args()
    home_up = True if args.assume_home == "up" else False if args.assume_home == "down" else probe(args.home_target, args.port, args.timeout)
    vps_up = True if args.assume_vps == "up" else False if args.assume_vps == "down" else probe(args.vps_target, args.port, args.timeout)
    text = render(args.serial, home_up, vps_up)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    previous = args.output.read_text() if args.output.exists() else ""
    if previous != text:
        temporary = args.output.with_suffix(".zone.tmp")
        temporary.write_text(text)
        temporary.replace(args.output)
        print("updated home=%s vps=%s" % (home_up, vps_up))
    else:
        print("unchanged home=%s vps=%s" % (home_up, vps_up))


if __name__ == "__main__":
    main()
