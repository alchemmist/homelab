"""Compare observed TLS ownership with independent Git-reviewed, namespace-local pins."""

import json
import re
import sys
from collections import defaultdict
from typing import cast

import yaml

from ci.quality.closed_root_backend import entries, plain, view
from ci.quality.public_tls_sources import inventory
from ci.quality.public_web import CATALOG

_LABEL = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?")
MAX_PIN_LENGTH = 253
MSG_EXPECTED_LIST = "expected a Kubernetes List envelope"


def _pin_choices(catalog: dict[str, object], issues: set[str]) -> dict[str, list[str]]:
    """Collect reviewed pins per host, including ordinary names without any pin."""
    choices: dict[str, list[str]] = {}
    for ns, hosts in view(catalog["hosts"]).items():
        for host, policy in view(hosts).items():
            pol = view(policy)
            pin = pol.get("tlsSourceName")
            if pol.get("route", "web") != "web":
                if "tlsSourceName" in pol:
                    issues.add(f"{ns}/{host}: non-web route may not pin a web key")
                continue
            choices.setdefault(host, [])  # Include ordinary names without any pin.
            if "tlsSourceName" not in pol:
                continue
            if (
                not isinstance(pin, str)
                or not 0 < len(pin) <= MAX_PIN_LENGTH
                or not all(_LABEL.fullmatch(p) for p in pin.split("."))
            ):
                issues.add(f"{ns}/{host}: invalid local TLS source name")
                continue
            choices[host].append(f"{ns}/{pin}")
    return choices


def _pin_bindings(
    choices: dict[str, list[str]],
    observed: dict[str, object],
    issues: set[str],
) -> "defaultdict[str, list[str]]":
    """Bind the host only when exactly one reviewed pin matches the observed source."""
    host_sources = view(observed["hostSources"])
    bindings: defaultdict[str, list[str]] = defaultdict(list)
    for host, pins in sorted(choices.items()):
        if len(pins) != 1:
            issues.add(f"{host}: expected one reviewed source pin, found {len(pins)}")
            continue
        if host_sources.get(host) != pins[0]:
            issues.add(f"{host}: observed source differs from reviewed pin")
            continue
        bindings[pins[0]].append(host)
    return bindings


def _certificate_issues(
    items: list[dict[str, object]],
    bindings: "defaultdict[str, list[str]]",
    issues: set[str],
) -> None:
    """Compare requested Certificate SAN sets against the reviewed source bindings."""
    for item in items:
        if item["kind"] != "Certificate":
            continue
        spec = view(item["spec"])
        secret_name = spec.get("secretName")
        if not isinstance(secret_name, str) or not secret_name:
            continue  # inventory recorded the malformed writer and blocked the whole plan
        ref = f"{view(item['metadata'])['namespace']}/{secret_name}"
        if ref not in bindings:
            continue
        dns = cast("list[str]", entries(spec.get("dnsNames", [])))
        if sorted(bindings[ref]) != sorted(dns) or any(
            spec.get(k) for k in ("ipAddresses", "uris", "emailAddresses", "otherNames")
        ):
            issues.add(f"{ref}: requested SAN set differs from reviewed source")


def compare(catalog: dict[str, object], items: list[dict[str, object]]) -> dict[str, object]:
    """Missing pins never mean use discovery. Withhold the entire reader plan on error."""
    observed = inventory(catalog, items)
    issues = {plain(e) for e in entries(observed["errors"])}
    bindings = _pin_bindings(_pin_choices(catalog, issues), observed, issues)
    _certificate_issues(items, bindings, issues)
    return {"sources": {} if issues else dict(sorted(bindings.items())), "errors": sorted(issues)}


def _list_envelope(batch: object) -> list[dict[str, object]]:
    """Gate stdin input on the exact Kubernetes List envelope shape."""
    if not isinstance(batch, dict):
        reason = MSG_EXPECTED_LIST
        raise TypeError(reason)
    items = entries(view(batch).get("items"))
    return cast("list[dict[str, object]]", items)


def main() -> int:
    """Compare catalog pins with a stdin Kubernetes List, exiting nonzero on any issue."""
    try:
        batch = json.load(sys.stdin)
        report = compare(
            yaml.safe_load(CATALOG.read_text()),
            _list_envelope(batch),
        )
    except (KeyError, TypeError, ValueError, AttributeError, yaml.YAMLError):
        # Never echo input values, exception text or a non-empty partial plan.
        report = {"sources": {}, "errors": ["invalid catalog or Kubernetes List input"]}

    print(json.dumps(report, indent=2))
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
