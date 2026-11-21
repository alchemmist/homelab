#!/usr/bin/env python3
"""Historical first-activation plan; hash-approved apply after real OIDC refresh.

Not a replay/reconciliation command after the single-gateway migration. Existing
policy/state drift is deliberately rejected rather than overwritten.

Run on socrat-0 with private bootstrap PAT/journal. Never invent a JWT group or
modify human accounts, WireGuard, SSH, setup keys, router identities, or defaults.
After any apply error inspect the exclusive journal; no blind mutation retries.
"""

import argparse
import hashlib
import json
import os
import runpy
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path.home() / ".local/state/netbird-internal-stage/journal"
BASE = "https://netbird.socrat.alchemmist.xyz/api/"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects when calling the private NetBird API."""

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def _api(token: str, method: str, endpoint: str, body: object = None) -> object:
    """Call one private NetBird API endpoint without following redirects."""
    req = urllib.request.Request(
        BASE + endpoint,
        method=method,
        headers={"Authorization": "Token " + token, "Content-Type": "application/json"},
        data=None if body is None else json.dumps(body).encode(),
    )
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(req, timeout=15) as response:
        return json.load(response)


def _reviewed_journal() -> tuple[str, dict[str, object]]:
    """Load the private bootstrap token and journal state, refusing replays."""
    token = cast("str", json.loads((ROOT / "bootstrap.json").read_text())["personal_access_token"])
    state = cast(
        "dict[str, object]", json.loads((ROOT / "internal-network-stage.json").read_text())
    )
    if state["state"] != "internal-resources-ready-await-genuine-admin-JWT":
        raise ValueError("unexpected stage or replay")
    if not (ROOT / "internal-network-enrollment-retired.json").is_file():
        raise ValueError("enrollment keys and Secrets must be retired first")
    return token, state


def _require_owner_alignment(token: str, identity: object) -> list[object]:
    """Require the recorded owner identity to hold the only owner role."""
    users = cast("list[object]", _api(token, "GET", "users"))
    raw_identity = cast("dict[str, object]", identity)
    target_user = cast("Callable[[object, object], None]", raw_identity["target_user"])
    subject = cast("Callable[[], object]", raw_identity["subject"])
    target_user(users, subject())
    if [
        cast("dict[str, object]", u)["id"]
        for u in users
        if cast("dict[str, object]", u)["role"] == "owner"
    ] != [subject()]:
        raise ValueError("native owner identity mismatch")
    return users


def _require_unmodified_policies(token: str, state: dict[str, object]) -> list[object]:
    """Only the reviewed SSH policy may exist before activation."""
    policies = cast("list[object]", _api(token, "GET", "policies"))
    if {cast("dict[str, object]", p)["id"] for p in policies} != {state["ssh_policy"]}:
        raise ValueError("unexpected policy drift")
    return policies


def _reviewed_admin_group(token: str, compiler: object) -> tuple[str, object]:
    """Resolve the genuine admin JWT group id and its current membership."""
    groups = _api(token, "GET", "groups")
    genuine_admin_group = cast(
        "Callable[[object], str]", cast("dict[str, object]", compiler)["genuine_admin_group"]
    )
    admin_id = genuine_admin_group(groups)
    group = _api(token, "GET", "groups/" + admin_id)
    return admin_id, group


def _reviewed_admin_members(token: str, identity: object, group: object) -> set[object]:
    """Admin JWT members must be genuinely admitted exact-owner devices only."""
    members = {
        cast("dict[str, object]", p)["id"] if isinstance(p, dict) else p
        for p in cast("list[object]", cast("dict[str, object]", group).get("peers", []))
    }
    peers = cast("list[object]", _api(token, "GET", "peers"))
    subject = cast("Callable[[], object]", cast("dict[str, object]", identity)["subject"])
    owner_peers = {
        cast("dict[str, object]", p)["id"]
        for p in peers
        if cast("dict[str, object]", p).get("user_id") == subject()
        and not cast("dict[str, object]", p).get("approval_required")
        and not cast("dict[str, object]", p).get("login_expired")
    }
    if not members or not members.issubset(owner_peers):
        raise ValueError("admin JWT members must be genuinely admitted exact-owner devices only")
    return members


def _require_network_alignment(token: str, state: dict[str, object]) -> None:
    """Live networks must exactly match the reviewed journal networks."""
    state_networks = cast("dict[str, dict[str, object]]", state["networks"])
    if {cast("dict[str, object]", n)["id"] for n in _api(token, "GET", "networks")} != {
        cast("dict[str, object]", n)["id"] for n in state_networks.values()
    }:
        raise ValueError("network drift")


def _planned_policies(
    compiler: object, admin_id: str, resources: list[object]
) -> list[dict[str, object]]:
    """Build admin-only policy writes for each reviewed host resource."""
    plan = []
    policy_body = cast(
        "Callable[[str, object], dict[str, object]]",
        cast("dict[str, object]", compiler)["policy_body"],
    )
    for resource in resources:
        raw = cast("dict[str, object]", resource)
        if not raw["enabled"] or raw["type"] != "host" or raw.get("groups"):
            raise ValueError("resource enabled/type/group drift")
        plan.append(
            {
                "address": raw["address"],
                "body": policy_body(admin_id, raw["id"]),
            }
        )
    return plan


def _build_activation_plan(
    token: str, compiler: object, state: dict[str, object], admin_id: str
) -> list[dict[str, object]]:
    """Verify every reviewed host network and build its policy writes."""
    _require_network_alignment(token, state)
    plan = []
    networks = cast("dict[str, object]", state["networks"])
    peers = cast("dict[str, object]", state["peers"])
    compiled_networks = cast(
        "dict[str, tuple[object, list[str]]]", cast("dict[str, object]", compiler)["NETWORKS"]
    )
    for host, (name, addresses) in compiled_networks.items():
        network = cast("dict[str, object]", networks[host])
        resources = cast(
            "list[object]",
            _api(token, "GET", "networks/" + cast("str", network["id"]) + "/resources"),
        )
        if {cast("dict[str, object]", r)["address"] for r in resources} != set(addresses):
            raise ValueError("resource scope drift")
        routers = cast(
            "list[dict[str, object]]",
            _api(token, "GET", "networks/" + cast("str", network["id"]) + "/routers"),
        )
        expected_peer = cast("dict[str, object]", peers[host])["id"]
        if (
            len(routers) != 1
            or routers[0]["peer"] != expected_peer
            or not routers[0]["enabled"]
            or not routers[0]["masquerade"]
        ):
            raise ValueError("router/return-path drift")
        plan.extend(_planned_policies(compiler, admin_id, resources))
    return plan


def _activate_policies(token: str, admin_id: str, plan: list[dict[str, object]]) -> list[str]:
    """Create each reviewed policy once, journaling progress before continuing."""
    created = []
    for item in plan:
        response = cast("dict[str, object]", _api(token, "POST", "policies", item["body"]))
        created.append(cast("str", response["id"]))
        # Record each successful create before any subsequent mutation.
        progress = ROOT / "internal-network-activation-progress.json"
        progress.write_text(json.dumps({"created_policy_ids": created}))
        progress.chmod(0o600)
        rule = cast("dict[str, object]", cast("list[object]", response["rules"])[0])
        source_ids = {
            cast("dict[str, object]", g)["id"] if isinstance(g, dict) else g
            for g in cast("list[object]", rule["sources"])
        }
        body = cast("dict[str, object]", item["body"])
        if (
            source_ids != {admin_id}
            or rule["protocol"] != "all"
            or rule["bidirectional"]
            or rule["destinationResource"]
            != cast("dict[str, object]", cast("list[object]", body["rules"])[0])[
                "destinationResource"
            ]
        ):
            raise ValueError("native policy readback mismatch; inspect journal, no retry")
    return created


def _require_activation_converged(
    token: str, state: dict[str, object], created: list[str], users: list[object]
) -> None:
    """Require no unrelated policy or human role changes after activation."""
    after = cast("list[object]", _api(token, "GET", "policies"))
    if {cast("dict[str, object]", p)["id"] for p in after} != {state["ssh_policy"], *created}:
        raise ValueError("unexpected policies after activation")
    if {
        cast("dict[str, object]", u)["id"]: cast("dict[str, object]", u)["role"]
        for u in cast("list[object]", _api(token, "GET", "users"))
    } != {cast("dict[str, object]", u)["id"]: cast("dict[str, object]", u)["role"] for u in users}:
        raise ValueError("unexpected role changes")


def main():
"""Plan or apply the guarded internal stage activation."""
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve-plan-hash")
    args = parser.parse_args()
    compiler = runpy.run_path(str(Path(__file__).with_name("netbird-internal-network.py")))
    identity = runpy.run_path(str(ROOT.parent / "owner-handover-v2.py"))
    token, state = _reviewed_journal()
    users = _require_owner_alignment(token, identity)
    policies = _require_unmodified_policies(token, state)
    admin_id, group = _reviewed_admin_group(token, compiler)
    members = _reviewed_admin_members(token, identity, group)
    plan = _build_activation_plan(token, compiler, state, admin_id)
    plan.sort(key=lambda p: cast("dict[str, object]", p)["address"])
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    print(
        json.dumps(
            {
                "plan_hash": digest,
                "admin_devices": len(members),
                "destinations": [cast("dict[str, object]", p)["address"] for p in plan],
                "writes": len(plan),
            }
        ),
        flush=True,
    )
    if not args.apply:
        return
    if args.approve_plan_hash != digest:
        raise ValueError("approved current plan hash required")
    dest = ROOT / "internal-network-activation-before.json"
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(
            {
                "plan": plan,
                "plan_hash": digest,
                "policies_before": policies,
                "roles_before": {
                    cast("dict[str, object]", u)["id"]: cast("dict[str, object]", u)["role"]
                    for u in users
                },
            },
            f,
        )
    created = _activate_policies(token, admin_id, plan)
    _require_activation_converged(token, state, created, users)
    fd = os.open(
        ROOT / "internal-network-activation-complete.json",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(fd, "w") as f:
        json.dump(
            {
                "policy_ids": created,
                "plan_hash": digest,
                "genuine_jwt_source": True,
                "exact_node_prefixes": [cast("dict[str, object]", p)["address"] for p in plan],
            },
            f,
        )
    print(
        "Native admin-only WG node policies created and read back. Real Mac routing/access acceptance still required."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("BLOCKED: " + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__))
        raise SystemExit(2)
