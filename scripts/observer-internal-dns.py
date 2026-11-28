#!/usr/bin/env python3
"""Scoped Authentik cluster DNS repair; default read-only, CAS apply once, no replay.

Run on approved controller with root k3s kubectl. A new private state directory is
mandatory for apply. Existing exact owned key is accepted read-only; different key
contents stop. Uncertain writes require inspect/readback, never apply replay.
"""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import cast

HOST = "auth.socrat.alchemmist.xyz"
KEY = "authentik-internal.server"
INTERNAL_VIP = "192.168.0.250"
HTTPS_PORT = 443
ACME_RESOLVER_ARG = "--acme-http01-solver-nameservers=1.1.1.1:53,9.9.9.9:53"


def _map(node: object) -> "dict[str, object]":
    """Cast one reviewed JSON node to a plain object map."""
    return cast("dict[str, object]", node)


def zone(address: str) -> str:
    """Render the Authentik CoreDNS zone for a private IPv4 address."""
    import ipaddress

    if not ipaddress.ip_address(address).is_private or ":" in address:
        msg = "Expected private IPv4 Service address"
        raise ValueError(msg)
    return f"""{HOST}:53 {{
    errors
    hosts {{
        {address} {HOST}
        ttl 30
        no_reverse
        fallthrough
    }}
    cache 30
    forward . /etc/resolv.conf
}}
"""


def desired(
    before: dict[str, object], address: str, owned_value: str | None = None
) -> dict[str, str]:
    """Copy the ConfigMap data and refuse to replace a conflicting unowned zone."""
    value = zone(address)
    old = _map(before.get("data", {})).get(KEY)
    if old is not None and old not in (value, owned_value):
        msg = "Owned DNS key collision; inspect before changing"
        raise RuntimeError(msg)
    data = dict(cast("dict[str, str]", _map(before.get("data", {}))))
    data[KEY] = value
    return data


def patch(before: dict[str, object], data: dict[str, str]) -> list[dict[str, object]]:
    """Test the ConfigMap identity, version, and data before setting the owned key."""
    meta = _map(before["metadata"])
    return [
        {"op": "test", "path": "/metadata/uid", "value": meta["uid"]},
        {
            "op": "test",
            "path": "/metadata/resourceVersion",
            "value": meta["resourceVersion"],
        },
        {"op": "test", "path": "/data", "value": before["data"]},
        {"op": "add", "path": "/data/" + KEY, "value": data[KEY]},
    ]


