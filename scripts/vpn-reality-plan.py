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
from typing import cast

spec = importlib.util.spec_from_file_location(
    "inventory", Path(__file__).with_name("vpn-hardening-inventory.py")
)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def _validated_inbound(
    config: dict[str, object], policy: dict[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    """Validate migration policy and return the single matching inbound row."""
    if (
        policy.get("version") != 1
        or policy.get("newVpsOrPublicIp") is not False
        or policy.get("scope") != "existing-socrat-2-only"
    ):
        raise ValueError("Unsupported scope")
    desired = cast("dict[str, object]", policy["realityCorrection"])
    if (
        not isinstance(desired.get("apiApplyEnabled"), bool)
        or desired.get("preserveClientMaterial") is not True
    ):
        raise ValueError("Explicit apply policy and preserved client material required")
    rows = cast("list[dict[str, object]]", config["inbounds"])
    matches = [x for x in rows if x["port"] == desired["port"]]
    if len(matches) != 1:
        raise ValueError("Expected exactly one target inbound")
    return matches[0], desired


def _validate_transport(
    row: dict[str, object], stream: dict[str, object], desired: dict[str, object]
) -> tuple[str, str]:
    """Reject transport drift or a disabled inbound before any planning."""
    if not row["enable"] or any(
        (
            row["protocol"] != desired["protocol"],
            stream.get("network") != desired["network"],
            stream.get("security") != desired["security"],
        )
    ):
        raise ValueError("Unexpected transport or disabled inbound")
    reality = cast("dict[str, object]", stream["realitySettings"])
    if reality["serverNames"] != desired["serverNames"]:
        raise ValueError("Unexpected client-visible SNI; do not migrate it implicitly")
    keys = [key for key in ("target", "dest") if key in reality]
    if len(keys) != 1:
        raise ValueError("Ambiguous REALITY target schema")
    key: str = keys[0]
    current: object = reality[key]
    if current != desired["oldTarget"] and current != desired["newTarget"]:
        raise ValueError("Target drift; stop")
    return key, str(current)


def build(config, policy):
    row, desired = _validated_inbound(config, policy)
    stream = json.loads(cast("str", row["stream_settings"]))
    key, current = _validate_transport(row, stream, desired)
    after = copy.deepcopy(config)
    operations = []
    if current != desired["newTarget"]:
        replacement = copy.deepcopy(stream)
        replacement["realitySettings"][key] = desired["newTarget"]
        for item in after["inbounds"]:
            if item["id"] == row["id"]:
                item["stream_settings"] = inventory.canonical(replacement)
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
    return {**result, "plan_sha256": inventory.digest(result)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("/srv/x-ui-lab/db/x-ui.db"))
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()
    path = inventory.check_path(args.database)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(":memory:")) as snapshot:
            source.backup(snapshot)
            if snapshot.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError("Integrity check failed")
            result = build(inventory.projection(snapshot), json.loads(args.policy.read_text()))
    print(inventory.canonical(result))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Target preview stopped on unsupported state; no writes performed"
        ) from None
