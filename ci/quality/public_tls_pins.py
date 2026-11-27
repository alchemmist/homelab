"""Compare observed TLS ownership with independent Git-reviewed, namespace-local pins."""

import json
import re
import sys
from collections import defaultdict

import yaml

from ci.quality.public_tls_sources import inventory
from ci.quality.public_web import CATALOG

_LABEL = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?")


def compare(catalog: dict, items: list[dict]) -> dict:
    """Missing pins never mean use discovery. Withhold the entire reader plan on error."""
    observed = inventory(catalog, items)
    issues = set(observed["errors"])
    choices = defaultdict(list)
    for ns, hosts in catalog["hosts"].items():
        for host, policy in hosts.items():
            pin = policy.get("tlsSourceName")
            if policy.get("route", "web") != "web":
                if "tlsSourceName" in policy:
                    issues.add(f"{ns}/{host}: non-web route may not pin a web key")
                continue
            choices.setdefault(host, [])  # Include ordinary names without any pin.
            if "tlsSourceName" not in policy:
                continue
            if (
                not isinstance(pin, str)
                or not 0 < len(pin) <= 253
                or not all(_LABEL.fullmatch(p) for p in pin.split("."))
            ):
                issues.add(f"{ns}/{host}: invalid local TLS source name")
                continue
            choices[host].append(f"{ns}/{pin}")
    bindings = defaultdict(list)
    for host, pins in sorted(choices.items()):
        if len(pins) != 1:
            issues.add(f"{host}: expected one reviewed source pin, found {len(pins)}")
            continue
        if observed["hostSources"].get(host) != pins[0]:
            issues.add(f"{host}: observed source differs from reviewed pin")
            continue
        bindings[pins[0]].append(host)
    return {"sources": {} if issues else dict(sorted(bindings.items())), "errors": sorted(issues)}


def main() -> int:
    report = compare(yaml.safe_load(CATALOG.read_text()), json.load(sys.stdin)["items"])
    print(json.dumps(report, indent=2))
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