def kubectl(*args: str, payload: str | None = None) -> dict[str, object]:
    """Run k3s kubectl once and decode its JSON response, failing on a nonzero exit."""
    r = subprocess.run(
        ["k3s", "kubectl", *args],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if r.returncode:
        msg = "Kubernetes operation failed; inspect private state, no blind retry"
        raise RuntimeError(msg)
    return _map(json.loads(r.stdout))


def _require_reviewed_preconditions(service: dict[str, object], cert: dict[str, object]) -> None:
    """Require the reviewed Service port and public ACME resolver arguments."""
    ports = cast("list[dict[str, object]]", _map(service["spec"])["ports"])
    if not any(p["port"] == HTTPS_PORT for p in ports):
        msg = "Public HTTPS Service precondition missing"
        raise RuntimeError(msg)
    containers = cast(
        "list[dict[str, object]]",
        _map(_map(_map(cert["spec"])["template"])["spec"])["containers"],
    )
    if not any(
        x == ACME_RESOLVER_ARG for c in containers for x in cast("list[object]", c.get("args", []))
    ):
        msg = "Public ACME resolver precondition missing"
        raise RuntimeError(msg)


def _require_repairable_configmap(before: dict[str, object]) -> None:
    """Require a mutable ConfigMap that already carries data to preserve."""
    if not before.get("data"):
        msg = "ConfigMap must carry existing data to preserve"
        raise RuntimeError(msg)
    if before.get("immutable", False):
        msg = "Immutable ConfigMap cannot be repaired"
        raise RuntimeError(msg)


def _owned_value_from_receipt(state_dir: Path, before: dict[str, object]) -> str:
    """Return the only value a fully accepted prior receipt authorizes replacing."""
    receipt = _map(json.loads((state_dir / "receipt.json").read_text()))
    previous = _map(json.loads((state_dir / "after.json").read_text()))
    if receipt["state"] != "exact-readback-accepted":
        msg = "Replacement requires a previously accepted exact-readback receipt"
        raise RuntimeError(msg)
    if receipt["only_changed_key"] != KEY:
        msg = "Replacement only authorizes the reviewed owned key"
        raise RuntimeError(msg)
    if (state_dir / "uncertain.json").exists():
        msg = "Prior state must be fully accepted before replacement"
        raise RuntimeError(msg)
    if _map(previous["metadata"])["uid"] != _map(before["metadata"])["uid"]:
        msg = "Prior receipt belongs to a different ConfigMap"
        raise RuntimeError(msg)
    return cast("str", _map(previous["data"])[KEY])


def _apply_and_verify(
    state: Path,
    before: dict[str, object],
    data: dict[str, str],
    digest: str,
) -> None:
    """Apply the approved patch once and verify the exact readback before saving."""
    before_meta = _map(before["metadata"])

    def save(name: str, obj: object) -> None:
        (state / name).write_text(json.dumps(obj, sort_keys=True))

    save("before.json", before)
    if data != before["data"]:
        save(
            "uncertain.json",
            {"state": "write-about-to-start", "approval_sha256": digest},
        )
        patch_payload = patch(before, data)
        result = kubectl(
            "-n",
            "kube-system",
            "patch",
            "configmap",
            "coredns-custom",
            "--type=json",
            "-p",
            json.dumps(patch_payload),
            "-o",
            "json",
        )
        save("write-response.json", result)
    after = kubectl("-n", "kube-system", "get", "configmap", "coredns-custom", "-o", "json")
    if _map(after["metadata"])["uid"] != before_meta["uid"]:
        msg = "ConfigMap identity changed during apply"
        raise RuntimeError(msg)
    if after["data"] != data:
        msg = "Exact post-write readback failed"
        raise RuntimeError(msg)
    save("after.json", after)
    save(
        "receipt.json",
        {
            "state": "exact-readback-accepted",
            "approval_sha256": digest,
            "only_changed_key": KEY,
            "runtime_acceptance": "pending",
            "other_data_preserved": True,
        },
    )
    marker = state / "uncertain.json"
    if marker.exists():
        marker.unlink()


def main() -> None:
    """Preview the DNS repair or apply the approved patch and check the exact readback."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--state", type=Path)
    p.add_argument("--approve-sha256")
    p.add_argument(
        "--replace-owned-state",
        type=Path,
        help="Prior accepted private receipt authorizing replacement of ONLY its exact owned key",
    )
    a = p.parse_args()
    service = kubectl("-n", "kube-system", "get", "svc", "traefik", "-o", "json")
    cert = kubectl("-n", "cert-manager", "get", "deployment", "cert-manager", "-o", "json")
    _require_reviewed_preconditions(service, cert)
    before = kubectl("-n", "kube-system", "get", "configmap", "coredns-custom", "-o", "json")
    _require_repairable_configmap(before)
    address = INTERNAL_VIP
    owned_value = None
    if a.replace_owned_state:
        owned_value = _owned_value_from_receipt(a.replace_owned_state, before)
    data = desired(before, address, owned_value)
    plan = {
        "configmap_uid": _map(before["metadata"])["uid"],
        "resourceVersion": _map(before["metadata"])["resourceVersion"],
        "service_uid": _map(service["metadata"])["uid"],
        "service_address": _map(service["spec"])["clusterIP"],
        "internal_vip": address,
        "before_data": before["data"],
        "after_data": data,
        "key": KEY,
        "host": HOST,
    }
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    if not a.apply:
        print(
            json.dumps(
                {
                    "approval_sha256": digest,
                    "change_required": data != before["data"],
                    "service_address": _map(service["spec"])["clusterIP"],
                    "internal_vip": address,
                    "writes": False,
                }
            )
        )
        return
    if a.approve_sha256 != digest:
        msg = "Fresh exact preimage approval required"
        raise RuntimeError(msg)
    if a.state is None:
        msg = "New private state directory required; no replay"
        raise RuntimeError(msg)
    if a.state.exists():
        msg = "New private state directory required; no replay"
        raise RuntimeError(msg)
    os.umask(0o077)
    a.state.mkdir(mode=0o700, parents=False)
    _apply_and_verify(a.state, before, data, digest)
    current = kubectl("-n", "kube-system", "get", "svc", "traefik", "-o", "json")
    if _map(current["metadata"])["uid"] != _map(service["metadata"])["uid"]:
        msg = "Service identity changed during apply"
        raise RuntimeError(msg)
    if _map(current["spec"])["clusterIP"] != _map(service["spec"])["clusterIP"]:
        msg = "Service address changed during apply"
        raise RuntimeError(msg)
    print(
        json.dumps(
            {
                "state": "exact-readback-accepted",
                "runtime_acceptance": "pending",
                "only_changed_key": KEY,
            }
        )
    )


if __name__ == "__main__":
    main()
