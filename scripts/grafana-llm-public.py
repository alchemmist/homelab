#!/usr/bin/env python3
"""Audit/create native public sharing for ONE shared-model activity dashboard, no anonymous org."""

import argparse
import base64
import fcntl
import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import cast

UID = "socrat-llm-activity-public"
STATE = Path.home() / ".local/state/homelab-grafana-llm-public"


def need(ok: bool, msg: str) -> None:
    """Raise an error when a required condition is not met."""
    if not ok:
        raise RuntimeError(msg)


def main() -> None:
    """Run the command-line entry point."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--approve-plan-hash")
    a = p.parse_args()
    os.umask(0o077)
    need(not STATE.is_symlink(), "Unsafe state")
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    need(
        STATE.stat().st_uid == os.geteuid() and not STATE.stat().st_mode & 0o077,
        "Unsafe state ownership",
    )
    with (STATE / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        need(
            not (STATE / "uncertain.json").exists(),
            "Uncertain previous publication; inspect privately",
        )
        cmd = ["kubectl", "-n", "cattle-monitoring-system"]
        secret = json.loads(
            subprocess.check_output(
                cmd + ["get", "secret", "socrat-grafana-admin", "-o", "json"],
                stderr=subprocess.DEVNULL,
            )
        )["data"]
        ip = subprocess.check_output(
            cmd
            + ["get", "svc", "kube-prometheus-stack-grafana", "-o", "jsonpath={.spec.clusterIP}"],
            text=True,
        )
        auth = base64.b64encode(
            base64.b64decode(secret["admin-user"])
            + b":"
            + base64.b64decode(secret["admin-password"])
        ).decode()

        def api(
            method: str, path: str, data: dict[str, object] | None = None
        ) -> tuple[int, dict[str, object]]:
            req = urllib.request.Request(
                "http://" + ip + path,
                method=method,
                headers={"Authorization": "Basic " + auth, "Content-Type": "application/json"},
                data=None if data is None else json.dumps(data).encode(),
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return r.status, cast("dict[str, object]", json.load(r))
            except urllib.error.HTTPError as e:
                return e.code, cast("dict[str, object]", json.load(e))

        code, settings = api("GET", "/api/admin/settings")
        anonymous = cast("dict[str, object]", settings.get("auth.anonymous", {}))
        need(
            code == 200 and anonymous.get("enabled") in [False, "false"],
            "Organization anonymous access drift; refuse publication",
        )
        code, dashboard = api("GET", "/api/dashboards/uid/" + UID)
        dash = cast("dict[str, object]", dashboard["dashboard"])
        need(code == 200 and dash["uid"] == UID, "Unexpected dashboard")
        expected = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "charts/monitoring-k3s/dashboards/llm-activity-public.json"
            ).read_text()
        )
        live = dash
        need(
            live["panels"] == expected["panels"]
            and live["templating"] == {"list": []}
            and live["annotations"] == {"list": []}
            and live["links"] == [],
            "Unexpected public content; refuse publication",
        )
        endpoint = "/api/dashboards/uid/" + UID + "/public-dashboards"
        code, before = api("GET", endpoint)
        desired = {
            "isEnabled": True,
            "annotationsEnabled": False,
            "timeSelectionEnabled": True,
            "share": "public",
        }
        if code == 200:
            need((STATE / "after.json").exists(), "Existing unowned public share; do not adopt")
            owned = json.loads((STATE / "after.json").read_text())
            need(
                before["uid"] == owned["uid"]
                and before["accessToken"] == owned["accessToken"]
                and all(before.get(k) == v for k, v in desired.items()),
                "Public share drift",
            )
            print(json.dumps({"operations": 0, "applied": False, "dashboard": UID}))
            return
        need(code == 404, "Unexpected sharing API response")
        context = {
            "dashboard": dashboard,
            "share_before": before,
            "desired": desired,
            "tool": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        digest = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
        if a.apply:
            need(a.approve_plan_hash == digest, "Fresh exact plan approval required")
            (STATE / "before.json").write_text(json.dumps(context))
            (STATE / "uncertain.json").write_text(json.dumps({"plan_hash": digest}))
            code, after = api("POST", endpoint, desired)
            need(code in [200, 201], "Public share create failed; no fallback to anonymous Viewer")
            code, verify = api("GET", endpoint)
            need(
                code == 200 and all(verify.get(k) == v for k, v in desired.items()),
                "Public sharing readback failed",
            )
            code, unchanged = api("GET", "/api/dashboards/uid/" + UID)
            need(
                code == 200 and unchanged["dashboard"] == dash,
                "Dashboard content changed during publication",
            )
            (STATE / "after.json").write_text(json.dumps(verify))
            token = cast("str", verify["accessToken"])
            need(
                len(token) == 32 and all(c in "0123456789abcdef" for c in token),
                "Unexpected public URL identifier",
            )
            url = "https://grafana.socrat.alchemmist.xyz/public-dashboards/" + token
            (STATE / "public-url.json").write_text(json.dumps({"startURL": url}))
            (STATE / "uncertain.json").unlink()
        print(
            json.dumps(
                {
                    "operations": 1,
                    "plan_hash": digest,
                    "applied": a.apply,
                    "dashboard": UID,
                    "anonymous_org_access": False,
                }
            )
        )


if __name__ == "__main__":
    main()
