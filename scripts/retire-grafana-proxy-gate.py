#!/usr/bin/env python3
"""Retire only the owned, unused Grafana proxy app after native SSO acceptance."""

import argparse
import fcntl
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
from pathlib import Path


def require(message: str, *, ok: bool):
    if not ok:
        raise RuntimeError(message)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--approve-plan-hash")
    a = p.parse_args()
    os.umask(0o077)
    loader = importlib.machinery.SourceFileLoader(
        "web", "/usr/local/sbin/homelab-public-web-access"
    )
    spec = importlib.util.spec_from_loader("web", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    api = m.API("/home/alchemmist/.cache/homelab-authentik/credentials.json")
    root = Path("/var/lib/homelab-retire-grafana-proxy")
    require("Unsafe state path", ok=not root.is_symlink())
    root.mkdir(mode=0o700, exist_ok=True)
    require(
        "Unsafe state ownership", ok=root.stat().st_uid == 0 and not root.stat().st_mode & 0o077
    )
    with (root / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        require("Uncertain previous write; stop", ok=not (root / "uncertain.json").exists())
        d = json.loads(
            subprocess.check_output(
                [
                    "kubectl",
                    "-n",
                    "cattle-monitoring-system",
                    "get",
                    "deploy",
                    "kube-prometheus-stack-grafana",
                    "-o",
                    "json",
                ]
            )
        )
        env = {
            e["name"]: e.get("value")
            for e in next(
                c for c in d["spec"]["template"]["spec"]["containers"] if c["name"] == "grafana"
            )["env"]
        }
        require(
            "Native policy not active",
            ok=env["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
            and env["GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN"] == "true",
        )
        ingress = json.loads(
            subprocess.check_output(
                ["kubectl", "-n", "identity", "get", "ingress", "public-web-grafana", "-o", "json"]
            )
        )
        require(
            "Old gate still routed",
            ok=ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]["name"]
            == "public-web-grafana-proxy",
        )
        s = m.snapshot(api)
        apps = [x for x in s["apps"] if x["slug"] == "public-web-grafana"]
        providers = [x for x in s["providers"] if x["name"] == "public-web-grafana"]
        if not apps and not providers:
            print(json.dumps({"operations": 0, "applied": False}))
            return
        require("Ambiguous owned gate", ok=len(apps) == len(providers) == 1)
        catalog = {
            "grafana": {
                "host": "grafana.socrat.alchemmist.xyz",
                "upstream": "http://kube-prometheus-stack-grafana.cattle-monitoring-system.svc.cluster.local:80",
                "admissionFrom": "grafana",
            }
        }
        ops, outpost = m.plan(s, catalog)
        require("Owned gate drift; do not delete", ok=not ops)
        app = apps[0]
        provider = providers[0]
        require(
            "Shared provider",
            ok=not any(x["provider"] == provider["pk"] and x["pk"] != app["pk"] for x in s["apps"]),
        )
        plan = {
            "app": app,
            "provider": provider,
            "outpost": outpost,
            "native_uid": d["metadata"]["uid"],
            "ingress_uid": ingress["metadata"]["uid"],
        }
        digest = hashlib.sha256(
            json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if a.apply:
            require("Fresh hash approval required", ok=a.approve_plan_hash == digest)
            (root / "before.json").write_text(json.dumps(s))
            (root / "uncertain.json").write_text(json.dumps(plan))
            api.call(
                "PATCH",
                "outposts/instances/" + outpost["pk"] + "/",
                {"providers": [p for p in outpost["providers"] if p != provider["pk"]]},
            )
            api.call("DELETE", "core/applications/public-web-grafana/")
            api.call("DELETE", "providers/proxy/" + str(provider["pk"]) + "/")
            after = m.snapshot(api)
            require(
                "Gate deletion not confirmed",
                ok=not any(x["slug"] == "public-web-grafana" for x in after["apps"]),
            )
            require(
                "Provider deletion not confirmed",
                ok=not any(x["pk"] == provider["pk"] for x in after["providers"]),
            )
            require(
                "Native app changed",
                ok=[x for x in s["apps"] if x["slug"] == "grafana"]
                == [x for x in after["apps"] if x["slug"] == "grafana"],
            )
            require("Group memberships changed", ok=s["groups"] == after["groups"])
            require(
                "Other outpost assignment changed",
                ok=next(x for x in after["outposts"] if x["pk"] == outpost["pk"])["providers"]
                == [p for p in outpost["providers"] if p != provider["pk"]],
            )
            (root / "after.json").write_text(json.dumps(after))
            (root / "uncertain.json").unlink()
        print(json.dumps({"operations": 3, "plan_hash": digest, "applied": a.apply}))


if __name__ == "__main__":
    main()
