#!/usr/bin/env python3
"""Pure target-only migration plan; no panel authentication, DB writes or Xray reload.

The policy is intent, not a claim of deployed state. A native API executor and
client acceptance must be reviewed before applying this plan.
"""

import argparse
import copy
import importlib.util
import json
import sqlite3
from contextlib import closing
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "inventory", Path(__file__).with_name("vpn-hardening-inventory.py")
)
if spec is None or spec.loader is None or not spec.has_location:
    reason = "Cannot load inventory helper"
    raise ValueError(reason)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def _inbounds(config: dict[str, object]) -> list[object]:
    value = config["inbounds"]
    return value if isinstance(value, list) else []


def _retarget(replacement: dict[str, object], key: str, new_target: object) -> None:
    reality = replacement["realitySettings"]
    if isinstance(reality, dict):
        reality[key] = new_target


def _restream(config: dict[str, object], row_id: object, canonical: object) -> None:
    for item in _inbounds(config):
        if isinstance(item, dict) and item["id"] == row_id:
            item["stream_settings"] = canonical


def build(config: dict[str, object], policy: dict[str, object]) -> dict[str, object]:
    if (
        policy.get("version") != 1
        or policy.get("newVpsOrPublicIp") is not False
        or policy.get("scope") != "existing-socrat-2-only"
    ):
        msg = "Unsupported scope"
        raise ValueError(msg)
    desired = policy["realityCorrection"]
    if not isinstance(desired, dict):
        reason = "Explicit apply policy required"
        raise TypeError(reason)
    if (
        not isinstance(desired.get("apiApplyEnabled"), bool)
        or desired.get("preserveClientMaterial") is not True
    ):
        msg = "Explicit apply policy and preserved client material required"
        raise ValueError(msg)
    matches = [x for x in _inbounds(config) if isinstance(x, dict) and x["port"] == desired["port"]]
    if len(matches) != 1:
        msg = "Expected exactly one target inbound"
        raise ValueError(msg)
    row = matches[0]
    stream: dict[str, object] = json.loads(str(row["stream_settings"]))
    if not row["enable"] or any(
        (
            row["protocol"] != desired["protocol"],
            stream.get("network") != desired["network"],
            stream.get("security") != desired["security"],
        )
    ):
        msg = "Unexpected transport or disabled inbound"
        raise ValueError(msg)
    reality = stream["realitySettings"]
    if not isinstance(reality, dict):
        reason = "Expected REALITY settings"
        raise TypeError(reason)
    if reality["serverNames"] != desired["serverNames"]:
        msg = "Unexpected client-visible SNI; do not migrate it implicitly"
        raise ValueError(msg)
    keys = [key for key in ("target", "dest") if key in reality]
    if len(keys) != 1:
        msg = "Ambiguous REALITY target schema"
        raise ValueError(msg)
    key = keys[0]
    current = reality[key]
    if current not in (desired["oldTarget"], desired["newTarget"]):
        msg = "Target drift; stop"
        raise ValueError(msg)
    after = copy.deepcopy(config)
    operations: list[dict[str, object]] = []
    if current != desired["newTarget"]:
        replacement = copy.deepcopy(stream)
        _retarget(replacement, key, desired["newTarget"])
        _restream(after, row["id"], inventory.canonical(replacement))
        operations.append(
            {
                "port": row["port"],
                "field": "realitySettings." + key,
                "old": current,
                "new": desired["newTarget"],
            }
        )
    result = {
        "before_configuration_sha256": inventory.digest(config),
        "planned_configuration_sha256": inventory.digest(after),
        "operations": operations,
        "preview_only": True,
        "production_writes": 0,
        "client_material_preserved": True,
        "requires_native_api_and_authenticated_client_acceptance": True,
    }
    plan: dict[str, object] = {**result, "plan_sha256": inventory.digest(result)}
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("/srv/x-ui-lab/db/x-ui.db"))
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()
    path = inventory.check_path(args.database)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(":memory:")) as snapshot:
            source.backup(snapshot)
            if snapshot.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                msg = "Integrity check failed"
                raise ValueError(msg)
            result = build(inventory.projection(snapshot), json.loads(args.policy.read_text()))
    print(inventory.canonical(result))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, ImportError, sqlite3.Error):
        msg = "Target preview stopped on unsupported state; no writes performed"
        raise SystemExit(msg) from None
