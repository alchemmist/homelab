#!/usr/bin/env python3
"""Preserve existing Kuma DB credentials; detach only an obsolete GitOps tracking tag."""

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import cast

NS = "uptime-kuma"
NAME = "uptime-kuma-db"
TRACK = "uptime-kuma:/Secret:uptime-kuma/uptime-kuma-db"


def require(ok: object, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def get(kind: str, name: str, ns: str = NS) -> dict[str, object]:
    return cast(
        "dict[str, object]",
        json.loads(subprocess.check_output(["kubectl", "-n", ns, "get", kind, name, "-o", "json"])),
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--approve-plan-hash")
    a = p.parse_args()
    os.umask(0o077)
    root = Path("/var/lib/homelab-kuma-credential-ownership")
    require(not root.is_symlink(), "Unsafe state path")
    root.mkdir(mode=0o700, exist_ok=True)
    require(root.stat().st_uid == 0 and not root.stat().st_mode & 0o077, "Unsafe state ownership")
    with (root / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        require(not (root / "uncertain.json").exists(), "Uncertain prior write")
        before = get("secret", NAME)
        meta = cast("dict[str, object]", before["metadata"])
        ann = cast("dict[str, object]", meta.get("annotations", {}))
        require(
            ann.get("meta.helm.sh/release-name") == "uptime-kuma"
            and ann.get("meta.helm.sh/release-namespace") == NS,
            "Foreign secret",
        )
        data = cast("dict[str, object]", before["data"])
        require(
            set(data) == {"password", "root-password"} and all(data.values()),
            "Incomplete existing credentials",
        )
        if (
            "argocd.argoproj.io/tracking-id" not in ann
            and ann.get("helm.sh/resource-policy") == "keep"
        ):
            print(json.dumps({"operations": 0, "applied": False}))
            return
        require(ann.get("argocd.argoproj.io/tracking-id") == TRACK, "Foreign tracking owner")
        app = get("applications.argoproj.io", "uptime-kuma", "argocd")
        app_spec = cast("dict[str, object]", app["spec"])
        sync_policy = cast("dict[str, object]", app_spec["syncPolicy"])
        automated = cast("dict[str, object]", sync_policy["automated"])
        require(automated["prune"] is False, "Never prune credentials")
        app_status = cast("dict[str, object]", app["status"])
        resources = cast("list[dict[str, object]]", app_status["resources"])
        resource = next(r for r in resources if r["kind"] == "Secret" and r["name"] == NAME)
        require(
            resource.get("requiresPruning") is True,
            "Desired manifests still manage the credential: stop",
        )
        context = {
            "uid": meta["uid"],
            "resourceVersion": meta["resourceVersion"],
            "source_revision": cast("dict[str, object]", app_status["sync"])["revision"],
            "credential_hash": hashlib.sha256(
                json.dumps(data, sort_keys=True).encode()
            ).hexdigest(),
        }
        digest = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
        if a.apply:
            require(a.approve_plan_hash == digest, "Fresh plan hash required")
            (root / "before.json").write_text(json.dumps(before))
            (root / "uncertain.json").write_text(json.dumps(context))
            patch = [
                {"op": "test", "path": "/metadata/uid", "value": meta["uid"]},
                {
                    "op": "test",
                    "path": "/metadata/resourceVersion",
                    "value": meta["resourceVersion"],
                },
                {"op": "remove", "path": "/metadata/annotations/argocd.argoproj.io~1tracking-id"},
                {
                    "op": "add",
                    "path": "/metadata/annotations/helm.sh~1resource-policy",
                    "value": "keep",
                },
            ]
            subprocess.run(
                [
                    "kubectl",
                    "-n",
                    NS,
                    "patch",
                    "secret",
                    NAME,
                    "--type=json",
                    "--patch-file=/dev/stdin",
                ],
                input=json.dumps(patch),
                text=True,
                check=True,
                capture_output=True,
            )
            after = get("secret", NAME)
            after_meta = cast("dict[str, object]", after["metadata"])
            require(
                after_meta["uid"] == meta["uid"]
                and cast("dict[str, object]", after["data"]) == data,
                "Credential data changed; stop",
            )
            after_ann = cast("dict[str, object]", after_meta["annotations"])
            require(
                after_ann.get("argocd.argoproj.io/tracking-id") is None
                and after_ann.get("helm.sh/resource-policy") == "keep",
                "Ownership update not confirmed",
            )
            (root / "after.json").write_text(json.dumps(after))
            (root / "uncertain.json").unlink()
        print(
            json.dumps(
                {
                    "operations": 1,
                    "plan_hash": digest,
                    "applied": a.apply,
                    "credential_data_replacement": False,
                }
            )
        )


if __name__ == "__main__":
    main()
