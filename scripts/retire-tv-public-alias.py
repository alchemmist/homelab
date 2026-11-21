#!/usr/bin/env python3
"""Delete only the three exact resources created for the retired TV alias; never prune."""

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path("/var/lib/homelab-tv-alias-retirement")
OWNED = [
    (
        "ingress",
        "public-web-grafana-tv",
        "b1934513-0887-4bdc-b3d1-4468047cc002",
        "/apis/networking.k8s.io/v1/namespaces/identity/ingresses/",
    ),
    (
        "certificate",
        "public-web-grafana-tv-tls",
        "40174498-dae6-488f-b131-117092f625eb",
        "/apis/cert-manager.io/v1/namespaces/identity/certificates/",
    ),
    (
        "secret",
        "public-web-grafana-tv-tls",
        "49ba877b-f7af-4891-a842-095cc05b9cda",
        "/api/v1/namespaces/identity/secrets/",
    ),
]


def need(msg: str, *, ok: bool):
    if not ok:
        raise RuntimeError(msg)


def get(kind: str, name: str):
    r = subprocess.run(
        ["kubectl", "-n", "identity", "get", kind, name, "--ignore-not-found", "-o", "json"],
        capture_output=True,
        check=True,
    )
    return json.loads(r.stdout) if r.stdout.strip() else None


def inspect():
    out = []
    for kind, name, uid, path in OWNED:
        o = get(kind, name)
        if o:
            need("Unowned replacement; stop", ok=o["metadata"]["uid"] == uid)
            if kind == "ingress":
                need(
                    "Ingress ownership drift",
                    ok=o["spec"]["rules"][0]["host"] == "tv.alchemmist.xyz"
                    and o["metadata"]["annotations"].get("argocd.argoproj.io/tracking-id")
                    == "public-web-entry:networking.k8s.io/Ingress:identity/public-web-grafana-tv",
                )
            if kind == "certificate":
                need("Certificate scope drift", ok=o["spec"]["dnsNames"] == ["tv.alchemmist.xyz"])
            if kind == "secret":
                need(
                    "Secret scope drift",
                    ok=o["metadata"]["annotations"].get("cert-manager.io/alt-names")
                    == "tv.alchemmist.xyz",
                )
            out.append(o)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--approve-plan-hash")
    a = p.parse_args()
    os.umask(0o077)
    need("Unsafe state", ok=not ROOT.is_symlink())
    ROOT.mkdir(mode=0o700, exist_ok=True)
    need("Unsafe state", ok=ROOT.stat().st_uid == 0 and not ROOT.stat().st_mode & 0o077)
    with (ROOT / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        need("Uncertain deletion; inspect privately", ok=not (ROOT / "uncertain.json").exists())
        objects = inspect()
        h = hashlib.sha256(json.dumps(objects, sort_keys=True).encode()).hexdigest()
        if a.apply and objects:
            need("Fresh exact approval required", ok=a.approve_plan_hash == h)
            need("Existing cleanup backup; inspect", ok=not (ROOT / "before.json").exists())
            (ROOT / "before.json").write_text(json.dumps(objects))
            (ROOT / "uncertain.json").write_text(json.dumps({"plan_hash": h}))
            for kind, name, uid, path in OWNED:
                o = get(kind, name)
                if not o:
                    continue
                need("Concurrent replacement; stop", ok=o["metadata"]["uid"] == uid)
                options = {
                    "apiVersion": "v1",
                    "kind": "DeleteOptions",
                    "propagationPolicy": "Foreground",
                    "preconditions": {
                        "uid": uid,
                        "resourceVersion": o["metadata"]["resourceVersion"],
                    },
                }
                r = subprocess.run(
                    ["kubectl", "delete", "--raw", path + name, "-f", "-"],
                    input=json.dumps(options).encode(),
                    capture_output=True,
                )
                need(
                    "Scoped delete failed; inspect privately",
                    ok=r.returncode == 0 or b"NotFound" in r.stderr,
                )
            remaining = inspect()
            need(
                "Secret deletion not confirmed",
                ok=not any(o["kind"] == "Secret" for o in remaining),
            )
            (ROOT / "after.json").write_text(
                json.dumps({"plan_hash": h, "delete_requests_completed": True})
            )
            (ROOT / "uncertain.json").unlink()
        print(
            json.dumps(
                {"operations": len(objects), "plan_hash": h, "applied": bool(a.apply and objects)}
            )
        )


if __name__ == "__main__":
    main()
