#!/usr/bin/env python3
"""Add the ordinary shared-browser group and one application binding, never members."""

import argparse
import fcntl
import hashlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "ri", Path(__file__).with_name("provision-redisinsight-oidc.py")
)
ri = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ri)
o = ri.oidc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True, type=Path)
    parser.add_argument("--approve-plan-hash")
    args = parser.parse_args()
    root = Path.home() / ".config/homelab/redisinsight"
    state = root / "oidc"
    with (state / "lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        marker = state / "uncertain.json"
        o.check(not marker.exists(), "Uncertain identity write; inspect first")
        api = o.iam.API(args.credentials, write=bool(args.approve_plan_hash))
        owner, settings, provider, app = o.inspect(api)
        file = state / "client.json"
        o.iam.private(file)
        journal = json.loads(file.read_text())
        group = ri.reader_group(api)
        existing = ri.extra_bindings(api, app)
        o.validate(api, owner, settings, provider, app, journal, existing.values())
        ops = ([] if group else ["create-empty-group"]) + (
            [] if existing else ["bind-to-redisinsight"]
        )
        plan = {
            "ops": ops,
            "name": ri.READERS,
            "app": app["pk"],
            "group": group and group["pk"],
            "owner": owner["pk"],
        }
        digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        if not args.approve_plan_hash or not ops:
            print(json.dumps({"operations": ops, "plan_hash": digest}))
            return
        o.check(digest == args.approve_plan_hash, "Plan hash changed")
        receipt = root / "readers-receipt.json"
        o.iam.private(receipt)
        data = json.loads(receipt.read_text())
        backup = Path(data["encryptedBackup"])
        o.iam.private(backup)
        age = (datetime.now(UTC) - datetime.fromisoformat(data["observedAt"])).total_seconds()
        o.check(
            0 <= age <= 3600 and hashlib.sha256(backup.read_bytes()).hexdigest() == data["sha256"],
            "Fresh encrypted backup required",
        )
        o.write_private(marker, plan)
        if not group:
            group = api.call(
                "POST",
                "core/groups/",
                {
                    "name": ri.READERS,
                    "attributes": ri.ATTRS,
                    "is_superuser": False,
                    "parents": [],
                    "children": [],
                    "roles": [],
                    "users": [],
                },
            )
        api.call(
            "POST",
            "policies/bindings/",
            {
                "target": app["pk"],
                "group": group["pk"],
                "order": 10,
                "enabled": True,
                "negate": False,
                "failure_result": False,
            },
        )
        group = ri.reader_group(api)
        o.validate(api, owner, settings, provider, app, journal, [group["pk"]])
        marker.unlink()
        print("Verified owner and reader bindings; no memberships changed.")


if __name__ == "__main__":
    main()
